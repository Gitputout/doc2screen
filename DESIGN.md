# doc2screen 设计文档

> 状态：Draft v0.2 · 2026-11-06
> 实现状态：v0.2 已实现 PDF/DOCX/ODT/EPUB/HTML/Markdown/RST/LaTeX/TXT → 自包含 HTML、EPUB3、Chrome PDF；已通过 30 道 Linux PDF 与 smoke test 验证。
> 定位：开源 CLI + Claude Code Skill。把不同格式的文档转成「以阅读为中心」的语义内容，再按目标屏幕输出 HTML / EPUB / PDF。
> 不是又一个 PDF 解析器，而是编排层、阅读层、打包层和质量门禁。

---

## 0. 摘要

**一份语义源，多种屏幕，多种交付。**

```
任意文档 → 提取 → 统一文档模型 → 清洗/复核 → 响应式阅读渲染 → HTML / EPUB / PDF → 自动验证
```

现有项目各强一段，但没人把最后一公里串起来：

| 项目 | 强项 | 缺什么 |
|---|---|---|
| MinerU | 中文/复杂版面、OCR、表格、公式、HTML/Markdown | 阅读体验、EPUB/PDF 打包、内容清理、屏幕 profile |
| Docling | DoclingDocument、阅读顺序、表格、HTML/Markdown | 同上；偏 GenAI 场景 |
| Marker | 版面 + OCR + 表格/公式，HTML/JSON/Markdown | 同上；GPU 依赖更重 |
| PDF-Reflow | 固定版式 PDF → 响应式单栏 HTML / 重排 PDF | 只吃 PDF、很新、无 EPUB、无清理、无 profile |
| k2pdfopt | 小屏/电纸书 PDF 重排 | 输出 PDF，不是语义 HTML |
| pdf2htmlEX | 高保真 PDF→HTML | 绝对定位，不可重排 |
| Pandoc / Calibre | 单一源多输出、EPUB 打包 | 上游需要干净语义内容 |

**差异化：** 多格式统一模型 + 屏幕 profile + 内容清理 + 图片策略 + 自动验证 + 许可证边界清晰。

**非目标：**

- 不做 OCR 精度竞赛；扫描件交给可选 MinerU/Tesseract adapter；
- 不做在线 SaaS / 账号体系；
- 不做 PDF 像素级复刻（保真只作为可选 fallback）；
- 不做完整编辑器；
- 不承诺所有格式；用支持矩阵和降级策略替代。

---

## 1. 用户与场景

| 场景 | 输入 | 输出 | 关键需求 |
|---|---|---|---|
| 手机读论文/讲义 | PDF、DOCX | 自包含 HTML | 单栏、字号、图片可放大 |
| 电纸书阅读 | EPUB、PDF、DOCX | EPUB3 | 原生目录/书签、图片、代码块可读 |
| 分享/打印 | 任意 | PDF（A4/A5/手机尺寸） | 分页、页码、书签、图片完整 |
| 技术文档归档 | HTML、MD、PDF | HTML + EPUB + PDF | 一份源，多端一致 |
| 内容整理 | 带广告/推广的 PDF | 干净 HTML | 删除/标记无关内容，保留出处 |

---

## 2. 总体架构

```
┌────────────┐     ┌────────────┐     ┌────────────┐     ┌────────────┐
│   Input    │────▶│   Ingest   │────▶│  DocModel  │────▶│   Curate   │
│ pdf/docx/  │     │ adapters   │     │  (JSON)    │     │ 自动 + 复核 │
│ epub/html/ │     └────────────┘     └────────────┘     └─────┬──────┘
│ md/txt     │                                                   │
└────────────┘                                                   ▼
        ┌────────────────────────────────────────────────────────┘
        ▼
┌────────────┐     ┌────────────┐     ┌────────────┐
│   Render   │────▶│  Package   │────▶│   Verify   │
│ responsive │     │ HTML/EPUB/ │     │ + report   │
│   HTML     │     │    PDF     │     │            │
└────────────┘     └────────────┘     └────────────┘
```

### 设计原则

