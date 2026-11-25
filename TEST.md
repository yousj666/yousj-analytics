# 本地实测记录（2026-11-25）

环境：Python 3 标准库，服务以测试 token 在本地 18787 端口启动，数据库为临时 SQLite 文件。

## 模拟上报

用 3 个不同 IP + UA 的「访客」共上报 5 次页面浏览（经 X-Forwarded-For 模拟来源 IP）：

| 访客 | IP | 页面 | 时间间隔 |
|---|---|---|---|
| A | 1.1.1.1 | `/`、`/tools/` | 两次间隔 60 秒 |
| B | 2.2.2.2 | `/`、`/games/` | 两次间隔 30 秒 |
| C | 3.3.3.3 | `/` | 1 次 |

5 次 POST /collect 全部返回 204。

## 核对结果

`cli.py overview`：

```json
{
  "site": "default",
  "date": "2026-11-25",
  "uv": 3,
  "pv": 5,
  "new_visitors": 3,
  "bounce_rate": 0.3333,
  "avg_duration_sec": 45.0
}
```

- UV=3、PV=5 ✅ 与模拟一致
- 新访客=3 ✅（三位都是首次出现）
- 跳出率=0.3333 ✅（3 人中 1 人只看 1 页）
- 平均停留=45.0 秒 ✅（(60+30)/2）

`cli.py pages` 排序正确：`/` PV 3 / UV 3 第一，`/tools/`、`/games/` 各 PV 1。

`cli.py trend 7`：今日 (UV 3, PV 5)，前 6 天全 0 ✅。

## 安全与边界检查

| 检查 | 结果 |
|---|---|
| 无 token 访问 `/api/overview` | 401 ✅ |
| 无 token 打开看板 `/` | 显示令牌输入框 ✅ |
| 带 token 打开看板 | 200，大字数字 3 / 5 / 3 ✅ |
| POST /collect 缺 path 字段 | 400 ✅ |
| 未设置 ANALYTICS_TOKEN 启动 | 报错 `error: ANALYTICS_TOKEN environment variable is not set` 并以 exit 1 退出 ✅ |
| tracker.js 体积 | 1484 字节（≤2KB）✅ |
