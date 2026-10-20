# 文档检查与本地网站

GymTS 的文档以仓库内 Markdown 为唯一文本来源。README、使用/接口/适配开发指南、架构说明、
社区文件和各独立适配包 README 可直接在仓库阅读；本地网站从这些源文件生成，不另维护一份改写稿。
工具只构建本地静态文件，不发布网站、不创建 Git 分支、不上传实验数据。

## 无依赖检查

从仓库根目录执行：

```bash
python3 -B scripts/docs.py check
```

该命令只使用 Python 标准库，读取 [site-pages.json](site-pages.json) 中的显式清单，检查来源、目标路径、
代码围栏及源 Markdown/HTML 链接的本地目标。它不会请求外网，也不会把 URL 可达性、供应商文档或当前分支
是否已推送到 GitHub 当作已验证事实。站点渲染和最终页面锚点由下面的严格构建继续检查。

只检查清单中的当前公开文档，不遍历全部历史设计；报告和草案的链接可指向仓库源文件，但不因此自动进入站点。
相对链接越出仓库、指向本机绝对路径或缺少目标时检查失败。链接到 `output/`、`.git/` 等本地材料也会被拒绝。

## 安装独立文档工具

核心运行不依赖 MkDocs。推荐给文档另建环境：

```bash
python3 -m venv /tmp/gymts-docs-venv
/tmp/gymts-docs-venv/bin/python -m pip install -r requirements-docs.txt
```

当前固定 MkDocs 1.6.1，传递依赖由 pip 解析。离线机器须提前准备全部文档依赖的 wheelhouse，再用
`pip install --no-index --find-links /path/to/wheelhouse -r requirements-docs.txt` 安装；
成功安装之后的 prepare/build 不需要访问网络。

## 构建和预览

```bash
/tmp/gymts-docs-venv/bin/python -B scripts/docs.py build \
  --work /tmp/gymts-docs-build --site-dir /tmp/gymts-docs-site

python3 -m http.server 8000 --bind 127.0.0.1 --directory /tmp/gymts-docs-site
```

在浏览器访问 `http://127.0.0.1:8000/`。停止预览服务使用 Ctrl-C。
工作目录和站点目录用专门的新目录，不要指定源码、数据、模型目录或 `/tmp` 本身。
脚本只接受它自己建立或带自身标记的 staging 目录，不递归删除未知目录。
站点输出必须为空或尚不存在；重新构建用新的空目录，避免误清理用户文件和旧页面残留。

`build` 先执行同样的源检查，再准备临时输入、调用 `mkdocs build --strict`，并核对最终 HTML 中
本地链接/锚点和资源。构建若发现警告、缺失链接或需要 CDN 才能运行的脚本/样式会失败。
默认目录是 `/tmp/gymts-docs-build` 和其中的 `site`，可用上述选项覆盖。
终端打印 JSON 摘要，不运行模型、单元测试或框架发行检查。

如只希望查看重写后的站点输入和配置，不渲染 HTML：

```bash
python3 -B scripts/docs.py prepare --work /tmp/gymts-docs-prepare
# 安装文档依赖后，可手动严格构建该准备结果。
/tmp/gymts-docs-venv/bin/python -m mkdocs build --strict \
  --config-file /tmp/gymts-docs-prepare/mkdocs.generated.yml
```

不要将 MkDocs 的 `docs_dir` 改为整个仓库，也不要直接把全部 `docs/` 交给网站发布。
根 [mkdocs.yml](../mkdocs.yml) 提供渲染配置，脚本生成的配置补充 staging 路径和清单导航。

## 链接与发布范围

清单逐项指定源文件、站点路径、导航分组和标题，目前包括中文/英文 README、完整项目说明、用户与 API 指南、
正式合同、核心架构、环境和数据目录、开发/维护/协作流程、11 个独立适配包 README、项目工作流、
状态/路线图/变更/许可/引用与第三方来源。`CITATION.cff` 与 MIT `LICENSE` 原文作为
明确列出的下载资产复制，许可链接在本地站点中直接指向该文本。

生成时按原 Markdown 的所在目录解析相对路径：

- 目标也在清单中：转换为站点内相对链接，保留查询与章节锚点。
- 目标是其他仓库文件：转换为 `https://github.com/Jurmean/GymTS/blob/main/...`。
- 目标是其他仓库目录：转换为对应的 `tree/main/...`。
- 已有外部 HTTPS 等链接：保持不变，不抓取或复制外部媒体。

未选中的历史 PDF、设计草案、验收日志、源码、私有数据和本地输出不复制进站点。
GitHub 回退链接以清单声明的分支为准，当前工作树尚未推送的文件在云端可能不存在；本地检查不会假装已上线。
站点使用 MkDocs 内置本地资源，关闭默认 CDN 代码高亮，不加载统计脚本；Mermaid 围栏作为可读源码呈现，
不从 CDN 引入绘图库。构建后的 HTML 可离线阅读，本地搜索和导航建议通过上述 HTTP 预览访问。

## 维护清单和 CI

新增页面先编辑源 Markdown，再在 `docs/site-pages.json` 选择是否纳入当前站点；不能为消除链接错误而
把整个目录、实验数据或历史文件自动加入。修改目标路径时由清单映射重写互链，不需要修改仓库阅读路径。
`scripts/docs.py` 当前支持常用行内链接、引用式定义和 HTML `href/src`；复杂自定义 Markdown/插件应扩展检查并实际构建验证。

[文档工作流](../.github/workflows/docs.yml) 对 push/PR 检查、构建并保存预览 artifact，只有仓库内容读取权限，
没有 Pages 部署、仓库写入或模型/服务调用步骤。工作流文件的存在不证明某次远端运行已成功。
文档修改不需要训练、重新采集 benchmark 或运行重型原生实验。

构建配置参考 [MkDocs 官方说明](https://www.mkdocs.org/user-guide/configuration/)，
Unicode 章节使用 [Python-Markdown 的 TOC 扩展](https://python-markdown.github.io/extensions/toc/)。