1. **单一语义源**：所有输出从 `DocModel` 渲染。
2. **流式优先，保真可选**：默认重排；pdf2htmlEX 式保真只作 fallback。
3. **确定性核心 + 可选重依赖**：核心不依赖 GPU/大模型。
4. **可追溯**：PDF 提取块带来源页/bbox；裁剪删除有审计记录。
5. **不自动误删**：推广/广告不自动删除；由用户通过 `--drop-text`/`--drop-asset` 显式处理，并在 `build.json` 中审计。
6. **许可证边界清晰**：v0.2 为 AGPL-3.0（因 PyMuPDF）；未来切换 pypdfium2 后再考虑宽松许可证。

---

## 3. 实现流程

### Step 0：检查输入

```bash
doc2screen inspect input.pdf
```

输出 `work/inspect.json`：页数、页面尺寸、是否扫描件、文本层健康度（字符数/乱码/康熙部首/替换字符）、图片数量、印刷目录页 `tocPages`、`ocrNeeded`、分栏检测、建议 extractor。

**门槛：** 文本层为空或严重损坏 → `--ocr auto`（OCRmyPDF/Tesseract）或 MinerU adapter，不硬提取。

### Step 0.5：预检预览（输出前确认）

```bash
doc2screen preview input.pdf --out preview/ \
  --profiles phone-notes,phone-16x9.5 --formats html,pdf
```

- 只抽取少量代表页/块，不跑完整文档；
- 输出候选 profile 的 HTML/PDF 样例和 `preview.json`；
- `preview.json` 包含 `tocPages`、`scannedLikePages`、`ocrNeeded`、warnings、样例页/块、输出路径；
- agent 把样例交给用户确认内容、排版、profile、OCR 语言和删除项，确认后才跑完整 `build`；
- 这是控制 token/时间成本和避免错误 profile 的前置门禁。

完整的转换风险清单见 `docs/conversion-risks.md`。

### Step 1：提取

```bash
doc2screen extract input.pdf --out work/
```

```
work/
  doc.json          # DocModel，warnings[] 记录提取警告
  raw.html          # 可选：中间 HTML
  assets/           # 图片
```

| 输入 | 默认 extractor | 备选 |
|---|---|---|
| PDF（文本层） | PyMuPDF（本地）/ pypdfium2（开源默认） | MinerU（复杂版面） |
| PDF（扫描件） | OCRmyPDF + Tesseract（可选依赖） | MinerU / PaddleOCR |
| DOCX / ODT | Pandoc | mammoth |
| EPUB | Pandoc | 直接解析 XHTML |
| HTML | Pandoc / 原文清洗 | readability/trafilatura |
| Markdown | Pandoc | 内置 parser |
| TXT | 段落器 | — |
| PPTX | 第一版不支持 | LibreOffice / python-pptx |

**PDF 提取要点：**

- block/line 读取，保留字号、粗体、bbox；
- 标题 = 字号 + 粗体 + 编号；
- 代码 = 等宽字体 + 缩进；
- 列表 = 缩进层级 / bullet；
- 图片 = 原始字节 + bbox + 哈希去重；图注取上下方最近且以「图/Figure/表/Table」开头的文本；
- 阅读顺序：单栏 y/x 排序；多栏用投影空白列检测；
- 页眉页脚：顶部/底部 8% 带内、≥30% 页面重复 → 删除；
- 印刷目录页：点线 + 页码行检测，整页跳过并在 `warnings`/`meta.tocPages` 记录；
- OCR 模式：跳过覆盖整页的背景图，避免正文夹带扫描页图片。

### Step 2：规范化

- 合并被拆开的段落/代码行；
- 统一标点、空白、全半角；
- 修复康熙部首（`⽤`→用）、CJK 兼容字、软连字符、乱码；
- 标题层级归一；
- 每块稳定 id + `source.page/bbox`；
- 图片去重、caption 关联；
- 输出 `doc.json` + `warnings[]`。

### Step 3：清洗与复核

自动（安全）：重复页眉/页脚/页码、空块、重复图片、过小装饰图。重复段落去重和水印识别尚未实现。

需复核：扫码/关注/公众号/训练营/广告/优惠/加群、二维码、外链密集块、封面/目录/版权页。当前 v0.2 不自动标记或删除这些内容。

裁剪：使用 `build --start-at/--end-at/--drop-text/--drop-asset` 显式指定；被删除的 block id 与原因记录在 `out/build.json` 的 `trim.removedBlocks`，便于审计。

### Step 4：渲染

```bash
doc2screen render work/doc.json --profile phone-notes --out out/book.html
```

