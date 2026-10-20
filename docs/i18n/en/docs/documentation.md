# Bilingual documentation: build and publish

Public site: [GymTS Documentation](https://gymts-docs.zrr9392.chatgpt.site/), with direct
[Chinese](https://gymts-docs.zrr9392.chatgpt.site/zh/) and
[English](https://gymts-docs.zrr9392.chatgpt.site/en/) entry points. The site provides corresponding-page
language switching, browser-local search, navigation, page outlines, code copying, light and dark modes,
and mobile navigation.

## 1. Sources and publication boundaries

[site-pages.json](site-pages.json) is the explicit publication manifest. Each of 42 pages has Chinese
and English content, for 84 content pages. Chinese reads the repository originals; full English
translations live at `docs/i18n/en/<original repository path>`. Home pages are
`docs/site/zh/index.md` and `docs/site/en/index.md`. Translations preserve code, API identifiers,
versions, and evaluation boundaries. The Chinese public contract is normative; English is its translation.

Relative links in translations resolve against the manifest's original source directory rather than
the translated file's directory. This keeps one copy of code and examples without copying data or
run artifacts. Selected pages map to the current language; other public source links point to GitHub.
Translated headings retain the original Chinese section IDs at build time, preserving cross-language
and existing deep links.

Only selected content, two explicitly listed text assets, and local `docs/theme/` resources are
published. Historical drafts, private attachment audits, questions and answers, datasets, weights,
SQLite/CAS, raw logs, and `output/` are excluded. The site loads no remote scripts, analytics,
fonts, or styles. Search indexes contain public page content; queries are processed in the browser.

## 2. Dependency-free source checks

```bash
python3 -B scripts/docs.py check
```

`check` uses only the Python standard library. It verifies the bilingual manifest, complete
translations, code fences, and local source-link targets. It makes no network requests and does
not establish external URL availability or successful remote deployment. `prepare/build` also verify
translated heading structure and generate stable anchors. Final HTML links and anchors are checked individually.

## 3. Build and preview locally

Documentation dependencies are separate from the core runtime:

```bash
python3 -m venv /tmp/gymts-docs-venv
/tmp/gymts-docs-venv/bin/python -m pip install -r requirements-docs.txt
/tmp/gymts-docs-venv/bin/python -B scripts/docs.py build \
  --work /tmp/gymts-docs-build --site-dir /tmp/gymts-docs-site
python3 -m http.server 8000 --bind 127.0.0.1 --directory /tmp/gymts-docs-site
```

Open `http://127.0.0.1:8000/zh/` or `/en/`; stop the server with Ctrl-C. The root entry chooses
the browser language or the last selection. Both language links remain available without JavaScript.
The default public canonical URL is this deployment's origin; the local HTTP address is only a preview.

After dependency installation, builds make no network requests. For offline installation, prepare
a wheelhouse and use `pip install --no-index --find-links /path/to/wheelhouse -r requirements-docs.txt`.
The builder does not run experiments, train models, create Git branches, or deploy services.

Use dedicated output directories outside the source checkout. Never use `/tmp`, source, data,
or model directories themselves as output targets. The script cleans only its own marked staging
files and refuses to recursively delete unknown directories. Site output must be empty or absent;
choose a new directory for a rebuild.

## 4. Prepare inputs and change hosting

To prepare both language inputs and configurations without rendering:

```bash
/tmp/gymts-docs-venv/bin/python -B scripts/docs.py prepare --work /tmp/gymts-docs-input
```

The result includes `mkdocs.zh.yml`, `mkdocs.en.yml`, and `source/zh/`, `source/en/`.
Use `build` for publication: it also generates the language entry, two local search indexes,
404 pages, sitemaps, and robots.txt.

For a different domain or a GitHub Pages subdirectory, supply the complete site prefix:

```bash
/tmp/gymts-docs-venv/bin/python -B scripts/docs.py build \
  --work /tmp/gymts-docs-rehost --site-dir /tmp/gymts-docs-rehost-site \
  --site-url https://example.org/GymTS/
```

Pages, assets, and language switches use relative links. `--site-url` sets canonical and alternate
URLs, sitemaps, and the 404 return link. Serve the complete output directory with a static HTTP
host; deployment needs no GymTS runtime, model service, or private data.

## 5. Maintain translations and the theme

When Chinese sources change, update the corresponding English mirrors. Preserve heading levels,
order, complete section content, API identifiers, and executable code. A short English overview is
not a replacement for a full guide; missing translations must not silently fall back to Chinese.
`translated_source_sha256` in the manifest pins the translation's source. After synchronizing the
translation, update that field using `sha256sum original-source-file`. Checks fail if a source
changes without synchronization. New pages need both languages' titles, sections, and sources.

The [theme](theme/main.html) uses MkDocs templates and local CSS / JavaScript. Before publication,
check desktop and mobile layouts, especially menu focus, search, themes, corresponding-page language
switches, and code copying. Supply new scripts and styles locally and preserve their licenses.
The framework core and project adapters do not depend on the documentation theme or hosting provider.

## 6. CI and online publication

The [documentation workflow](../.github/workflows/docs.yml) checks and strictly builds both languages
on push/PR, then provides a downloadable artifact. It has read-only repository permissions and does
not call Sites automatically or establish that GitHub Pages has been enabled.

The current public site is hosted by Sites. Its identity is recorded in
[.openai/hosting.json](../.openai/hosting.json). Reuse that project ID for updates, rebuild, synchronize
the checked static directory in a separate publication workspace, then save and deploy its version.
Short-lived publication credentials pass only through the tool session, never the repository or
build output. Do not change the main repository's remote to the hosting provider's source address.

Publication source and artifacts must match the same pushed content. Verify actual deployment
status and the public URL after release. The main repository retains originals, translations,
theme, and builder; generated HTML and deployment archives are not committed there.

## 7. References

- [Gymnasium documentation](https://gymnasium.farama.org/): the reference for documentation grouping, navigation, and reading layout; its branding and assets are not copied.
- [MkDocs configuration](https://www.mkdocs.org/user-guide/configuration/): the optional documentation builder.
- [Python-Markdown TOC](https://python-markdown.github.io/extensions/toc/): sections and stable anchors.
