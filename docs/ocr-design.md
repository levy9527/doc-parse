# OCR + 表格识别能力设计（doc-parse）

> 状态：方案评审稿（已按仓库实证修订）。目标：让 doc-parse 能解析 **图片型 / 扫描型 PDF** 及内嵌图片页，
> 并在无文字层的页面上重建结构化 Markdown 表格，同时**不破坏现有纯文本 PDF 的解析质量、不 OCR 好页**。

---

## 1. 背景与问题

当前 PDF 全部走 `markitdown`(0.1.7) 的 pdfminer/pdfplumber 后端——**只读 PDF 自带的文字层，不对像素做 OCR**：

- 有文字层的 PDF（如 `20240201-DWUK-Report-5906.pdf`，48 页 / ~131KB 文本）能正常出文，但页内**以图片呈现的内容（照片、扫描页、图表）无法转写**；
- 纯扫描 / 纯图片型 PDF（无文字层）整体返回空或几乎为空；
- 内嵌 / 单独上传的 `.jpg/.png` 同样不走 OCR。

样例 PDF 实测：45/48 页文字充足，但存在低文字页（第 47 页 text_len=0），且 pdfminer 顶层统计不到 `LTImage`——图片多被包在嵌套/流式对象里，markitdown 不会去读它。

### 结论
需要一个 **OCR + 表格识别** 的引擎，**仅在“无可用文字层”时触发**，覆盖扫描页、图片页、内嵌大图并重建表格；有文字层的页保持原样。

---

## 2. 技术选型（含仓库实证）

| 决策点 | 结论 | 依据 |
|---|---|---|
| OCR 引擎 | **`rapidocr`（统一包）+ `onnxruntime` 引擎** | RapidOCR 官方 CPU 引擎即 ONNX Runtime；统一包 `rapidocr` 是旧拆分包 `rapidocr_onnxruntime` 的继任 |
| 包选型证据 | TableStructureRec **硬性依赖 `rapidocr>1.0,<3.0`** 并调用 `return_word_box=True` 的 2.x 结构化输出 | 拆分包 `rapidocr_onnxruntime` 对不上依赖与新 API，**无法驱动表格管线** |
| PDF 光栅化 | **poppler-utils + pdf2image**（而非 PyMuPDF） | MuPDF/PyMuPDF 有 License 顾虑；poppler 的 `pdftoppm/pdftotext/pdfinfo` 一并解决渲染 + 文字层探测 |
| 文字层处理 | poppler `pdftotext` / pdfminer / pdfplumber | 有文字层 → **不 OCR、不做 image 表格分类**，直接抽文字层（表格即文本） |
| 表格识别 | **`table_cls` + `wired_table_rec` + `lineless_table_rec`** | **只用于无文字层页**；区分有线/无线表格并重建结构化 Markdown |
| 触发策略 | **文档级两档 + 逐页低文字判定** | 全文字页→直接 markitdown（零改动）；含缺文字页→仅缺文字页 OCR+表格 |
| 图片文件 | `.jpg/.jpeg/.png` 走同一 OCR 路径 | 扩展一致性 |
| 模型离线 | 构建期下载并固化进镜像 | 生产环境要求离线运行 |

---

## 3. 总体架构

```
HTTP  /parse  (server.py)
   │
   ▼
doc_parser.parse(filepath)
   │ 按扩展名路由
   ├── .pdf  → pdf_pipeline（见下）
   ├── .jpg/.jpeg/.png → ocr.ocr_image(整图) (+表格识别)
   └── 其他   → markitdown / txt_parser（现状不变）

PDF 管线 pdf_pipeline：
   pdftotext 逐页取文字量
      │
      ├─ 所有页充足 ─►【档 A】整体 markitdown（零改动，不做 OCR）
      │
      └─ 存在缺文字页 ─►【档 B】逐页拼接：
           文字页 ──► 抽文字层（pdfminer/pdfplumber）＝ 文本+表格（不 OCR）
           缺文字页 ──► 渲染位图(poppler 200–300dpi)
                        ├─ RapidOCR(return_word_box=True)：整页行识别 → 正文
                        └─ table_cls(有线/无线) → wired|lineless_table_rec
                             复用上面同一次 ocr_result → HTML→Markdown 表
                        按 y 坐标合并正文+表格+图注 → 页标记
           逐页 page-break 拼接 Markdown
```