语义 HTML、目录、进度、字号、深浅色、代码复制、图片查看器；图片按宽高比选择 fit/rot/strip；自包含或 assets 目录；无障碍 lang/alt/标题层级。

### Step 5：打包

```bash
doc2screen build work/doc.json --profile phone-notes \
  --out out/  # 默认只输出 PDF
```

```
out/
  book.html
  book.pdf
  build.json
```

### Step 6：验证

```bash
doc2screen verify out/ --source work/doc.json
```

检查项见 §11；失败返回非零退出码，生成 `out/report.md`。

### Step 7：报告

输入/输出路径、页数/图片数/删除项、降级警告（扫描件/OCR/缺字/公式表格转图）、建议。

---

## 4. DocModel

### 4.1 设计理由

- 同一份内容输出 HTML/EPUB/PDF/Markdown；
- 清洗能定位到块和来源页；
- 验证能对比源文档覆盖率；
- 不同 extractor 收敛到同一接口。

### 4.2 Schema（节选）

```json
{
  "schema": "doc2screen/1",
  "meta": {"title": "...", "author": "", "language": "zh-CN", "source": "input.pdf",
           "sourceHash": "sha256:...", "createdAt": "..."},
  "profile": {"id": "phone-notes", "cssWidth": 390, "cssHeight": 552,
              "baseFont": 17, "margin": 16},
  "blocks": [
    {"id": "b0001", "type": "heading", "level": 1, "text": "第一章",
     "html": "<h1>第一章</h1>", "source": {"page": 1, "bbox": [40, 80, 560, 110]}},
    {"id": "b0002", "type": "paragraph", "text": "……", "html": "<p>……</p>",
     "source": {"page": 1, "bbox": [38, 120, 560, 150]}},
    {"id": "b0003", "type": "figure", "asset": "a0001", "alt": "示例",
     "caption": "图 1 · 示例", "role": "screenshot",
     "width": 1604, "height": 318, "aspect": 5.04, "layout": "strip",
     "source": {"page": 2, "bbox": [38, 259, 557, 362]}}
  ],
  "assets": {"a0001": {"path": "assets/a0001.png", "mediaType": "image/png",
                        "width": 1604, "height": 318, "sha256": "..."}},
  "warnings": [{"code": "text-layer-radicals", "message": "...", "count": 113}]
}
```

### 4.3 Block 类型

`heading | paragraph | list | code | table | figure | quote | callout | divider | pagebreak`

- `list`：`ordered`、`items[]`；
- `code`：`language`、`text`；
- `table`：优先 `html`；
- `figure`：`role`（photo/diagram/screenshot/scan）、`layout`（fit/rot/strip/panel）。

---

## 5. 阅读顺序与分栏

- 单栏：按 y、再按 x。
- 多栏：文本块 x 投影 → 找宽度 > 页宽 5%、覆盖高度 > 60% 的空白谷 → 切列 → 列内 y 排序；跨栏块单独处理。
- 不确定时记录 `warnings`，建议 MinerU/Docling 重试，不强行猜。
- 表格/公式：能保留 HTML 就保留；不能则转图片并附 caption，不做低质量 OCR 伪造文本。

---

## 6. 清洗规则

### 6.1 自动（安全）

| 规则 | 判定 | 动作 |
|---|---|---|
| 重复页眉/页脚 | 顶部/底部 8% 带内，≥30% 页面重复 | 删除，记入 warnings |
| 页码 | 纯数字/罗马数字/「第 x 页」 | 删除，记入 warnings |
| 空块 | 无文本、无图片 | 删除 |
| 重复图片 | sha256 相同 | 保留首次 |
| 装饰图 | 宽或高 < 48px | 跳过，不进入 DocModel |

### 6.2 推广内容（需复核）

| 规则 | 例子 | v0.2 行为 |
|---|---|---|
| 推广文本 | 扫码、关注、公众号、训练营、广告、优惠、加群 | 不自动删除；可用 `--drop-text` |
| 二维码 | 方形、高对比、黑白块 | 作为图片保留；可用 `--drop-asset` |
| 外链密集 | 短段落含 ≥3 个 URL | 保留，人工复核 |
| 封面/目录/版权页 | 首页、重复标题 | 保留，可用 `--start-at/--end-at` 裁剪 |

