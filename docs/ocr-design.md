# OCR + 表格识别能力（doc-parse）— 设计与落地

> 状态：**已定稿并落地**（分支 `feature/ocr-pdf`）。目标：让 doc-parse 能解析 **图片型 / 扫描型 PDF** 及内嵌
> 图片页，并在需要时重建结构化 Markdown 表格，同时**不破坏现有纯文本 PDF 的解析质量、不 OCR 好页**。

---

## 1. 背景

PDF 原先全走 `markitdown`(0.1.7) 的 pdfminer/pdfplumber 后端——**只读 PDF 自带文字层，不做像素 OCR**：

- 有文字层的 PDF（如 DWUK 报告样例，48 页 / ~131KB）能出文，但页内**以图片呈现的内容（照片、扫描页、图表）无法转写**；
- 纯扫描 / 图片型 PDF（无文字层）整体返回空或近空；
- `.jpg/.jpeg/.png` 同样不转写。

> 样例实测：DWUK 报告 45/48 页文字充足，但存在低文字页（如第 47 页 text_len=0）；纯扫描 PDF 每页 text_len 全为 0。

---

## 2. 技术选型（最终）

| 决策点 | 结论 | 依据 |
|---|---|---|
| OCR 引擎 | **统一包 `rapidocr` + `onnxruntime` 引擎** | RapidOCR 官方 CPU 引擎即 ONNX Runtime；统一包是旧 `rapidocr_onnxruntime` 的继任 |
| 包选型 | TableStructureRec 依赖 `rapidocr` 及结构化输出 | 拆分包对不上，**无法驱动表格管线**；需 `rapidocr` 2.x 结构化输出 |
| PDF 光栅化 | **poppler-utils + pdf2image** | MuPDF/PyMuPDF 有 License 顾虑；poppler 的 `pdftoppm/pdftotext` 一并解决渲染 + 文字层探测 |
| 文字层页 | 直接抽文字层，**不做 OCR、不做 image 表格分类** | 表格在有文字层时已是文本 |
| 表格识别 | `table_cls` + `wired_table_rec` + `lineless_table_rec` | **仅用于无文字层页**；区分有线/无线重建 Markdown 表；**默认关闭** |
| 触发策略 | 文档级两档 + 逐页低文字判定 | 全文字页→markitdown 零改动；含缺文字页→仅缺文字页 OCR |
| 图片文件 | `.jpg/.jpeg/.png` 走同一 OCR 路径 | 一致性 |
| 模型离线 | 构建期下载并固化进镜像 | 生产离线运行 |
| 输出 | 纯 Markdown 文本（`/parse` 返回结构不变） | JSON/坐标留二期 |

---

## 3. 总体架构

```
doc_parser.parse(filepath)
   │ 按扩展名路由
   ├── .pdf            → pdf_pipeline.parse_pdf
   ├── .jpg/.jpeg/.png → ocr 图片转写
   └── 其他            → markitdown / txt_parser（不变）

PDF 管线：pdfminer 逐页取原生文字量
   ├─ 所有页充足 ─►【档A】整体 markitdown（零改动，不做 OCR）
   └─ 存在缺文字页 ─►【档B】逐页拼接：
        文字页   ─► pdfminer 抽文字层（不 OCR / 不跑表格模型）
        缺文字页 ─► 渲染位图(poppler, 200dpi) → RapidOCR 识别一次
                     ├─ 输出正文段落
                     └─ 几何门控判定为“真数据网格”时，才按需跑
                        table_cls→(wired|lineless) 重建表格（可关）
```

### 档 A / 档 B
- **档 A（无缺文字页）**：整份走 markitdown，输出与现状一致。
- **档 B（存在缺文字页 / 纯扫描）**：逐页拼接。
  - 文字页：pdfminer 抽文字层。
  - 缺文字页：渲染 + RapidOCR；内容完整即可，表格重建可选。
- 触发：页原生文字 `< pdf_text_min_chars(=300)` 判为缺文字页。

### 缺文字页的处理（关键实现事实）
1. **一页只识别一次**：`RapidOCR(img)` 拿 `.boxes/.txts/.scores`；正文文本与（可选的）表格重建**共用同一次识别结果**，不重复 OCR。
2. **廉价几何门控 `looks_like_table_layout`**：用识别行/列对齐判断是否**真数据网格**——
   - ≥3 行且每行 ≥3 个水平分离且不重叠的列块（数据网格），或 ≥5 行每行 ≥2 列（双列明细表）；
   - 封面 / 章节分隔 / 议程 / 纯散文页（单列）**不触发**表格模型，避免慢与冗余假表。
3. 命中才跑表格：`table_cls` 选有线/无线 → `wired_table_rec`/`lineless_table_rec` 重建 html → 转 Markdown 表，并有“真表”验收门控。
4. **表格模型按分类懒加载**：只加载命中分支（wired 或 lineless 之一），不两个都载。
5. 表格识别有一定不确定性（best-effort）；对 deck/幻灯片，OCR 正文本身已完整，故**默认不开表格**。

---

## 4. 模块

