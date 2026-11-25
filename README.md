# yousj-analytics

自托管的轻量网站访问统计：一个不到 2KB 的上报脚本 + 一个零依赖的 Python 服务（采集、查询 API、看板三合一），数据全部存在你自己的服务器上。既能开网页看板看，也能用命令行查——人和 AI 都能用。

为 [yousj.cc](https://yousj.cc) 而造，通用设计，任何静态站都能接。

## 特性

- **零依赖**：服务端只用 Python 3 标准库（`http.server` + `sqlite3`），单文件 `server.py` 直接跑，不用 pip 装任何东西
- **隐私优先**：不用 Cookie；原始 IP 不落库，只存 HMAC 哈希；UV 用的哈希把日期揉进密钥，盐等效于每天轮换，跨天无法关联同一访客
- **快**：tracker.js 1.5KB，`sendBeacon` 异步上报不阻塞页面；SQLite 开 WAL 模式写入
- **带鉴权**：看板和 API 都要 token（环境变量注入，不写死在代码里）

## 架构

```
页面里的 tracker.js ──sendBeacon──▶ POST /collect ──▶ SQLite (WAL)
                                                          │
        看板 GET /  ◀── server.py ──▶ GET /api/* （token 校验）
        cli.py ──HTTP+Bearer token──▶ GET /api/*
```

## 快速开始

```bash
export ANALYTICS_TOKEN='换成你自己的随机长字符串'
python3 server.py            # 监听 127.0.0.1:8787
```

环境变量：

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `ANALYTICS_TOKEN` | ✅ | — | 看板/API 口令，也是访客哈希的密钥；未设置服务拒绝启动 |
| `ANALYTICS_PORT` | | 8787 | 监听端口 |
| `ANALYTICS_HOST` | | 127.0.0.1 | 监听地址（建议只听本机，前面挂反代） |
| `ANALYTICS_DB` | | `./analytics.db` | SQLite 文件路径 |

日期口径固定为东八区（Asia/Shanghai），如需其他时区改 `server.py` 顶部的 `TZ`。

## 接入网站

每个页面加一行（`data-site` 区分站点，先只有一个站也建议写上）：

```html
<script async src="https://analytics.example.com/tracker.js" data-site="mysite"></script>
```

脚本会自动上报当前路径、来源页（referrer）、浏览器语言、屏幕尺寸。服务端同时对外提供 `/tracker.js`，也可以直接引用服务端的地址。

访客 IP 取 `X-Forwarded-For` 首段（为反代场景设计），没有该头时用直连 IP。

## 看数据

**看板**：浏览器打开服务根路径，输入 token 即可。深色看板展示今日 UV/PV、新访客、跳出率、平均停留、近 7 天 PV 趋势柱状图、热门页面 Top 10。也可直接带 `?token=xxx&site=mysite` 打开。

**命令行**（给脚本和 AI 用，输出 JSON）：

```bash
export ANALYTICS_URL=http://127.0.0.1:8787
export ANALYTICS_TOKEN='你的 token'
python3 cli.py overview            # 今日概况
python3 cli.py overview 2026-11-25 # 指定日期
python3 cli.py trend 7             # 近 7 天 UV/PV
python3 cli.py pages               # 今日热门页面
# 多站点时加 --site mysite
```

## API

以下接口均需鉴权：请求头 `Authorization: Bearer <token>` 或查询参数 `?token=<token>`，未带或错误返回 401。

| 接口 | 说明 |
|---|---|
| `POST /collect` | 上报一次浏览。JSON（或 text/plain beacon），必填 `site`、`path`，可选 `referrer`、`lang`、`screen`、`ts`（毫秒时间戳）。成功返回 204，字段缺失返回 400 |
| `GET /api/overview?site=&date=` | 指定日概况：`uv`、`pv`、`new_visitors`、`bounce_rate`、`avg_duration_sec`（date 缺省为今日） |
| `GET /api/trend?site=&days=7` | 按天 UV/PV 序列 |
| `GET /api/pages?site=&date=` | 热门页面 Top 10（含每页 UV） |

指标口径（都是估算，和所有无 Cookie 统计一样）：

- **UV**：当日不重复的访客哈希数（哈希 = HMAC(日期 + IP + UA)）
- **新访客**：用另一个只用于此目的的稳定伪名哈希记录「首次出现日期」，当日首次出现即新访客
- **跳出率**：当日只浏览 1 个页面的访客占比
- **平均停留**：当日浏览 ≥2 页的访客，其（最后一次 − 第一次）上报间隔的平均值；当日无人浏览多页时返回 `null`

## 部署

直接跑：

```bash
ANALYTICS_TOKEN='...' nohup python3 server.py &
```

systemd 示例（`/etc/systemd/system/yousj-analytics.service`）：

```ini
[Unit]
Description=yousj-analytics
After=network.target

[Service]
WorkingDirectory=/opt/yousj-analytics
Environment=ANALYTICS_TOKEN=换成你自己的随机长字符串
Environment=ANALYTICS_DB=/opt/yousj-analytics/analytics.db
ExecStart=/usr/bin/python3 /opt/yousj-analytics/server.py
Restart=always
User=nobody

[Install]
WantedBy=multi-user.target
```

nginx 反代示例（把采集、看板都挂到一个子域名下）：

```nginx
server {
    listen 443 ssl;
    server_name analytics.example.com;
    # ... 你的证书配置 ...

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
    }
}
```

注意：看板和 API 靠 token 保护，但仍建议给反代加上 HTTPS；采集接口 `/collect` 本身不鉴权（访客浏览器要能直接上报），靠字段校验和体量控制兜底，介意的话可在反代层对 `/collect` 做限速。

## 隐私说明

- 不使用 Cookie，不做跨站追踪，不采集任何表单内容
- 数据库里只有：时间、站点、路径、来源页、语言、屏幕尺寸、两个 HMAC 伪名哈希
- 原始 IP 只在请求处理瞬间用于算哈希，不写入数据库、不写日志（服务默认关闭访问日志输出）
- 更换 `ANALYTICS_TOKEN` 会让历史访客哈希全部对不上（等于换盐），UV 连续性会断，请慎重

## 实测

本地模拟 3 个访客 5 次浏览的完整核对记录见 [TEST.md](TEST.md)。

## License

MIT