**原则：宁可保留，不可误删。** v0.2 不自动删除推广块；显式删除会写入 `build.json` 的 `trim.removedBlocks`。

---

## 7. 屏幕 profile 与图片策略

### 7.1 Profiles

```json
{
  "phone-notes":  {"label": "0.706 Huawei Notes-like", "cssWidth": 390, "cssHeight": 552, "baseFont": 17, "margin": 16},
  "phone-16x9.5": {"label": "6.39in 16:9.5", "cssWidth": 390, "cssHeight": 657, "baseFont": 17, "margin": 16},
  "phone-16x9":   {"label": "6.x in 16:9",   "cssWidth": 390, "cssHeight": 693, "baseFont": 17, "margin": 16},
  "phone-19.5x9": {"label": "6.x in 19.5:9", "cssWidth": 390, "cssHeight": 845, "baseFont": 17, "margin": 16},
  "kindle":       {"label": "Kindle 6in",    "cssWidth": 600, "cssHeight": 800, "baseFont": 18, "margin": 24},
  "a5":           {"label": "A5",            "cssWidth": 559, "cssHeight": 794, "baseFont": 11, "margin": 28},
  "a4":           {"label": "A4",            "cssWidth": 794, "cssHeight": 1123,"baseFont": 11, "margin": 36}
}
```

设备比例与页面比例不是一回事：6.39″ 16:9.5 屏幕约 82.9×139.6 mm，而 390×552 的 0.706 页面按宽度显示约 82.9×117.4 mm，刻意留出上下空间给工具栏与页边距。完整公式、阅读字号/边距启发式和示例见 `docs/screen-profiles.md`；`scripts/profile_helper.py` 可由英寸和比例生成 profile 建议。

- HTML：profile 影响 `--reading-width`、`--fs`、页边距；布局流式。
- PDF：profile 作为 `@page` 尺寸（CSS px → pt ×0.75）。
- 自定义：`--width 412 --height 733`。

### 7.2 图片模式

| 宽高比 | HTML | EPUB/PDF | 说明 |
|---|---|---|---|
| < 1.45 | 页宽 | 页宽 | 竖图/普通图 |
| 1.45–4.0 | 可旋转 90° / 页宽 | 页宽或旋转 | 中等宽图 |
| ≥ 4.0 | 横向滑动 + 全屏 | 按空白列切面板 | 超宽终端/表格 |
| 扫描页 | 页宽 + 全屏 | 整页图 | 不做 OCR 伪造 |

切面板（借鉴 k2pdfopt 列检测思路，独立实现）：目标宽度 ≈ 正文宽 ×1.6；在目标位置附近找全背景色空白列；切点加 16px 重叠；每个面板保留原分辨率；EPUB/PDF 标注「（1/3）」。

---

## 8. 输出格式

### 8.1 自包含 HTML

- CSS/JS/图片全部内联；离线；
- 目录、进度、字号、深浅色、代码复制、图片查看器；
- 可选 assets 目录模式。

### 8.2 EPUB3

```
mimetype
META-INF/container.xml
OEBPS/content.opf, nav.xhtml, css/reader.css, text/chapter-*.xhtml, images/...
```

按 h1/h2 拆章；无 JS；CSS 简化；nav + OPF spine；宽图切面板；代码块 `pre-wrap`；epubcheck（可选）。

### 8.3 PDF

- 默认 Chrome headless（用户选择）；
- 打印 CSS：浅色、隐藏 UI、图片页宽、代码换行、`break-inside: avoid`；
- 分页：章节新页、标题不孤行、图片不跨页、页脚页码；
- 后处理：PyMuPDF（可选）写书签；否则仅元数据。

### 8.4 Markdown（可选）

从 DocModel 序列化干净 Markdown，便于二次编辑。

---

## 9. 技术选型

