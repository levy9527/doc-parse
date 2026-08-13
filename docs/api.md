# doc-parse 接口说明

文档解析服务，接收文件并返回 Markdown 文本。基于 `markitdown`，以独立 Python 镜像提供 HTTP 服务，供 Node.js 等其它服务调用。

## 镜像信息

- 镜像：`doc-parse:20260813`
- 端口：`8000`
- 构建：`docker build -t doc-parse:20260813 .`

## 运行

```bash
docker run -d --name doc-parse -p 8000:8000 doc-parse:20260813
```

## 接口

### 1. 健康检查

`GET /health`

响应：

```json
{ "status": "ok" }
```

### 2. 解析文档

`POST /parse`

以 `multipart/form-data` 上传文件，字段名为 `file`。

请求：

```
POST /parse
Content-Type: multipart/form-data; boundary=...

file=<文件二进制>
```

响应（成功，`200`）：

```json
{
  "filename": "demo.pdf",
  "text": "# 标题\n\n正文 Markdown 内容..."
}
```

错误响应：

| 状态码 | detail |
| ------ | ------ |
| `400`  | 缺少文件名 |
| `500`  | 写入临时文件失败 / 解析失败 |

## 支持的文件类型

| 类型 | 扩展名 |
| ---- | ------ |
| Word | `.docx` |
| Excel / CSV | `.xls` `.xlsx` `.csv` |
| PPT | `.pptx` |
| PDF | `.pdf` |
| 网页 | `.htm` `.html` `.xml` `.rss` `.atom` |
| 电子书 / 笔记 | `.epub` `.ipynb` |
| 邮件 | `.msg` |
| 压缩包 | `.zip` |
| 数据 | `.json` `.jsonl` |
| 图片 | `.jpg` `.jpeg` `.png` |
| 音频 / 视频 | `.m4a` `.mp3` `.wav` `.mp4` |
| 纯文本 | `.txt` 及其它（自动探测编码） |

## 调用示例

### curl

```bash
curl -F "file=@demo.pdf" http://localhost:8000/parse
```

### Node.js

```js
import { readFile } from 'node:fs/promises';

const bytes = await readFile('demo.pdf');
const fd = new FormData();
fd.append('file', new Blob([bytes]), 'demo.pdf');

const res = await fetch('http://localhost:8000/parse', {
  method: 'POST',
  body: fd,
});
const { text } = await res.json();
```

### Python

```python
import requests

with open("demo.pdf", "rb") as f:
    resp = requests.post(
        "http://localhost:8000/parse",
        files={"file": ("demo.pdf", f)},
    )
text = resp.json()["text"]
```
