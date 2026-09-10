# OCR + 表格识别能力（doc-parse）— 设计与落地

> 状态：**已定稿并落地**（分支 `feature/ocr-pdf`）。目标：让 doc-parse 能解析 **图片型 / 扫描型 PDF** 及内嵌
> 图片页，并在需要时重建结构化 Markdown 表格，同时**不破坏现有纯文本 PDF 的解析质量、不 OCR 好页**。
>
> **2026-09 更新（架构简化）**：① PDF **不再走 markitdown**——它会把招聘模板简历的水印竖列/分栏误判成
> markdown 表格，造成「结构伪造 + 水印字符与正文粘连」（实测技能词 `Webpack` 变成 `Webpackd`，词边界失配）；
> ② 渲染由 poppler(`pdftoppm` 逐页子进程) 换成 **pypdfium2(PDFium) 进程内渲染**，实测快约 4.8 倍，poppler 已整体移除。
> 水印判定细节见 `docs/text-quality-design.md`。

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
| PDF 光栅化 | **pypdfium2（PDFium, BSD）进程内渲染** | 无子进程、无临时文件；实测比 poppler+pdf2image 快约 4.8 倍。2026-09 起 poppler 已移除 |
| 文字层页 | 直接抽文字层，**不做 OCR、不做 image 表格分类** | 表格在有文字层时已是文本 |
| 表格识别 | `table_cls` + `wired_table_rec` + `lineless_table_rec` | **仅用于无文字层页**；区分有线/无线重建 Markdown 表；**默认关闭** |
| 触发策略 | **逐页判定**（不再有文档级档 A） | `auto` 仅缺文字页 OCR；`always` 每页强制 OCR；`never` 全不 OCR |
| 图片文件 | `.jpg/.jpeg/.png` 走同一 OCR 路径 | 一致性 |
| 模型离线 | 构建期下载并固化进镜像 | 生产离线运行 |
| 输出 | 纯 Markdown 文本（`/parse` 返回结构不变） | JSON/坐标留二期 |

---

## 3. 总体架构

```
docparse.doc_parser.parse(filepath)
   │ 按扩展名路由
   ├── .pdf            → docparse.pdf_pipeline.parse_pdf
   ├── .jpg/.jpeg/.png → docparse.ocr 图片转写
   └── 其他            → markitdown / docparse.txt_parser（不变）

PDF 管线：pdfminer 逐页取原生文字量（原始长度 + 去水印后有效长度）
   PDF 不走 markitdown，一律逐页处理：
        文字页   ─► pdfminer 抽文字层（不 OCR / 不跑表格模型）
        缺文字页 ─► 渲染位图(pypdfium2, 200dpi) → RapidOCR 识别一次
                     ├─ 输出正文段落
                     └─ 几何门控判定为“真数据网格”时，才按需跑
                        table_cls→(wired|lineless) 重建表格（可关）
```

### 逐页处理与 OCR 模式
- **不再有档 A / 档 B**：PDF 一律逐页处理，markitdown 只服务非 PDF 文档（docx/xlsx/pptx/html…）。
- 每页决策 `_should_ocr_page(mode, raw_len, meaningful_len)`：
  - `auto`（默认）：仅「缺文字页」OCR，其余走 pdfminer 文字层；
  - `always`：**每页都强制 OCR**（忽略文字层；慢，用于排查/质检）；
  - `never`：完全不 OCR（缺文字页输出占位提示）。
- 缺文字页判定：页原生文字 `< pdf_text_min_chars(=300)`，**或**「水印主导页」（原文够长但去掉
  水印噪声后有效文字不足阈值且噪声占比 ≥ 50%）——后者救「可见内容是图片、文字层只剩水印」的模板 PDF。

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
| `src/docparse/config.py` | 配置，均可环境变量覆盖（见 §5） |
| `src/docparse/ocr.py` | RapidOCR 懒加载单例；单次识别、正文/表格共用；几何门控 |
| `src/docparse/table_rec.py` | `table_cls`→wired/lineless（懒加载）；html→Markdown 表 + 验收门控 |
| `src/docparse/pdf_pipeline.py` | 逐页判定与文字层抽取 / 渲染(pypdfium2)+OCR+表格、拼接 Markdown |
| `scripts/download_models.py` | 构建期离线固化 ONNX 模型 + manifest |
| 修改 | `src/docparse/doc_parser.py`、`pyproject.toml`、`Dockerfile`、`docs/api.md` |
| 测试 | `tests/test_config.py`、`tests/test_table_rec.py`、`tests/test_text_quality.py`、`tests/test_pdf_pipeline.py`（全套 31 项通过） |