### 3.1 文档级两档判定（关键：好文档零改动）
1. 用 poppler `pdftotext` 逐页取原生文字量。
2. **档 A —— 无问题页**：所有页文字量 ≥ 阈值 → 整份直接走现有 `markitdown`，不 OCR、不跑图像表格识别。
3. **档 B —— 存在缺文字页**（低文字/扫描/图片主导页）→ 逐页管线：
   - **文字页**：抽文字层（pdfminer/pdfplumber，即 markitdown 现有依赖），文字层表格本来就是文本；**不做 OCR / table_cls**。
   - **缺文字页**：渲染位图 → RapidOCR 正文 + 表格重建（3.2）。
4. 兜底：整档近空（纯扫描件）→ 全页走 OCR 管线。

> 说明：`table_cls` / wired / lineless 是 **image 侧**识别，仅存在于"无文字层"分支；
> 有文字层的表格不经过图像识别，避免对好页做无用计算。

### 3.2 缺文字页 OCR + 表格重建
1. `pdf2image`(`pdftoppm`) 渲染该页为 PNG（默认 200 DPI；`wired_table_rec v2` 对 >2000px 图建议等比缩放）。
2. 一次 `RapidOCR(img, return_word_box=True)` 拿 `.boxes/.txts/.scores`（带坐标的整页行识别）→ 作为正文来源。
3. `table_cls` 判定页类型（有线/无线）→ 用 `wired_table_rec` / `lineless_table_rec`，并把第 2 步 `ocr_result` **直接喂给表格引擎**（避免二次 OCR）→ 产 HTML → 转 Markdown 表。
4. 按识别框 y 坐标做阅读序合并：正文段落 + 表格 + 图注。
5. 页尾 page-break，逐页拼接。

> 优化：正文与表格**共用同一次 RapidOCR 识别**（`ocr_result` 复用），不重复识别、天然无重复文字。

### 3.3 图片文件（.jpg/.png）
- 直接 RapidOCR + 表格识别，返回 Markdown。复用 `ocr.py` / `table_rec.py`。

---

## 4. 模块与文件改动

```
新增
  ocr.py            # rapidocr 引擎(onnxruntime) 懒加载单例；ocr_image→结构化输出
  table_rec.py      # table_cls/wired/lineless 封装 → html→markdown 表（复用 ocr_result）
  pdf_pipeline.py   # 档 A/B 判定、逐页文字层抽取 / 渲染+OCR+表格、拼接 Markdown
  config.py         # DPI、阈值、模型目录、启用开关(ocr/table)
  scripts/download_models.py  # 构建期拉取固定版本 ONNX 模型到 /app/models
  tests/test_ocr.py / test_table_rec.py / test_pdf_pipeline.py

修改
  doc_parser.py     # .pdf → pdf_pipeline；.jpg/.png → ocr
  requirements.txt  # + 见下
  Dockerfile        # + apt poppler-utils & libgomp1；构建期跑 download_models
  docs/api.md       # 说明 OCR 能力与可选请求参数(ocr=auto/always/never)
```

### 依赖
- **系统(apt)**：`poppler-utils`（pdftoppm/pdftotext/pdfinfo）；`libgomp1`（onnxruntime 在 slim 需要）。
- **Python(pip)**：
  - `pdf2image`（渲染包装，避开 PyMuPDF License）
  - `rapidocr` + `onnxruntime`（统一包，CPU/ONNX Runtime 引擎）
  - `wired_table_rec` `lineless_table_rec` `table_cls`（表格结构识别；要求 `rapidocr>1.0,<3.0`）
  - 保留 `markitdown[pdf,...]`（档 A 整文档 + 非 PDF 文档复用）
