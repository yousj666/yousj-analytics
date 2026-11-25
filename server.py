#!/usr/bin/env python3
"""yousj-analytics — self-hosted lightweight website analytics.

Zero-dependency (Python 3 standard library only): collector + query API +
dashboard in a single file, backed by SQLite (WAL mode).

Environment:
  ANALYTICS_TOKEN   required — shared secret for /api/* and the dashboard.
                    The server refuses to start when it is unset.
  ANALYTICS_PORT    listen port (default 8787)
  ANALYTICS_HOST    listen host (default 127.0.0.1)
  ANALYTICS_DB      SQLite file path (default ./analytics.db)

Privacy:
  No cookies. Raw IPs are never stored. A visitor is represented by two
  pseudonymous hashes (HMAC-SHA256 keyed with ANALYTICS_TOKEN):
    - visitor_day:  key includes the calendar date, so the salt effectively
      rotates daily and a visitor cannot be linked across days with it.
      Used for UV.
    - visitor_seen: stable key used ONLY to estimate "new vs returning"
      (first day this pseudonym was ever seen).
"""

import hashlib
import hmac
import json
import os
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = os.environ.get("ANALYTICS_TOKEN", "")
if not TOKEN:
    sys.stderr.write("error: ANALYTICS_TOKEN environment variable is not set\n")
    sys.exit(1)