### 依赖
- **apt**：`libgomp1`（onnxruntime）、`libgl1` `libglib2.0-0`（cv2）。（`poppler-utils` 已移除）
- **pip/uv**：`pypdfium2`（渲染）、`rapidocr` + `onnxruntime`（统一包）、`wired_table_rec` `lineless_table_rec` `table_cls`；`markitdown[...]` 仅用于非 PDF 格式。
- **版本**：按 PyPI 实际版本锁定（`pyproject.toml` 已固定），避免上游迭代 API 漂移。

---

## 5. 配置（全部经环境变量）

| 环境变量 | 默认 | 含义 |
|---|---|---|
| `OCR_MODE` | `auto` | `auto`(仅缺文字页 OCR，推荐) / `always`(**每页强制 OCR**) / `never`(完全不 OCR) |
| `PDF_TEXT_MIN_CHARS` | `300` | 页原生文字低于此值判缺文字页 → OCR。实测：样例文字页最低 852、近空页 0–60，300 可干净切分 |
| `OCR_DPI` | `200` | 渲染分辨率（保持 200） |
| `TABLE_ENABLED` | `false` | 是否跑表格重建（慢，需结构时开 `true`） |
| `OCR_MODEL_DIR` | 各包默认 | ONNX 模型目录 |
| `OCR_INTRA_THREADS` | `8` | onnxruntime intra-op 线程数。**实测 auto 最慢**（超额订阅）；建议取可见核数的 1/2~1/6（12 核→6，96 核→16）。`OMP_NUM_THREADS` 无效，必须用本项 |
| `OCR_INTER_THREADS` | `0`(自动) | onnxruntime inter-op 线程数 |

---

## 6. 模型离线预置

- `rapidocr`/表格三包模型默认首次运行自动下载（modelscope）。生产要求离线：
  - `scripts/download_models.py`：构建期实例化各引擎（触发下载）→ 把 7 个 ONNX(~150MB) 拷贝到 `/app/models` 并写 `manifest.json`(sha256)；
  - 该步同时填充到 site-packages 各包 models 缓存，运行期离线可用。
- 7 个模型：rapidocr 3（det/cls/rec）+ `table_cls` 1 + `wired_table_rec` 1 + `lineless_table_rec` 2（detect/process）。

---

## 7. Docker

- base `python:3.12-slim`（daocloud 镜像），apt 源先切**清华镜像**（官方源国内 502）。
- 安装：`libgomp1 libgl1 libglib2.0-0`（不再安装 poppler-utils）。
- 依赖：先 `pip install uv`，后 `uv pip install`（`UV_INDEX_URL`/`UV_SYSTEM_PYTHON` 指向清华源与系统 Python）。
- 构建期跑 `scripts/download_models.py /app/models` 固化模型。
- 渲染统一走 `pypdfium2`（PDFium, BSD），本地与容器一致，无 poppler 依赖。

---

## 8. 已定决策 & 已知限制

### 已定
1. OCR：统一包 `rapidocr`(onnxruntime)，文字页不 OCR、`table_cls` 仅用于无文字层页。
2. 文字页用 pdfminer 逐页抽文字层、整档拼 page break（保位置）；**PDF 不再使用 markitdown**，markitdown 仅服务非 PDF 文档。
3. 缺文字阈值 `pdf_text_min_chars=300`；`OCR_MODE=always/never` 可覆盖自动判定。
4. 表格一期整页 `table_cls`→单一引擎（多表/旋转透视暂不做）。
5. 表格重建默认关闭（`TABLE_ENABLED=false`）；模型构建期离线固化；输出纯 Markdown。

### 已知限制 / 二期
- `table_cls` 只有 wired/wireless 两类、无“无表”类，靠几何门控 + 结构验收兜底；一页多表、旋转/透视需 `rapid-table-det`。
- 表格重建为 best-effort、存在轻微不确定性（同页可能只出正文未出表，或有正文/表格少量重复）。
- 有表格结构的纯文字 PDF，文字页为 pdfminer 平铺文本（不再有 markitdown 的表格排版还原）；需要结构时开 `TABLE_ENABLED=true` 仅对无文字层页生效。
- 坐标结构化 JSON 输出留二期。
- 容器(linux)OCR 比本地(macOS)慢（onnxruntime/架构差异），纯 OCR 热跑约 ~9s/8 页扫描。

---

## 9. 验证（容器实测，纯扫描 PDF 8 页）

| 配置 | 首跑 | 热跑 |
|---|---|---|
| 表格开启 | ~21s | ~14s |
| 纯 OCR（`TABLE_ENABLED=false`，默认） | ~10.7s | **~8.8s** |

