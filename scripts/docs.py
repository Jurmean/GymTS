#!/usr/bin/env python3
"""Check curated bilingual Markdown, prepare staging, or build MkDocs HTML.

``prepare`` and ``build`` need requirements-docs.txt. No command publishes or downloads
content. Staging is an explicit allowlist, never a copy of the repository.
"""

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import sys
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/site-pages.json"
BLOCKED = {".git", ".env", ".aws", ".ssh", "output", "outputs", "node_modules",
           ".venv", "venv", "build", "dist", "__pycache__"}
MARKER = ".gymts-docs-staging.json"


class DocsError(Exception):
    pass


def source_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise DocsError("Source path must be relative to the repository: " + value)
    if any(part in BLOCKED or part.startswith(".gymts") for part in path.parts):
        raise DocsError("Local/private material is outside the documentation scope: " + value)
    resolved = ROOT.joinpath(*path.parts).resolve()
    if not resolved.is_relative_to(ROOT):
        raise DocsError("Source path escapes the repository: " + value)
    return resolved


def load_manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("version") != 2 or not data.get("pages"):
        raise DocsError("Unsupported or empty documentation manifest")
    if set(data.get("languages", {})) != {"zh", "en"}:
        raise DocsError("The documentation requires complete zh and en language catalogs")
    sources, destinations = set(), set()
    for kind in ("pages", "assets"):
        for entry in data[kind]:
            source, destination = entry["source"], entry["destination"]
            path = PurePosixPath(destination)
            if (path.is_absolute() or ".." in path.parts or "\\" in destination
                    or not destination or any(part.startswith(".") for part in path.parts)):
                raise DocsError("Unsafe staging destination: " + destination)
            if source in sources or destination in destinations:
                raise DocsError("Duplicate source or destination: " + source)
            sources.add(source)
            destinations.add(destination)
            actual = source_path(source)
            if not actual.is_file() or (ROOT / source).is_symlink():
                raise DocsError("Missing or symbolic-link documentation source: " + source)
            if kind == "pages":
                if actual.suffix != ".md" or not destination.endswith(".md"):
                    raise DocsError("Pages must use Markdown: " + source)
                if entry.get("translated_source_sha256") != hashlib.sha256(actual.read_bytes()).hexdigest():
                    raise DocsError("Source changed: update the English translation and translated_source_sha256 for " + source)
                for locale in data["languages"]:
                    if not entry.get("title", {}).get(locale) or not entry.get("section", {}).get(locale):
                        raise DocsError("Localized title and section are required: " + source)
                    localized = entry.get("translations", {}).get(locale, source if locale == "zh" else "")
                    if not localized or not source_path(localized).is_file() or (ROOT / localized).is_symlink():
                        raise DocsError("Missing translation for {}: {}".format(locale, source))
                for alias in entry.get("aliases", []):
                    source_path(alias)
                    if alias in sources:
                        raise DocsError("Duplicate documentation alias: " + alias)
                    sources.add(alias)
    repository = urlsplit(data["repository"])
    if repository.scheme != "https" or repository.netloc != "github.com":
        raise DocsError("Expected an HTTPS GitHub repository URL")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", data["branch"]):
        raise DocsError("Invalid repository branch")
    return data


def mask_code(text, source):
    """Preserve offsets, ignoring links inside common fenced/inline code."""
    lines, fence = [], None
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence is None and match:
            fence = (match[1][0], len(match[1]), number)
            lines.append(re.sub(r"[^\r\n]", " ", line))
        elif fence is not None:
            lines.append(re.sub(r"[^\r\n]", " ", line))
            if match and match[1][0] == fence[0] and len(match[1]) >= fence[1] and not match[2].strip():
                fence = None
        else:
            lines.append(line)
    if fence:
        raise DocsError("{}:{}: unclosed code fence".format(source, fence[2]))
    result = "".join(lines)
    return re.sub(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)",
                  lambda match: re.sub(r"[^\r\n]", " ", match[0]), result, flags=re.S)


