#!/usr/bin/env python3
"""Check curated Markdown, prepare a staging tree, or build local MkDocs HTML.

Only ``build`` needs requirements-docs.txt. No command publishes or downloads
content. Staging is an explicit allowlist, never a copy of the repository.
"""

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit, urlunsplit


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
    if data.get("version") != 1 or not data.get("pages"):
        raise DocsError("Unsupported or empty documentation manifest")
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
                if not entry.get("title") or not entry.get("section"):
                    raise DocsError("Page title and section are required: " + source)
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


def target_link(link, source, destination, mapping, manifest, counts):
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
        new_path = posixpath.relpath(mapping[relative], posixpath.dirname(destination) or ".")
        counts["site_links"] += 1
        return urlunsplit(("", "", quote(new_path, safe="/._-"), parts.query, parts.fragment))
    counts["repository_fallback_links"] += 1
    kind = "tree" if target.is_dir() else "blob"
    path = "/{}/{}/{}".format(kind, quote(manifest["branch"], safe="/._-"), quote(relative, safe="/._-"))
    return manifest["repository"].rstrip("/") + path + ("?" + parts.query if parts.query else "") + ("#" + parts.fragment if parts.fragment else "")


def checked_pages(manifest):
    counts = {key: 0 for key in ("external_links", "anchor_links", "repository_links", "site_links", "repository_fallback_links")}
    mapping = {entry["source"]: entry["destination"] for kind in ("pages", "assets") for entry in manifest[kind]}
    rewritten, errors = {}, []
    for entry in manifest["pages"]:
        source, destination = entry["source"], entry["destination"]
        text = source_path(source).read_text(encoding="utf-8")
        replacements = []
        try:
            for start, end in link_spans(text, source):
                try:
                    value = target_link(text[start:end], source, destination, mapping, manifest, counts)
                    replacements.append((start, end, value))
                except DocsError as error:
                    line = text.count("\n", 0, start) + 1
                    errors.append("{}:{}: {}".format(source, line, error))
        except DocsError as error:
            errors.append(str(error))
        for start, end, value in reversed(replacements):
            text = text[:start] + value + text[end:]
        rewritten[destination] = text
    if errors:
        raise DocsError("Documentation check failed:\n" + "\n".join(errors))
    counts.update({"status": "passed", "pages": len(manifest["pages"]), "assets": len(manifest["assets"]),
                   "network_requests": 0, "manifest": "docs/site-pages.json"})
    return rewritten, counts


def output_path(value, label):
    path = Path(value).expanduser().resolve()
    if path == ROOT or path.is_relative_to(ROOT) or ROOT.is_relative_to(path):
        raise DocsError(label + " must be outside the source checkout: " + str(path))
    if path == Path(path.anchor) or path == Path("/tmp") or path == Path.home():
        raise DocsError(label + " must be a dedicated output directory")
    return path


def prepare(manifest, rewritten, work, site):
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
        if previous.get("format") != "gymts-docs-staging/1" or previous.get("repository") != str(ROOT):
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
    for destination, text in rewritten.items():
        target = staged / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for entry in manifest["assets"]:
        target = staged / entry["destination"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_path(entry["source"]).read_bytes())
    sections = {}
    for entry in manifest["pages"]:
        sections.setdefault(entry["section"], []).append({entry["title"]: entry["destination"]})
    config = {"INHERIT": str(ROOT / "mkdocs.yml"), "docs_dir": str(staged), "site_dir": str(site),
              "nav": [{section: entries} for section, entries in sections.items()]}
    config_path = work / "mkdocs.generated.yml"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files = sorted([*rewritten, *(entry["destination"] for entry in manifest["assets"])])
    marker.write_text(json.dumps({"format": "gymts-docs-staging/1", "repository": str(ROOT), "files": files}, indent=2) + "\n", encoding="utf-8")
    return {"work": str(work), "source": str(staged), "site_dir": str(site), "config": str(config_path),
            "staged_files": len(files), "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest()}


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links, self.remote_resources = set(), [], []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
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
    args = parser.parse_args()
    try:
        manifest = load_manifest()
        rewritten, report = checked_pages(manifest)
        if args.command != "check":
            site = Path(args.site_dir).expanduser().resolve() if args.site_dir else Path(args.work).expanduser().resolve() / "site"
            report.update(prepare(manifest, rewritten, args.work, site))
            if args.command == "build":
                if site.exists() and any(site.iterdir()):
                    raise DocsError("Site output must be empty; choose a new directory: " + str(site))
                result = subprocess.run([sys.executable, "-B", "-m", "mkdocs", "build", "--strict",
                                         "--config-file", report["config"]], cwd=str(ROOT),
                                        stdout=sys.stderr, stderr=sys.stderr, check=False)
                if result.returncode:
                    raise DocsError("MkDocs build failed; install requirements-docs.txt and inspect the messages above")
                report.update(check_html(site))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (DocsError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