- DWUK 报告（文字型）逐页 pdfminer 抽取，干净可读（2026-09 前为走 markitdown，现 PDF 不再使用）。
- 纯扫描清华 PDF：8 页全部 OCR，内容完整；默认不开表格 → 无冗余假表。

---

## 10. 性能实测与调优（2026-09 补充）

### 10.1 渲染器：poppler → pypdfium2

同一张页面图，交替 4 轮（排除顺序/噪声），隔离渲染与 OCR：

| 渲染器 | 渲染 s/页 | OCR s/页 | 合计 s/页 |
|---|---|---|---|
| poppler(`pdftoppm` 子进程) | 0.410 ~ 0.439 | 0.867 ~ 1.000 | 1.277 ~ 1.439 |
| **pypdfium2（进程内）** | **0.081 ~ 0.084** | 1.020 ~ 1.069 | **1.102 ~ 1.153** |

- **渲染快约 5.2 倍**（四轮全部稳定复现）——换 pypdfium2 的核心目标达成。
- ⚠️ pdfium 渲染出的图，**OCR 慢约 12%**（两图尺寸相同 4000×2250、识别行数 99~100 几乎一致；
  推测为抗锯齿/对比度差异导致检测阶段开销变化）。渲染节省仍大于该损失。
- 净收益：图文页约 **17%**；密集正文页渲染占比小，收益更小（见 10.2 的教材实测）。
- 内容一致性（换渲染器不丢质量）：120 页教材相似度 **97.0%**；水印型简历相似度 **99.3%**，
  且姓名/手机/邮箱/学历/技能命中**完全一致**。有文字层的 PDF 两环境输出**逐字节相同**
  （不渲染，走 pdfminer）。

### 10.2 镜像对照（服务器 10.116.23.80，背靠背、同条件）

| 镜像 | 渲染器 | 教材 120 页（全 OCR） |
|---|---|---|
| 新（`doc-parse:ocr` / `20260910-ocr`） | pypdfium2 | **400.1s** |
| 线上旧镜像 | poppler | 424.2s |

→ 新镜像快 **24.1s（5.7%）**；两者均 120 页全 OCR，内容一致（82,263 vs 82,068 字）。

### 10.3 线程数：真正的旋钮是 `intra_op`，**不是** `OMP_NUM_THREADS`

固定同一张图只 OCR（隔离渲染），改线程数：

| `intra_op_num_threads` | Mac(12 核) | 服务器(96 核) |
|---|---|---|
| auto (-1) | 0.936s | **1.676s（最慢）** |
| 64 | — | 0.915s |
| 32 | — | 1.156s |
| 16 | — | **0.766s（最快）** |
| 12 | 0.962s | 0.922s |
| **8** | **0.528s** | 1.065s |
| **6** | **0.468s（最快）** | 1.074s |
| 4 | 0.513s | 1.387s |
| 2 | 0.865s | — |
| 1 | 1.598s | — |

- `OMP_NUM_THREADS` 设 1 / 6 / 8 / 12 **完全无差别**（0.92~1.00s）→ 该变量对本环境的
  onnxruntime 引擎**无效**，别白设。
- 生效的是 `EngineConfig.onnxruntime.intra_op_num_threads`（RapidOCR `params`）。**auto 最慢**：
  它会按可见核数开满线程池，在容器里超额订阅反而拖慢（Mac 12 核 ~2 倍差距；
  服务器 96 核 auto 1.676s vs 16 线程 0.766s，**2.2 倍**）。
- 通过环境变量 **`OCR_INTRA_THREADS`** 配置（见 §5 与 `.env.sample`），**默认 8**（避免 auto 的超额订阅）。
  建议值约为可见核数的 **1/2 ~ 1/6**，并按机器实测：本次 12 核 → **6**，96 核 → **16**。线程数过多或过少都变慢。

### 10.4 负载测量的坑（重要）

- Mac 实测：空闲 1 分钟负载 ~3；跑 120 页 OCR 期间升到 **~79**，跑完立刻回落到 ~3。
- 即**负载主要由本次测试自身产生**（onnxruntime 线程 + Docker VM 的 IO 等待），不是桌面软件占用。
- 因此**跨时间点的绝对耗时不可比**（同一份教材曾测得 195s / 322s / 345s），
  评估改动必须做**背靠背对照**（如 10.1 / 10.2 的做法）。

### 10.5 单页并行度（决定下一步优化方向）

OCR 期间容器 CPU 约 **1300%（12 核）** → 单页 OCR 已基本吃满 12 核，
所以在 12 核机器上再做「页级并行」收益有限；但服务器 96 核下单页仅用十几个线程，
**页级并行在服务器上仍有较大空间**（需实测，见 §8 二期）。