| 文件 | 说明 |
|---|---|
| `config.py` | 配置，均可环境变量覆盖（见 §5） |
| `ocr.py` | RapidOCR 懒加载单例；单次识别、正文/表格共用；几何门控 |
| `table_rec.py` | `table_cls`→wired/lineless（懒加载）；html→Markdown 表 + 验收门控 |
| `pdf_pipeline.py` | 档A/B 判定、逐页文字层抽取 / 渲染+OCR+表格、拼接 Markdown |
| `scripts/download_models.py` | 构建期离线固化 ONNX 模型 + manifest |
| 修改 | `doc_parser.py`、`requirements.txt`、`Dockerfile`、`docs/api.md` |
| 测试 | `tests/test_config.py`、`tests/test_table_rec.py`、`tests/test_pdf_pipeline.py`（17 项通过） |

### 依赖
- **apt**：`poppler-utils`（渲染/文字层）、`libgomp1`（onnxruntime）、`libgl1` `libglib2.0-0`（cv2）。
- **pip/uv**：`rapidocr` + `onnxruntime`（统一包）、`pdf2image`、`wired_table_rec` `lineless_table_rec` `table_cls`；保留 `markitdown[pdf,...]`。
- **版本**：按 PyPI 实际版本锁定（`requirements.txt` 已固定），避免上游迭代 API 漂移。

---

## 5. 配置（全部经环境变量）

| 环境变量 | 默认 | 含义 |
|---|---|---|
| `OCR_ENABLED` | `true` | OCR 总开关 |
| `OCR_MODE` | `auto` | `auto`(有缺文字页才 OCR) / `always` / `never` |
| `PDF_TEXT_MIN_CHARS` | `300` | 页原生文字低于此值判缺文字页 → OCR。实测：样例文字页最低 852、近空页 0–60，300 可干净切分 |
| `OCR_DPI` | `200` | 渲染分辨率（保持 200） |
| `TABLE_ENABLED` | `false` | 是否跑表格重建（慢，需结构时开 `true`） |
| `OCR_MODEL_DIR` | 各包默认 | ONNX 模型目录 |

---

## 6. 模型离线预置

- `rapidocr`/表格三包模型默认首次运行自动下载（modelscope）。生产要求离线：
  - `scripts/download_models.py`：构建期实例化各引擎（触发下载）→ 把 7 个 ONNX(~150MB) 拷贝到 `/app/models` 并写 `manifest.json`(sha256)；
  - 该步同时填充到 site-packages 各包 models 缓存，运行期离线可用。
- 7 个模型：rapidocr 3（det/cls/rec）+ `table_cls` 1 + `wired_table_rec` 1 + `lineless_table_rec` 2（detect/process）。

---

## 7. Docker

- base `python:3.12-slim`（daocloud 镜像），apt 源先切**清华镜像**（官方源国内 502）。
- 安装：`poppler-utils libgomp1 libgl1 libglib2.0-0`。
- 依赖：先 `pip install uv`，后 `uv pip install`（`UV_INDEX_URL`/`UV_SYSTEM_PYTHON` 指向清华源与系统 Python）。
- 构建期跑 `scripts/download_models.py /app/models` 固化模型。
- 本地无 poppler 时，`pdf_pipeline` 渲染 dev 回退 pypdfium2（BSD）；Docker 内始终走 poppler。

---

## 8. 已定决策 & 已知限制

### 已定
1. OCR：统一包 `rapidocr`(onnxruntime)，文字页不 OCR、`table_cls` 仅用于无文字层页。
2. 档B 文字页用 pdfminer 逐页抽文字层、整档拼 page break（保位置）；markitdown 保留为档A 快速路径与非 PDF 文档。
3. 缺文字阈值 `pdf_text_min_chars=300`；`OCR_MODE=always/never` 可覆盖自动判定。
4. 表格一期整页 `table_cls`→单一引擎（多表/旋转透视暂不做）。
5. 表格重建默认关闭（`TABLE_ENABLED=false`）；模型构建期离线固化；输出纯 Markdown。

### 已知限制 / 二期
- `table_cls` 只有 wired/wireless 两类、无“无表”类，靠几何门控 + 结构验收兜底；一页多表、旋转/透视需 `rapid-table-det`。
- 表格重建为 best-effort、存在轻微不确定性（同页可能只出正文未出表，或有正文/表格少量重复）。
- 有表格结构的纯文字 PDF 若触发档B，文字页为 pdfminer 平铺文本，会丢 markitdown 排版细节。
- 坐标结构化 JSON 输出留二期。
- 容器(linux)OCR 比本地(macOS)慢（onnxruntime/架构差异），纯 OCR 热跑约 ~9s/8 页扫描。

---

## 9. 验证（容器实测，纯扫描 PDF 8 页）

| 配置 | 首跑 | 热跑 |
|---|---|---|
| 表格开启 | ~21s | ~14s |
| 纯 OCR（`TABLE_ENABLED=false`，默认） | ~10.7s | **~8.8s** |

- DWUK 报告（文字型）走档A，输出与 markitdown 一致（零回归）。
- 纯扫描清华 PDF：8 页全部 OCR，内容完整；默认不开表格 → 无冗余假表。
