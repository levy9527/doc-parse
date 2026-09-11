# CI 流水线说明

本项目使用 Woodpecker CI，代码合并进主干后自动执行：

**构建镜像 → Trivy 安全扫描 → 推送到镜像仓库**

## 触发条件

| 事件 | 是否构建 |
|---|---|
| PR（opened / synchronize） | ❌ 不构建 |
| 特性分支 push | ❌ 不构建 |
| **合并进 `main` / `master`** | ✅ 构建 + 扫描 + 推送 |
| 打 git tag | ✅ 构建 + 扫描 + 推送 |

即**只在真正合并进主干后构建**，避免无效构建占用构建机。

配置在仓库根目录的 `.woodpecker.yml`。

## 三个步骤

| 步骤 | 作用 |
|---|---|
| `build` | 构建镜像 |
| `security-scan` | Trivy 扫描，发现**有修复方案的** HIGH/CRITICAL 即失败，带病镜像不会流出 |
| `push` | 推送到镜像仓库 |

### 镜像 tag 规则

- 打了 git tag → 用 tag 名称
- 否则 → `日期-commit短SHA`，例如 `20260101-a1b2c3d`

日期取**北京时间**。注意容器内通常没有 tzdata，`TZ=Asia/Shanghai` 会**静默失效**
（仍然返回 UTC），必须用 POSIX 格式 `TZ=CST-8`：

```yaml
- export TAG="${CI_COMMIT_TAG:-$(TZ=CST-8 date +%Y%m%d)-$(echo "$CI_COMMIT_SHA" | cut -c1-8)}"
```

## Dockerfile 层顺序（重要）

**依赖安装必须放在 `COPY src/` 之前**：

```dockerfile
# 依赖层：只随 pyproject.toml 变化
COPY pyproject.toml ./
RUN uv pip install <依赖列表>

# 项目层：随源码变化
COPY src/ ./src/
COPY scripts/ ./scripts/
RUN uv pip install --no-deps --no-build-isolation .
```

Docker 的规则是「`COPY` 的文件变了，它**之后**的所有层全部失效」。若先拷源码再装
依赖，**改一行代码就要重下全部依赖**。实测差距：

| 场景 | 先源码后依赖 | 先依赖后源码 |
|---|---|---|
| 冷构建 | 约 25 分钟 | 约 25 分钟（无法避免） |
| **改源码重建** | **约 25 分钟** | **3 秒** |

配套两点：

- `--no-deps --no-build-isolation` —— 依赖已在上一层装好，这里只装项目自身，
  且复用已装好的构建后端，不再访问网络
- `--mount=type=cache,target=/root/.cache/uv` —— 让 uv 下载过的 wheel 跨构建复用，
  即使某层失效也不必重走公网

依赖列表可从 `pyproject.toml` 直接提取，避免手工维护两份清单：

```dockerfile
RUN python -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'));print(chr(10).join(list(d.get('project',{}).get('dependencies',[]))+list(d.get('build-system',{}).get('requires',[]))))" > /tmp/requirements.txt \
    && uv pip install -r /tmp/requirements.txt
```

> `--mount=type=cache` 需要 BuildKit。Docker 23+ 起 `docker build` 默认就是
> BuildKit，无需额外配置。

---

## 踩坑记录

以下都是实际调试中踩到并修复的问题，按"是否与具体环境相关"排序。

### 1. `UV_INDEX_URL` 管不到 `pip`

```dockerfile
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple   # 只作用于 uv
RUN pip install -q uv                                        # ← 仍走 pypi.org！
```

必须**同时**设 `PIP_INDEX_URL`，否则这一行在国内会极慢甚至卡死。

### 2. 部分 registry 不接受 Docker 默认的 attestation 层

Docker 23+ 起 `docker build` 默认走 BuildKit，会给镜像附加 provenance 证明层
（mediaType `application/vnd.oci.empty.v1+json`）。部分私有 registry（例如阿里云
ACR 个人版）无法解析，**blob 全部上传成功后 manifest 被拒**：