def link_spans(text, source):
    """Yield destination-only spans for inline links, definitions and HTML."""
    visible = mask_code(text, source)
    spans = []
    for match in re.finditer(r"!?\[(?:\\.|[^\]\\])*\]\(", visible):
        start = match.end()
        while start < len(visible) and visible[start].isspace():
            start += 1
        if start == len(visible):
            continue
        if visible[start] == "<":
            end = visible.find(">", start + 1)
            if end < 0:
                raise DocsError(source + ": unterminated angle-bracket link")
            spans.append((start + 1, end))
            continue
        end, nesting = start, 0
        while end < len(visible):
            char = visible[end]
            if char == "\\":
                end += 2
                continue
            if char == "(":
                nesting += 1
            elif char == ")":
                if nesting == 0:
                    break
                nesting -= 1
            elif char.isspace() and nesting == 0:
                break
            end += 1
        if end > start:
            spans.append((start, end))
    for match in re.finditer(r"^ {0,3}\[[^\]\n]+\]:[ \t]*(<([^>\n]+)>|([^\s]+))", visible, re.M):
        group = 2 if match[2] is not None else 3
        spans.append(match.span(group))
    for match in re.finditer(r"\b(?:href|src)\s*=\s*([\"'])(.*?)\1", visible, re.I):
        spans.append(match.span(2))
    previous = -1
    for start, end in sorted(set(spans)):
        if start < previous:
            continue
        previous = end
        yield start, end


def target_link(link, source, destination, mapping, manifest, counts, html_link=False):
    parts = urlsplit(link)
    if parts.scheme or parts.netloc:
        if parts.scheme not in ("http", "https", "mailto", "tel", ""):
            raise DocsError("{}: unsupported link scheme: {}".format(source, parts.scheme))
        counts["external_links"] += 1
        return link
    if not parts.path:
        counts["anchor_links"] += 1
        return link
    decoded = unquote(parts.path)
    if decoded.startswith(("/", "\\")):
        raise DocsError("{}: absolute local link: {}".format(source, link))
    target = (ROOT / source).parent.joinpath(decoded).resolve()
    if not target.is_relative_to(ROOT):
        raise DocsError("{}: link escapes the repository: {}".format(source, link))
    relative = target.relative_to(ROOT).as_posix()
    source_path(relative)
    if not target.exists():
        raise DocsError("{}: missing link target: {}".format(source, link))
    counts["repository_links"] += 1
    if relative in mapping:
        mapped = mapping[relative]
        if html_link:
            target_url = page_url(mapped) if mapped.endswith(".md") else mapped
            new_path = posixpath.relpath(target_url or ".", page_url(destination) or ".")
            if mapped.endswith(".md"):
                new_path = new_path.rstrip("/") + "/"
        else:
            new_path = posixpath.relpath(mapped, posixpath.dirname(destination) or ".")
        counts["site_links"] += 1
        return urlunsplit(("", "", quote(new_path, safe="/._-"), parts.query, parts.fragment))
    counts["repository_fallback_links"] += 1
    kind = "tree" if target.is_dir() else "blob"
    path = "/{}/{}/{}".format(kind, quote(manifest["branch"], safe="/._-"), quote(relative, safe="/._-"))
    return manifest["repository"].rstrip("/") + path + ("?" + parts.query if parts.query else "") + ("#" + parts.fragment if parts.fragment else "")


def checked_pages(manifest):
    counts = {key: 0 for key in ("external_links", "anchor_links", "repository_links", "site_links", "repository_fallback_links")}
    rewritten, errors = {}, []
    for locale in manifest["languages"]:
        mapping = {entry["source"]: locale + "/" + entry["destination"]
                   for kind in ("pages", "assets") for entry in manifest[kind]}
        for entry in manifest["pages"]:
            for alias in entry.get("aliases", []):
                mapping[alias] = locale + "/" + entry["destination"]
        for entry in manifest["pages"]:
            source = entry["source"]
            localized = entry.get("translations", {}).get(locale, source)
            destination = locale + "/" + entry["destination"]
            text = source_path(localized).read_text(encoding="utf-8")
            replacements = []
            try:
                for start, end in link_spans(text, localized):
                    try:
                        html_link = bool(re.search(r"\b(?:href|src)\s*=\s*[\"']$", text[max(0, start - 30):start], re.I))
                        value = target_link(text[start:end], source, destination, mapping, manifest, counts, html_link)
                        replacements.append((start, end, value))
                    except DocsError as error:
                        line = text.count("\n", 0, start) + 1
                        errors.append("{}:{}: {}".format(localized, line, error))
            except DocsError as error:
                errors.append(str(error))
            for start, end, value in reversed(replacements):
                text = text[:start] + value + text[end:]
            rewritten[destination] = text
    if errors:
        raise DocsError("Documentation check failed:\n" + "\n".join(errors))
    counts.update({"status": "passed", "pages": len(rewritten), "pages_per_language": len(manifest["pages"]),
                   "languages": list(manifest["languages"]), "assets": len(manifest["assets"]),
                   "network_requests": 0, "manifest": "docs/site-pages.json"})
    return rewritten, counts