HOST = os.environ.get("ANALYTICS_HOST", "127.0.0.1")
PORT = int(os.environ.get("ANALYTICS_PORT", "8787"))
DB_PATH = os.environ.get("ANALYTICS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "analytics.db"))
TZ = timezone(timedelta(hours=8))  # dashboard/API dates are Asia/Shanghai; adjust to your locale

_lock = threading.Lock()
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.execute("PRAGMA journal_mode=WAL")
_db.execute(
    """CREATE TABLE IF NOT EXISTS events(
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         ts INTEGER NOT NULL,
         day TEXT NOT NULL,
         site TEXT NOT NULL,
         path TEXT NOT NULL,
         referrer TEXT DEFAULT '',
         lang TEXT DEFAULT '',
         screen TEXT DEFAULT '',
         visitor_day TEXT NOT NULL,
         visitor_seen TEXT NOT NULL)"""
)
_db.execute("CREATE INDEX IF NOT EXISTS idx_events_site_day ON events(site, day)")
_db.commit()


def _hmac_hex(*parts):
    m = hmac.new(TOKEN.encode(), "\x1f".join(parts).encode(), hashlib.sha256)
    return m.hexdigest()


def day_of(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, TZ).strftime("%Y-%m-%d")


def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def client_ip(headers, peer):
    xff = headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return peer or ""


# ---------------------------------------------------------------- queries

def q_overview(site, day):
    with _lock:
        pv = _db.execute("SELECT COUNT(*) FROM events WHERE site=? AND day=?", (site, day)).fetchone()[0]
        uv = _db.execute("SELECT COUNT(DISTINCT visitor_day) FROM events WHERE site=? AND day=?", (site, day)).fetchone()[0]
        new = _db.execute(
            """SELECT COUNT(*) FROM (
                 SELECT visitor_seen, MIN(day) AS first_day FROM events WHERE site=? GROUP BY visitor_seen
               ) WHERE first_day=?""",
            (site, day),
        ).fetchone()[0]
        single = _db.execute(
            """SELECT COUNT(*) FROM (
                 SELECT visitor_day FROM events WHERE site=? AND day=? GROUP BY visitor_day HAVING COUNT(*)=1
               )""",
            (site, day),
        ).fetchone()[0]
        spans = _db.execute(
            """SELECT (MAX(ts)-MIN(ts))/1000.0 FROM events WHERE site=? AND day=?
               GROUP BY visitor_day HAVING COUNT(*)>=2""",
            (site, day),
        ).fetchall()
    bounce = round(single / uv, 4) if uv else None
    avg = round(sum(r[0] for r in spans) / len(spans), 1) if spans else None
    return {
        "site": site,
        "date": day,
        "uv": uv,
        "pv": pv,
        "new_visitors": new,
        "bounce_rate": bounce,        # estimate: share of visitors with exactly 1 pageview
        "avg_duration_sec": avg,      # estimate: mean (last-first pageview) per multi-view visitor; null if none
    }


def q_trend(site, days):
    end = datetime.now(TZ).date()
    out = []
    with _lock:
        for i in range(days - 1, -1, -1):
            d = (end - timedelta(days=i)).strftime("%Y-%m-%d")
            pv = _db.execute("SELECT COUNT(*) FROM events WHERE site=? AND day=?", (site, d)).fetchone()[0]
            uv = _db.execute("SELECT COUNT(DISTINCT visitor_day) FROM events WHERE site=? AND day=?", (site, d)).fetchone()[0]
            out.append({"date": d, "uv": uv, "pv": pv})
    return {"site": site, "days": days, "trend": out}


def q_pages(site, day, limit=10):
    with _lock:
        rows = _db.execute(
            """SELECT path, COUNT(*) AS pv, COUNT(DISTINCT visitor_day) AS uv
               FROM events WHERE site=? AND day=? GROUP BY path ORDER BY pv DESC LIMIT ?""",
            (site, day, limit),
        ).fetchall()
    return {"site": site, "date": day, "pages": [{"path": p, "pv": pv, "uv": uv} for p, pv, uv in rows]}


# ---------------------------------------------------------------- dashboard

CSS = """
body{background:#0b0e14;color:#e6e1d8;font-family:system-ui,'Segoe UI',Roboto,sans-serif;margin:0;padding:24px}
h1{font-size:20px;color:#f0b429;letter-spacing:.05em}
.cards{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}
.card{background:#131824;border:1px solid #232a3a;border-radius:10px;padding:16px 20px;min-width:140px}
.card .n{font-size:36px;font-weight:700;color:#fff}
.card .l{color:#9aa3b2;font-size:13px;margin-top:4px}
table{border-collapse:collapse;width:100%;max-width:720px;background:#131824;border:1px solid #232a3a;border-radius:10px;overflow:hidden}
td,th{padding:8px 12px;border-bottom:1px solid #232a3a;text-align:left;font-size:14px}
th{color:#f0b429}
.bar{display:flex;align-items:flex-end;gap:6px;height:120px;margin:12px 0}
.bar div{flex:1;background:#f0b429;border-radius:3px 3px 0 0;position:relative;min-height:2px}
.bar span{position:absolute;bottom:-18px;left:0;right:0;text-align:center;font-size:10px;color:#9aa3b2}
input{background:#131824;border:1px solid #232a3a;color:#fff;padding:8px;border-radius:6px}
button{background:#f0b429;border:0;padding:8px 14px;border-radius:6px;font-weight:600;cursor:pointer}
"""


def dashboard_html(site, token):
    ov = q_overview(site, today())
    tr = q_trend(site, 7)["trend"]
    pg = q_pages(site, today())["pages"]
    maxpv = max([r["pv"] for r in tr] + [1])
    bars = "".join(
        '<div style="height:%d%%" title="%s PV %d"><span>%s</span></div>'
        % (max(2, r["pv"] * 100 // maxpv), r["date"], r["pv"], r["date"][5:])
        for r in tr
    )
    rows = "".join(
        "<tr><td>%s</td><td>%d</td><td>%d</td></tr>" % (p["path"], p["pv"], p["uv"]) for p in pg
    ) or '<tr><td colspan="3">暂无数据</td></tr>'
    bounce = "—" if ov["bounce_rate"] is None else "%.0f%%" % (ov["bounce_rate"] * 100)
    avg = "—" if ov["avg_duration_sec"] is None else "%s 秒" % ov["avg_duration_sec"]
    return """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>网站统计 · %s</title><style>%s</style></head><body>
<h1>网站统计看板 · %s（今日）</h1>
<div class="cards">
 <div class="card"><div class="n">%d</div><div class="l">访客 UV</div></div>
 <div class="card"><div class="n">%d</div><div class="l">浏览 PV</div></div>
 <div class="card"><div class="n">%d</div><div class="l">新访客（估算）</div></div>
 <div class="card"><div class="n">%s</div><div class="l">跳出率（估算）</div></div>
 <div class="card"><div class="n">%s</div><div class="l">平均停留（估算）</div></div>
</div>
<h1>近 7 天 PV 趋势</h1><div class="bar">%s</div>
<h1 style="margin-top:36px">热门页面 Top 10</h1>
<table><tr><th>页面</th><th>PV</th><th>UV</th></tr>%s</table>
</body></html>""" % (site, CSS, site, ov["uv"], ov["pv"], ov["new_visitors"], bounce, avg, bars, rows)


LOGIN_HTML = """<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>网站统计</title>
<style>%s</style></head><body><h1>网站统计看板</h1>
<form method="get"><input type="password" name="token" placeholder="访问令牌"> <button>进入</button></form>
</body></html>""" % CSS


# ---------------------------------------------------------------- handler

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self, qs):
        given = qs.get("token", [""])[0] or self.headers.get("Authorization", "").replace("Bearer ", "")
        return hmac.compare_digest(given, TOKEN)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/collect":
            return self._send(404, json.dumps({"error": "not found"}))
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            ev = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return self._send(400, json.dumps({"error": "bad json"}))
        site = str(ev.get("site", ""))[:64]
        path = str(ev.get("path", ""))[:512]
        if not site or not path:
            return self._send(400, json.dumps({"error": "site and path are required"}))
        ts = int(ev.get("ts") or 0) or int(datetime.now(timezone.utc).timestamp() * 1000)
        day = day_of(ts)
        ip = client_ip(self.headers, self.client_address[0])
        ua = self.headers.get("User-Agent", "")
        with _lock:
            _db.execute(
                "INSERT INTO events(ts,day,site,path,referrer,lang,screen,visitor_day,visitor_seen) VALUES(?,?,?,?,?,?,?,?,?)",
                (ts, day, site, path, str(ev.get("referrer", ""))[:512], str(ev.get("lang", ""))[:32],
                 str(ev.get("screen", ""))[:32], _hmac_hex("day", day, ip, ua), _hmac_hex("seen", ip, ua)),
            )
            _db.commit()
        self._send(204, b"", "text/plain")

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/tracker.js":
            here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker.js")
            with open(here, "rb") as f:
                return self._send(200, f.read(), "application/javascript; charset=utf-8")
        if u.path == "/":
            if not self._authed(qs):
                return self._send(200, LOGIN_HTML, "text/html; charset=utf-8")
            site = qs.get("site", ["default"])[0]
            return self._send(200, dashboard_html(site, TOKEN), "text/html; charset=utf-8")
        if u.path.startswith("/api/"):
            if not self._authed(qs):
                return self._send(401, json.dumps({"error": "unauthorized"}))
            site = qs.get("site", ["default"])[0]
            if u.path == "/api/overview":
                return self._send(200, json.dumps(q_overview(site, qs.get("date", [today()])[0]), ensure_ascii=False))
            if u.path == "/api/trend":
                return self._send(200, json.dumps(q_trend(site, int(qs.get("days", ["7"])[0])), ensure_ascii=False))
            if u.path == "/api/pages":
                return self._send(200, json.dumps(q_pages(site, qs.get("date", [today()])[0]), ensure_ascii=False))
            return self._send(404, json.dumps({"error": "unknown api"}))
        return self._send(404, json.dumps({"error": "not found"}))


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