- **版本锁定**：上述库迭代快、README 多为最新 main API，与 PyPI 可能不一致。落地按 PyPI 实际版本固定 requirements 并适配真实 API（尤其 `rapidocr` 2.x 结构化输出、table 三包 >=1.2.0/0.1.0 的输入输出）。

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
      poppler-utils libgomp1 && rm -rf /var/lib/apt/lists/*

# 依赖装完后，构建期下载模型并固化
COPY scripts/ requirements.txt ./
RUN pip install -r requirements.txt && python scripts/download_models.py /app/models
```

---

## 5. 配置化（建议默认，可调）

| 参数 | 默认 | 含义 |
|---|---|---|
| `ocr.enabled` | true | OCR 总开关 |
| `ocr.mode` | `auto` | auto / always / never（覆盖自动档判定） |
| `pdf_text_min_chars` | 300 | 页原生文字低于此值判“缺文字页”→ OCR。依据实测：样例真实文字页最低 852，近空页 0–60，300 可干净切分 |
| `ocr.dpi` | 200 | 渲染分辨率（默认不改，250–300 可提小字召回） |
| `table.enabled` | `false` | 无文字层页是否跑表格重建（慢，默认关；需结构时 `TABLE_ENABLED=true`） |
| `model_dir` | env `OCR_MODEL_DIR` | ONNX 模型目录；引擎构造全部传显式 `model_path` |

> 计时/命中页数由调用方负责（现有 parse() 已把计时外置）。

---

## 6. 模型离线预置（已确认）

- `rapidocr` 与 TableStructureRec 模型**默认首次运行自动下载**（GitHub/魔搭/镜像）。生产要求离线：
  1. `scripts/download_models.py`：枚举 rapidocr(检测/分类/识别) + `table_cls` + wired + lineless 各 ONNX 的固定版本 URL，构建期下载并 MD5 校验；运行期**禁用自动拉取**。
  2. 引擎初始化全部显式 `model_path`/config 指向 `/app/models`（RapidOCR config、`TableCls(model_path=...)`、`WiredTableInput(model_path=...)`、`LinelessTableInput(model_path=...)`）。
  3. `.dockerignore` 排除源 `.md`/缓存，避免模型重复或误打包。
- 体积预估：OCR 三件套数十 MB + 表格模型数个 ONNX（各数十 MB）。这是主要成本，见 §8 评审。

---

## 7. 风险与权衡

| 风险 | 缓解 |
|---|---|
| 库版本/API 漂移 | requirements 锁版本；P0 先适配真实 PyPI API |
| onnxruntime 体积/首次加载慢 | 懒加载单例；按需 `table.enabled` |
| 表格识别 CPU 慢 | 仅对无文字层问题页启用 |
| OCR 有错字 | 有文字层页一律不 OCR |
| 正文/表格重复 | 同一次 `ocr_result` 复用于两者，不重复识别 |
| 档 B 文字页重建回归 | 文字页仍走文字层；回归测试对比现有 `out/markitdown/*.md` |
| 与 `/parse` 返回兼容 | 仍返回 `{filename,text}`；可加可选参数 `ocr=auto/always/never`，默认 auto |
| 模型下载/离线 | 构建期 `download_models.py` 固化 + 显式 model_path |

---

## 8. 决策与待评审

**已定**
1. OCR 引擎：统一包 `rapidocr`（CPU=onnxruntime 引擎）——表格三包硬性依赖它及其 2.x 结构化输出。
2. 文字页不做 OCR、不做 image 表格分类；`table_cls` 仅用于无文字层页。
3. 模型构建期离线固化进 Docker（`/app/models` + 显式 `model_path`），运行期不联网。
4. 输出：纯 Markdown 文本（JSON/坐标结构化留二期）。

**待评审**
1. **缺文字页判定阈值** 已定 `pdf_text_min_chars=300`（实测切分值）；是否暴露 `ocr=always/never` 覆盖自动判定 → 会暴露，默认 `auto`。
2. **档 B 文字页重建方式**：含缺文字页时，其余文字页是 (a) 整体 markitdown + 仅缺文字页 OCR 后按页标记插入（快，但 markitdown 无页对齐、插入位置不精确），还是 (b) 文字页用 pdfminer 逐页抽文字层、整档 `pdf_pipeline` 逐页拼 page break（位置精确，实现更重、轻回归风险）。推荐 (b) 仅在“存在缺文字页”时启用。
3. **多表/旋转透视页**：一期整页 `table_cls`→单一引擎；复杂页(一页多表/透视/旋转)二期引入 `rapid-table-det` TableDetector。一期是否接受此简化。

---

## 9. 落地阶段

- **P0 冒烟（离线）**：装依赖、锁定版本、适配真实 PyPI API；下载模型到本地 `models/`；验证 `rapidocr`(onnxruntime)+poppler 能识别样例 PDF 缺文字页；打通 `ocr.py`。
- **P1 打通**：`pdf_pipeline` 两档判定 + 缺文字页 OCR；图片(.jpg/.png)走 OCR；单测 + 样例回归（对比 `out/markitdown/*.md`）。
- **P2 表格**：`table_rec.py`（table_cls + wired/lineless → Markdown 表），无文字层页表格命中验证（复用同一次 OCR）。
- **P3 打磨/Docker**：阅读序合并、阈值调参、config 暴露、`download_models.py` + 构建期固化、`/parse` 可选参数。
- **二期**：`rapid-table-det` 多表/旋转透视、坐标结构化 JSON。