def output_path(value, label):
    path = Path(value).expanduser().resolve()
    if path == ROOT or path.is_relative_to(ROOT) or ROOT.is_relative_to(path):
        raise DocsError(label + " must be outside the source checkout: " + str(path))
    if path == Path(path.anchor) or path == Path("/tmp") or path == Path.home():
        raise DocsError(label + " must be a dedicated output directory")
    return path


def heading_tokens(text):
    try:
        import markdown
        from markdown.extensions.toc import slugify_unicode
    except ImportError:
        raise DocsError("Install requirements-docs.txt before prepare/build")
    rendered = markdown.Markdown(extensions=["fenced_code", "tables", "attr_list", "toc"],
                                 extension_configs={"toc": {"slugify": slugify_unicode}})
    rendered.convert(text)
    def flatten(items):
        result = []
        for item in items:
            result.append((item["level"], item["id"]))
            result.extend(flatten(item["children"]))
        return result
    return flatten(rendered.toc_tokens)


def stable_translation_anchors(original, translated, source):
    """Give translated headings the original IDs, preserving old deep links."""
    old, new = heading_tokens(original), heading_tokens(translated)
    if [level for level, anchor in old] != [level for level, anchor in new]:
        raise DocsError("Translation heading structure differs: " + source)
    lines = translated.splitlines(keepends=True)
    visible = mask_code(translated, source).splitlines(keepends=True)
    positions = [index for index, line in enumerate(visible) if re.match(r"^ {0,3}#{1,6}\s+", line)]
    if len(positions) != len(old):
        raise DocsError("Translated headings must use ATX syntax: " + source)
    for index, (level, anchor) in zip(positions, old):
        line = lines[index].rstrip("\r\n")
        line = re.sub(r"\s+\{#[^}]+\}\s*$", "", line)
        line = re.sub(r"\s+#+\s*$", "", line)
        lines[index] = line + " {#" + anchor + "}\n"
    return "".join(lines)


def page_url(destination):
    path = PurePosixPath(destination)
    if path.name == "index.md":
        parent = path.parent.as_posix()
        return "" if parent == "." else parent + "/"
    return path.with_suffix("").as_posix() + "/"


