# Myrmidon 控制台 v1（首个 UI 版本）

基于 [sapper-v2](https://github.com/N1nEmAn/sapper-v2) 的产品化分支：保留「事实图谱 + 自主编排」内核，重做 Web 控制台，并补齐交付级能力。

## 这一版有什么

| 能力 | 说明 |
|---|---|
| **页面化控制台** | 概览 / 任务 / 跑分 / 设置 四页；任务表支持搜索、状态筛选、排序、分页、批量置顶删除、双击改名 |
| **任务详情五页签** | 结论（可读总结）、作战图（泳道/DAG 双布局、拖拽缩放）、发现（flag 台账）、步骤（时间线）、日志（增量轮询） |
| **登录与隔离** | pbkdf2 密码 + 会话 Cookie；`admin` / `viewer` 两角色；viewer 只能看被授权目录，跑分与设置页不可见 |
| **三种状态语义** | 运行中（脉冲）/ 未完成（预算内没判定完成，进度保留）/ 已完成，避免"怎么还有任务在跑"的歧义 |
| **多平台** | TSecBench 原生；CTFd 适配器；本地离线题目（`arena_local`）；无平台也能用自由任务 |
| **模型与引擎** | 网关模型列表拉取、按引擎切换（DeepSeek / 网关 / 原生 CLI）、Auto 默认预算与步数全局配置 |
| **Docker 交付** | 控制台镜像 + compose + 入口脚本 + 健康检查；数据全在 `/data` 卷，容器无状态 |

截图与完整介绍见仓库根目录 [MYRMIDON.md](../MYRMIDON.md)。

## 快速开始（源码）

```bash
git clone https://github.com/zzhnohikari/myrmidon.git
cd myrmidon
./install.sh
sapper console-user add admin --password '强密码'      # 写 ~/.sapper/users.json
sapper console --root ~/sapper-missions --port 8890    # 打开 http://127.0.0.1:8890
```

模型凭证二选一：页面「设置 → 模型网关」填；或环境变量 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`。

## Docker 部署（打包镜像）

### 1. 构建

```bash
# --platform 必须与客户机器架构一致：x86_64 云主机用 amd64，Apple/ARM 用 arm64
docker build --platform linux/amd64 -f docker/Dockerfile.console -t myrmidon-console:1.0.0 .
docker image inspect myrmidon-console:1.0.0 --format '{{.Os}}/{{.Architecture}}'
```

### 2. 导出 / 导入（离线交付）

```bash
docker save myrmidon-console:1.0.0 | gzip > myrmidon-console-1.0.0.tar.gz   # 约 405MB

# 客户机上
docker load < myrmidon-console-1.0.0.tar.gz
```

### 3. 生成账号

```bash
mkdir -p /opt/myrmidon/data
docker run --rm --entrypoint python3 \
  -v /opt/myrmidon/data:/data myrmidon-console:1.0.0 \
  /app/lib/sapper.py console-user add admin \
  --role admin --password '换成强密码'
```

> 注意 `--entrypoint python3`：镜像默认入口是控制台启动脚本，跑一次性命令必须覆盖。
>
> 不带 `--file` 也可以：默认写到 `$HOME/.sapper/users.json`（容器内即 `/data/.sapper/users.json`），
> 控制台和入口脚本都会自动识别。也可以显式 `--file /data/users.json`，两种都生效。

### 4. 启动

```bash
docker run -d --name myrmidon --restart unless-stopped \
  -p 127.0.0.1:8890:8890 \
  -v /opt/myrmidon/data:/data \
  -e ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic \
  -e ANTHROPIC_AUTH_TOKEN=sk-你的key \
  myrmidon-console:1.0.0
```

### 5. 验证

```bash
curl -s http://127.0.0.1:8890/api/health                      # {"ok": true, ...}
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8890/api/missions
# 期望 401（鉴权生效）。返回 200 说明还是开放模式，检查 users.json 落点
```

浏览器打开 `http://127.0.0.1:8890`，用刚建的账号登录。

### 本次构建产物

| 项 | 值 |
|---|---|
| 平台 | **`linux/amd64`**（x86_64 云主机直接可用） |
| image id | `sha256:001a24e3803cc84e739600d493cdc8ee15597fcfed997f1ce34f281554fe31bf` |
| 大小 | 423,800,958 字节 |
| tar.gz | `myrmidon-console-1.0.0-linux-amd64.tar.gz`（423,081,834 字节） |
| sha256 | `c2b3da8d384271c9c97bf2f8a4192e34f430d7892af9a3d7c13764c06ad1e14f` |

> 早前误打的 `linux/arm64` 包只适用于 Apple Silicon / ARM 服务器，`docker load` 到 x86_64 上会
> `exec format error`，已从 Release 移除。ARM 环境请用 `--platform linux/arm64` 自行构建。

**实测（腾讯云北京竞价 SA3.MEDIUM4 / Ubuntu 22.04）**：`docker load` 11s → 建账号 → `docker run` →
容器 healthy、未登录 401、登录 200、建任务成功。

## 文档

- [使用手册（Markdown）](../docs/使用手册.md) · [图文版 HTML](../docs/使用手册.html)
- [交付部署手册](../docs/交付部署.md)（含 Nginx/HTTPS、VPN 三种接法、备份、升级回滚、离线镜像分发）
- [新平台接入](../docs/新平台接入.md)（三种方式 + 5 方法适配器契约）

## 已知边界

- 控制台镜像是「大脑」，不含 nmap / pwntools / nuclei；需要真正执行工具时用 Kali 底座镜像 `docker/Dockerfile`
- 前端无构建链（单文件模板），改完模板需重启 console 进程
- 尚未实现：审计日志、报告模板导出、服务端分页（大数据量下列表仍是全量拉取后前端分页）
- 本项目仅用于**授权**的安全测试与比赛环境，见 [DISCLAIMER.md](../DISCLAIMER.md)
