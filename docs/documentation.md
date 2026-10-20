# 双语文档站：构建与发布

公开网站：[GymTS Documentation](https://gymts-docs.zrr9392.chatgpt.site/)，可直接访问
[中文](https://gymts-docs.zrr9392.chatgpt.site/zh/)与
[English](https://gymts-docs.zrr9392.chatgpt.site/en/)。网站提供对应页面的语言切换、浏览器内搜索、
侧栏导航、页内目录、代码复制、深浅色模式和移动端导航。

## 1. 源码与发布边界

[site-pages.json](site-pages.json) 是显式发布清单。42 个页面分别提供中文与英文，共 84 个内容页面。
中文从仓库原文读取；英文由 `docs/i18n/en/<原仓库路径>` 提供完整翻译，首页分别位于
`docs/site/zh/index.md` 和 `docs/site/en/index.md`。译文保留原代码、API 标识、版本和评价边界；
正式合同的中文原文是规范来源，英文是对应翻译。

译文中的相对链接按清单的原源文件目录解析，而非翻译文件所在目录。这样可以指向同一份代码和示例，
无需复制数据或运行产物。站点生成器将已选页面映射到当前语言，其他公开源码指向 GitHub。
英文标题在构建时保留中文原章节 ID，因此跨语言和历史章节链接可继续定位。

只发布清单中的内容、两份明确列出的文本资产及 `docs/theme/` 的本站主题资源。
历史草案、私有附件审计、题目和答案、数据、权重、SQLite/CAS、原始日志及 `output/` 不进入网站。
站点不加载远程脚本、统计服务、字体或样式；搜索索引由公开页面生成，查询词在浏览器内处理。

## 2. 无依赖源码检查

```bash
python3 -B scripts/docs.py check
```

`check` 只依赖 Python 标准库，检查双语清单、翻译是否齐全、代码围栏及源链接本地目标。
它不请求网络，不把外部 URL 可达性或远端部署成功当作检查事实。
`prepare/build` 继续核对译文标题结构并生成稳定锚点；最终 HTML 的链接与锚点也会逐项检查。

## 3. 构建与本地预览

文档依赖独立于核心运行环境：

```bash
python3 -m venv /tmp/gymts-docs-venv
/tmp/gymts-docs-venv/bin/python -m pip install -r requirements-docs.txt
/tmp/gymts-docs-venv/bin/python -B scripts/docs.py build \
  --work /tmp/gymts-docs-build --site-dir /tmp/gymts-docs-site
python3 -m http.server 8000 --bind 127.0.0.1 --directory /tmp/gymts-docs-site
```

浏览 `http://127.0.0.1:8000/zh/` 或 `/en/`，按 Ctrl-C 停止预览。网站根入口按浏览器语言或上次
选择进入对应语言；不运行 JavaScript 时仍提供两个语言入口。默认公开 canonical URL 来自本站部署；
本地 HTTP 地址仅用于预览。

安装完依赖后，构建不请求网络。离线安装可先准备 wheelhouse，再使用
`pip install --no-index --find-links /path/to/wheelhouse -r requirements-docs.txt`。
工具不会运行实验、训练模型、创建 Git 分支或部署服务。

输出目录必须是独立目录，不能放在源码检出内部；不要指定 `/tmp`、源码、数据或模型目录本身。
脚本只清理带自身标记的 staging 文件，拒绝递归删除未知目录。站点输出必须为空或尚不存在，重建可选择新目录。

## 4. 准备输入与更换托管平台

仅准备两种语言的输入和配置：

```bash
/tmp/gymts-docs-venv/bin/python -B scripts/docs.py prepare --work /tmp/gymts-docs-input
```

结果包含 `mkdocs.zh.yml`、`mkdocs.en.yml` 和 `source/zh/`、`source/en/`。
正式构建使用 `build`，它还会生成语言入口、两份本地搜索索引、404、sitemap 和 robots.txt。

更换域名或部署到 GitHub Pages 子目录时指定完整站点前缀：

```bash
/tmp/gymts-docs-venv/bin/python -B scripts/docs.py build \
  --work /tmp/gymts-docs-rehost --site-dir /tmp/gymts-docs-rehost-site \
  --site-url https://example.org/GymTS/
```

页面、资源和语言切换均使用相对链接；`--site-url` 用于 canonical、alternate、sitemap 和 404 返回入口。
将完整输出目录交给静态 HTTP 托管即可，部署不需要 GymTS 运行库、模型服务或私有数据。

## 5. 更新翻译与主题

修改中文原文后，同步相应英文镜像。保持标题级别、顺序、章节内容、API 和可执行代码一致；
不要以英文概览代替完整指南，也不要在缺少译文时静默回退到中文。
清单中的 `translated_source_sha256` 固定本轮翻译依据；同步翻译后用 `sha256sum 原源文件` 更新该值。
源文发生变化而未同步时，检查会失败。新页面须同时登记两种语言的标题、分组和来源。

[主题](theme/main.html)使用 MkDocs 模板与本地 CSS / JavaScript；发布前检查桌面和手机布局，
尤其是菜单键盘焦点、搜索、深浅色、同页语言切换与代码复制。新增脚本或样式必须本地提供并保留许可。
框架核心与项目适配包不依赖文档主题或部署平台。

## 6. CI 与线上发布

[文档工作流](../.github/workflows/docs.yml)在 push/PR 上检查并严格构建双语站点，提供可下载 artifact。
该工作流只有仓库读取权限；它不自动调用 Sites，也不声称已经启用 GitHub Pages。

当前公开网站由 Sites 托管，站点身份在 [.openai/hosting.json](../.openai/hosting.json) 中登记。
更新时复用该项目 ID，重新构建，在独立发布工作区同步经过检查的静态目录，再保存并部署对应版本。
短期发布凭证只通过工具会话传入，不写入仓库或构建输出；不要把主仓库 remote 改成托管平台的源码地址。

网站发布源码与构建制品须对应同一份已经推送的内容，发布后核对实际部署状态及公开 URL。
主仓库保留文档原文、译文、主题与构建工具，生成的 HTML 和部署归档不提交到主仓库。

## 7. 参考

- [Gymnasium 文档](https://gymnasium.farama.org/)：本次参考其文档分组、侧栏和阅读布局，不复制其品牌和资源。
- [MkDocs 配置](https://www.mkdocs.org/user-guide/configuration/)：可选文档构建器。
- [Python-Markdown TOC](https://python-markdown.github.io/extensions/toc/)：章节与稳定锚点。