| 层 | 主选 | 理由 | 备选 | 许可证 |
|---|---|---|---|---|
| PDF 提取 | **PyMuPDF（本地）/ pypdfium2（开源默认）** | 质量/许可证平衡 | pdfplumber | PyMuPDF AGPL；pypdfium2 Apache/BSD |
| 扫描/复杂版面 | **MinerU（可选 CLI）** | 中文/OCR/表格/公式 | Tesseract + Docling | 以 LICENSE.md 为准 |
| DOCX/ODT/EPUB/HTML/MD | **Pandoc 外部 CLI** | 语义 HTML、图片、脚注/表格 | mammoth | GPL-2+（只调用） |
| PPTX | 第一版不支持 | — | LibreOffice | MPL-2.0 |
| 中间模型 | **自定义 DocModel JSON** | 解耦、可审计、多输出 | DoclingDocument | 本项目 |
| HTML 渲染 | **手写模板 + CSS/JS** | 完全控制阅读体验 | Pandoc template | 本项目 |
| EPUB | **stdlib zipfile** | 无依赖 | ebooklib | 本项目 |
| PDF 导出 | **Chrome headless**（用户选择） | CSS 支持最好、已安装 | WeasyPrint | Chrome 专有 |
| HTML 解析 | **lxml** | 已安装、快 | bs4 | BSD |
| 浏览器验证 | **puppeteer-core** | 真实视口/溢出检查 | Playwright | Apache-2.0 |

**依赖边界：**

```
AGPL-3.0 核心（v0.2；因 PyMuPDF）
├── lxml / pypdfium2 / WeasyPrint(可选)     import
├── Pandoc / Chrome                         subprocess，不打包
├── PyMuPDF                                 optional/local（AGPL）
└── MinerU                                  optional adapter（许可证待确认）
```

**ADR：**

- ADR-001 语义优先，不做保真克隆。
- ADR-002 本地先用 PyMuPDF，开源默认换 pypdfium2；backend 接口隔离。
- ADR-003 非 PDF 输入统一走 Pandoc。
- ADR-004 PDF 导出用 Chrome（用户选择）；WeasyPrint 后续可选。
- ADR-005 DocModel 用 JSON。
- ADR-006 核心不调用 LLM；清洗由 agent 复核。
- ADR-007 EPUB 手写打包。
- ADR-008 不做“万能格式”，支持矩阵 + 降级。

**被否掉：** 以 Docling/MinerU 为核心（重/慢/许可证复杂）；pdf2htmlEX 默认（保版式）；Calibre 重排（效果一般）；直接拼 GitHub 代码（版权/维护风险）。

---

## 10. 版权与合规

### 10.1 Clean-room

1. 只读文档/README/公开行为；不复制源码/注释/命名；
2. 先写行为规格，再独立实现；
3. 提交前做相似性自查；
4. `references/research.md` 记录“借鉴了谁的什么思路”；
5. 不复制 README 文字、截图、示例 PDF、测试数据、模型权重；
6. 复用 MIT/Apache 代码才允许，并保留版权/NOTICE。

### 10.2 许可证矩阵

| 依赖 | 许可证 | 用法 | 义务 |
|---|---|---|---|
| lxml | BSD | import | 保留版权 |
| pypdfium2 | Apache/BSD | import（开源默认） | 保留版权 |
| PyMuPDF | AGPL-3.0/商业 | optional/local | 分发时 AGPL |
| Pandoc | GPL-2+ | subprocess | 不打包 |
| Chrome | 专有 | subprocess | 不打包，用户自装 |
| MinerU | NOASSERTION | optional subprocess | 不打包；商业先确认 |
| Tesseract | Apache-2.0 | optional | 保留声明 |
| puppeteer-core | Apache-2.0 | devDependency | 保留声明 |

> 以各项目最新 LICENSE 为准；发布前重新核对。

### 10.3 内容版权

- 只转换用户有权使用的文档；输出继承原文档版权；
- 仓库不放受版权保护的 PDF/转换结果/截图；
- 测试用公共领域或自造样例；
- 示例输出只放自造内容。

### 10.4 商标/专利/登记

- 项目名先查重；不暗示 MinerU/Docling 官方背书；
- 专利若想申请，公开前申请；否则丧失新颖性（美国 1 年宽限）；
- 软著/商标登记可选，不是开源前提；
- 本文不构成法律意见。

### 10.5 发布前检查

- [x] LICENSE（AGPL-3.0）
- [ ] README（中英双语、支持矩阵、限制、隐私）
- [ ] THIRD_PARTY.md / NOTICE
- [ ] references/research.md
- [ ] 无 GPL/AGPL 源码复制
- [ ] 无受版权保护的样例/截图/模型
- [ ] 依赖许可证核对
- [ ] CI：lint + 单测 + 端到端 smoke
- [ ] 安全：不执行用户 HTML/JS；路径穿越/zip 炸弹防护
- [ ] 隐私：本地处理、无遥测
- [ ] 版本号/CHANGELOG