def prepare(manifest, rewritten, work, site, site_url):
    work = output_path(work, "Work directory")
    site = output_path(site, "Site directory")
    if site == work or work.is_relative_to(site) or site.is_relative_to(work / "source"):
        raise DocsError("Site directory must not contain staging or be inside staging/source")
    marker = work / MARKER
    if marker.is_symlink() or (work / "source").is_symlink():
        raise DocsError("Staging marker and source directory must not be symbolic links")
    if work.exists() and any(work.iterdir()) and not marker.is_file():
        raise DocsError("Refusing an existing nonempty unowned work directory: " + str(work))
    if marker.exists():
        previous = json.loads(marker.read_text(encoding="utf-8"))
        if previous.get("format") != "gymts-docs-staging/2" or previous.get("repository") != str(ROOT):
            raise DocsError("Work marker belongs to a different source checkout")
        previous_sources = set(previous["files"])
        for old in previous_sources:
            relative = PurePosixPath(old)
            if relative.is_absolute() or ".." in relative.parts or "\\" in old:
                raise DocsError("Invalid file path in staging marker")
            candidate = work / "source" / old
            if not candidate.resolve().is_relative_to(work / "source"):
                raise DocsError("Staging file escapes its source directory")
            if candidate.exists():
                if not candidate.is_file() or candidate.is_symlink():
                    raise DocsError("Unexpected staging entry: " + str(candidate))
                candidate.unlink()
    work.mkdir(parents=True, exist_ok=True)
    staged = work / "source"
    staged.mkdir(exist_ok=True)
    # Do not let a custom file silently enter MkDocs's static-file copying.
    if any(path.is_file() or path.is_symlink() for path in staged.rglob("*")):
        raise DocsError("Unexpected file in staging/source; choose a new work directory")
    configs, files = {}, []
    for locale, settings in manifest["languages"].items():
        other = next(language for language in manifest["languages"] if language != locale)
        sections = {}
        for entry in manifest["pages"]:
            destination = locale + "/" + entry["destination"]
            text = rewritten[destination]
            if locale != "zh":
                text = stable_translation_anchors(rewritten["zh/" + entry["destination"]], text, entry["source"])
            relative_url = page_url(entry["destination"])
            current = locale + "/" + relative_url
            alternate = other + "/" + relative_url
            source = entry.get("translations", {}).get(locale, entry["source"])
            metadata = {"title": entry["title"][locale], "home": entry.get("home", False),
                        "normative_translation": entry["destination"] == "reference/contract.md",
                        "alternate_url": posixpath.relpath(alternate, current or ".") + "/",
                        "alternate_absolute": urljoin(site_url, alternate),
                        "source_url": manifest["repository"] + "/blob/" + manifest["branch"] + "/" + quote(source, safe="/._-")}
            target = staged / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("---\n" + json.dumps(metadata, ensure_ascii=False) + "\n---\n\n" + text, encoding="utf-8")
            files.append(destination)
            sections.setdefault(entry["section"][locale], []).append({entry["title"][locale]: entry["destination"]})
        for entry in manifest["assets"]:
            destination = locale + "/" + entry["destination"]
            target = staged / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source_path(entry["source"]).read_bytes())
            files.append(destination)
        config = {"INHERIT": str(ROOT / "mkdocs.yml"), "docs_dir": str(staged / locale),
                  "site_dir": str(site / locale), "site_url": urljoin(site_url, locale + "/"),
                  "theme": {"name": None, "custom_dir": str(ROOT / "docs/theme"), "static_templates": ["404.html"]},
                  "site_description": settings["description"],
                  "extra": {"locale": locale, "other_locale": other, "labels": settings["labels"],
                            "license_url": "LICENSE"},
                  "nav": [{section: entries} for section, entries in sections.items()]}
        config_path = work / ("mkdocs." + locale + ".yml")
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        configs[locale] = str(config_path)
    marker.write_text(json.dumps({"format": "gymts-docs-staging/2", "repository": str(ROOT), "files": sorted(files)}, indent=2) + "\n", encoding="utf-8")
    return {"work": str(work), "source": str(staged), "site_dir": str(site), "configs": configs,
            "staged_files": len(files), "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest()}


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links, self.remote_resources = set(), [], []
        self.article_depth, self.article_text = 0, []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "article":
            self.article_depth += 1
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("name"):
            self.ids.add(attrs["name"])
        for key in ("href", "src"):
            if attrs.get(key):
                self.links.append((tag, key, attrs[key]))
        resource = attrs.get("src") if tag == "script" else attrs.get("href") if tag == "link" and attrs.get("rel") == "stylesheet" else None
        if resource and (urlsplit(resource).scheme or resource.startswith("//")):
            self.remote_resources.append(resource)

    def handle_endtag(self, tag):
        if tag == "article" and self.article_depth:
            self.article_depth -= 1

    def handle_data(self, data):
        if self.article_depth:
            self.article_text.append(data)


def finish_site(manifest, site, site_url):
    for locale in manifest["languages"]:
        index = []
        for entry in manifest["pages"]:
            url = page_url(entry["destination"])
            path = site / locale / url / "index.html"
            parser = PageLinks()
            parser.feed(path.read_text(encoding="utf-8"))
            index.append({"title": entry["title"][locale], "url": url,
                          "text": re.sub(r"\s+", " ", " ".join(parser.article_text)).strip()})
        (site / locale / "search.json").write_text(json.dumps({"locale": locale, "pages": index}, ensure_ascii=False), encoding="utf-8")
    landing = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="GymTS documentation in English and Chinese"><title>GymTS Documentation · 中文 / English</title><link rel="icon" href="zh/assets/favicon.svg" type="image/svg+xml"><style>body{font:16px/1.7 system-ui,sans-serif;max-width:620px;margin:13vh auto;padding:30px;color:#142638}h1{font-size:42px;letter-spacing:-1px}a{display:inline-block;padding:12px 20px;margin:10px 10px 0 0;background:#087f6d;color:white;border-radius:7px;text-decoration:none}p{color:#657386}</style></head><body><main><p>GymTS · Documentation</p><h1>Experiments. Evidence. Evaluation.</h1><p>时间序列实验、执行证据与独立评价。选择语言 / Choose your language.</p><a href="zh/" lang="zh">中文文档 →</a><a href="en/" lang="en">English documentation →</a></main><script>try{var language=localStorage.getItem('gymts-lang')||((navigator.language||'').toLowerCase().startsWith('zh')?'zh':'en');if(language==='zh'||language==='en')location.replace(language+'/'+location.search+location.hash)}catch(e){}</script></body></html>'''
    (site / "index.html").write_text(landing, encoding="utf-8")
    (site / "404.html").write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>404 · GymTS</title></head><body style="font-family:system-ui;padding:10vh 8vw"><h1>Page not found / 页面不存在</h1><p><a href="' + html.escape(site_url, quote=True) + '">GymTS Documentation →</a></p></body></html>', encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    # Each locale emits a sitemap; keep a single discoverable index at the root.
    sitemap = '<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join('<sitemap><loc>' + html.escape(urljoin(site_url, locale + '/sitemap.xml')) + '</loc></sitemap>' for locale in manifest['languages']) + '</sitemapindex>'
    (site / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (site / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: " + urljoin(site_url, "sitemap.xml") + "\n", encoding="utf-8")


def check_html(site):
    pages, errors, links = {}, [], 0
    for path in site.rglob("*.html"):
        parser = PageLinks()
        parser.feed(path.read_text(encoding="utf-8"))
        pages[path] = parser
        if parser.remote_resources:
            errors.append(str(path) + ": remote script/stylesheet resource")
    for path, parser in pages.items():
        for tag, key, value in parser.links:
            parts = urlsplit(value)
            if parts.scheme or parts.netloc or parts.path.startswith("/"):
                continue
            # Theme UI links (modal dialogs and shortcut controls) are not document anchors.
            if value == "#":
                continue
            target = path.parent.joinpath(unquote(parts.path)).resolve() if parts.path else path
            if target.is_dir():
                target = target / "index.html"
            if not target.is_relative_to(site) or not target.exists():
                errors.append("{}: missing local HTML target {}".format(path.relative_to(site), value))
            elif parts.fragment and target in pages and unquote(parts.fragment) not in pages[target].ids:
                errors.append("{}: missing local anchor {}".format(path.relative_to(site), value))
            links += 1
    if errors:
        raise DocsError("Built HTML check failed:\n" + "\n".join(errors))
    return {"html_pages": len(pages), "local_html_links_checked": links, "remote_script_stylesheets": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Check explicit sources and local links without third-party dependencies")
    for name in ("prepare", "build"):
        child = sub.add_parser(name)
        child.add_argument("--work", default="/tmp/gymts-docs-build")
        child.add_argument("--site-dir", help="Empty/nonexistent local HTML output directory; defaults to WORK/site")
        child.add_argument("--site-url", default="https://gymts-docs.zrr9392.chatgpt.site/", help="Canonical public site origin, including any hosting subpath")
    args = parser.parse_args()
    try:
        manifest = load_manifest()
        rewritten, report = checked_pages(manifest)
        if args.command != "check":
            site = Path(args.site_dir).expanduser().resolve() if args.site_dir else Path(args.work).expanduser().resolve() / "site"
            parsed_url = urlsplit(args.site_url)
            if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc or parsed_url.query or parsed_url.fragment:
                raise DocsError("Site URL must be an HTTP(S) origin/path without query or fragment")
            site_url = args.site_url.rstrip("/") + "/"
            report.update(prepare(manifest, rewritten, args.work, site, site_url))
            if args.command == "build":
                if site.exists() and any(site.iterdir()):
                    raise DocsError("Site output must be empty; choose a new directory: " + str(site))
                for locale, config in report["configs"].items():
                    result = subprocess.run([sys.executable, "-B", "-m", "mkdocs", "build", "--strict",
                                             "--config-file", config], cwd=str(ROOT),
                                            stdout=sys.stderr, stderr=sys.stderr, check=False)
                    if result.returncode:
                        raise DocsError("MkDocs build failed for " + locale + "; install requirements-docs.txt and inspect the messages above")
                finish_site(manifest, site, site_url)
                report.update(check_html(site))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (DocsError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