```
error from registry: unknown manifest class for application/vnd.oci.empty.v1+json
```

修复：构建时加 `--provenance=false --sbom=false`。

> 代价说明：这样做会同时关掉 SBOM / 来源证明。如果 registry 支持这些特性，
> 应当保留它们而不是关掉。本项目因目标 registry 不支持才关闭。

### 3. Trivy 漏洞库需走国内镜像源

Trivy 默认从 `ghcr.io` 拉漏洞库。该域名的 API 端点在国内可通，但实际 blob 会
重定向到 `pkg-containers.githubusercontent.com`，**国内服务器上会卡死**
（实测 5 分钟无任何进展）。设 `TRIVY_DB_REPOSITORY` 指向国内镜像后，
1 分 56 秒完成首次下载。

配合把漏洞库缓存目录挂进步骤容器复用，**后续每次扫描 <1 秒**：

```yaml
environment:
  TRIVY_DB_REPOSITORY: ghcr.m.daocloud.io/aquasecurity/trivy-db
volumes:
  - /var/cache/trivy:/root/.cache/trivy   # 宿主机上的持久缓存目录
```

### 4. 推大镜像要用 registry 的内网端点

若构建机与 registry 在同一云厂商的同区域，**公网端点会受出口带宽限制**
（实测约 1.2MB/s）。推 2GB 镜像时报：

```
failed commit on ref "layer-sha256:...": net/http: timeout
```

改用 VPC 内网端点后，同一次推送 **31 秒失败 → 7 秒成功**。

注意：两端点**共用同一套账号密码，但需要分别 `docker login`**（docker 按
registry 主机名分别存储凭证）。

### 5. `--ignore-unfixed` 的取舍

扫描参数 `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1` 表示：
**只阻断"有修复方案"的高危漏洞**。

这样做的原因：基础镜像里大量高危漏洞官方**尚无修复版本**，如果一并阻断，
流水线会长期红灯且无法通过升级解决 —— 久而久之大家就学会忽略告警了。

若需要更严格，去掉 `--ignore-unfixed`；若只想先观察，把 `--exit-code` 改成 `0`。

---

## 附：自建 Woodpecker 时才会遇到的坑

普通贡献者可以跳过这一节。

| 问题 | 现象 | 解法 |
|---|---|---|
| `woodpeckerci/*:latest` 是**占位桩** | 拉下来是 13MB 空壳，运行只打印 "The :latest tag has been removed" | 用明确版本号，如 `v3.18.1` |
| SQLite 驱动名 | `database driver 'sqlite' not supported` | 用 **`sqlite3`** |
| 数据目录属主 | `unable to open database file` | 容器内以非 root 的 uid 1000 运行，宿主机目录需 `chown 1000:1000` |
| agent 读不了 docker socket | 流水线无法构建镜像 | compose 里加 `group_add: ["<宿主机 docker 组 GID>"]` |
| gRPC 密钥未持久化 | server 每次重启随机生成，agent 失联 | 设置并持久化 `WOODPECKER_GRPC_SECRET` |
| 仓库未开启 `volumes` 信任 | `[linter] Insufficient trust level to use 'volumes'` | 仓库设置里开 Trusted → Volumes |
| 引用了未创建的 secret | `[generic] secret "xxx" not found`，**流水线连步骤都不会创建** | 用不到就别引用 |
| webhook 响应码 | 分不清是否正常 | **`200` = 创建了流水线；`204` = 收到但按规则跳过**（不是失败） |

### 验证技巧：临时分支验证法

想让流水线在**不合并主干**的前提下跑一次（例如验证 CI 配置改动），可以：

1. 从待验证分支切一个临时分支
2. 在临时分支里把该分支名加入 `when` 的 `branch` 列表
3. push 后流水线即会执行
4. 验证完删除临时分支

这样既验证了 CI，又不会污染正式 PR，也不会在镜像仓库留下无关 tag。