---

## 11. 验证与质量门禁

### HTML

- `scrollWidth == clientWidth`（390/412/360，15/21px 字号）；
- 所有图片 `naturalWidth > 0`；
- 图片容器高度 > 0；旋转/横滑切换后仍 > 0；
- TOC 链接可定位；
- 代码块可横向滚动，不撑破页面；
- 深/浅色、字号不溢出；
- 无外部请求（自包含时）；
- 无 JS 错误。

### PDF

- 页面尺寸 == profile；
- 无空白页；
- 每张图片显示宽高比 == 原始比例；
- 书签数量 == 章节/题目数（如启用）；
- 文本可搜索；字体嵌入；
- 页脚页码连续。

### EPUB

- zip：`mimetype` 第一项且不压缩；
- `container.xml`/`content.opf`/`nav.xhtml` 合法；
- spine/item 资源存在；
- nav 与章节一致；
- 无 JS；epubcheck（可选）。

### 文本覆盖率

源文本 vs 输出字符数 < 90% 报警；列出丢失页/块；OCR 页单独标记。

---

## 12. 路线图

**Phase 1（MVP）**：inspect、PDF 提取（PyMuPDF 本地）、Pandoc（DOCX/EPUB/HTML/MD/TXT）、DocModel、HTML 渲染、profile、Chrome PDF、基础 verify。

**Phase 2（v0.2 已完成基础版）**：EPUB3、自动校验、CI、OCR MVP、预检 preview 已落地；图片切面板、交互式 curation、MinerU adapter 仍待做。

**Phase 3**：pypdfium2 默认后端、MinerU adapter、PyMuPDF 可选、公式/表格增强。

---

## 13. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 提取质量不足 | 标题/代码/图片不准 | 可选后端；测试量化 |
| 扫描件 OCR | 文本错/版面乱 | `--ocr auto` + preview + `doctor`；复杂版面建议 MinerU；不伪造 |
| 印刷目录混入正文 | 排版不自然 | 目录页检测并跳过；渲染器重建目录 |
| 全量转换成本高/参数错 | 时间与 token 浪费 | `preview` 抽样 + 用户确认后再 `build` |
| 多栏/复杂表格 | 阅读顺序错 | 投影检测 + 警告 + 可选 Docling |
| EPUB 兼容性 | 排版崩 | 简化 CSS、无 JS、epubcheck |
| 中文字体缺失 | 方框/替换 | 字体栈 + 警告 |
| 许可证漂移 | 合规风险 | 发布前核对；THIRD_PARTY |
| 范围膨胀 | 做不完 | 支持矩阵 + 非目标 + 分阶段 |
| 内容误删 | 用户损失 | 不自动删除；显式参数 + `build.json` 审计 |

---

## 14. 待定

1. 默认 PDF 后端：Chrome（已选）→ WeasyPrint 后续；
2. 第一版不做 PPTX（已定）；
3. 是否提供 `--fidelity`；
4. 是否发布 PyPI；
5. 是否做 Claude Code 插件市场分发。

---

## 附录 A：CLI

```bash
doc2screen inspect input.pdf

doc2screen preview input.pdf --out preview/ \
  --profiles phone-notes,phone-16x9.5 --ocr auto

doc2screen build input.pdf --profile phone-notes \
  --out out/  # 默认只输出 PDF

doc2screen extract input.docx --out work/
doc2screen render work/doc.json --profile kindle --out out/book.html
doc2screen verify out/
```

## 附录 B：参考项目

- MinerU — https://github.com/opendatalab/MinerU
- Docling — https://github.com/docling-project/docling
- Marker — https://github.com/datalab-to/marker
- PDF-Reflow — https://github.com/omrsangx/PDF-Reflow
- k2pdfopt — https://www.willus.com/k2pdfopt/
- pdf2htmlEX — https://github.com/pdf2htmlEX/pdf2htmlEX
- Pandoc — https://github.com/jgm/pandoc
- Calibre — https://github.com/kovidgoyal/calibre
- WeasyPrint — https://github.com/Kozea/WeasyPrint
- pypdfium2 — https://github.com/pypdfium2-team/pypdfium2

> 仅思路参考/外部调用；本项目不复制其代码、文档文字、图片、测试数据或模型权重。
