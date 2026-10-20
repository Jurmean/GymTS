# 翻译维护 / Translation maintenance

英文全文位于 `en/<原仓库路径>`，发布对应关系由
[site-pages.json](../site-pages.json) 显式指定；网站首页另有独立中英文原文。

译文的相对链接保持原源文档的路径语义，由构建器按清单中的 `source` 解析，再映射到
当前语言页面或 GitHub 原源码。请通过生成的网站阅读这些链接，不要复制代码或数据到翻译目录。

中文源变化后，同步英文全文与清单中的 `translated_source_sha256`。运行
`python -B scripts/docs.py check` 和安装文档依赖后的严格构建，防止缺译、旧译或错误锚点。
API 标识、可执行代码、版本、数值、评价与许可边界应与源文一致。

Full English translations live under `en/<original repository path>`. The manifest explicitly pairs
each page. Relative links retain the original document's path semantics; the builder resolves and
maps them to the active language or original GitHub source. Read them through the generated site;
do not duplicate code or datasets in the translation directory.

After source changes, synchronize the full translation and its `translated_source_sha256` entry.
Run the dependency-free source check and strict documentation build. Preserve API identifiers,
executable code, versions, numeric facts, evaluation boundaries, and license scope.
