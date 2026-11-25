#!/usr/bin/env python3
"""yousj-analytics CLI — query a running server from the command line (AI-friendly).

Connection comes from the environment:
  ANALYTICS_URL    base URL of the server (default http://127.0.0.1:8787)
  ANALYTICS_TOKEN  the same token the server was started with

Usage:
  python3 cli.py overview [YYYY-MM-DD] [--site SITE]
  python3 cli.py trend [DAYS]         [--site SITE]
  python3 cli.py pages [YYYY-MM-DD]   [--site SITE]

Output is JSON on stdout.
"""

import json
import os
import sys
import urllib.request

BASE = os.environ.get("ANALYTICS_URL", "http://127.0.0.1:8787").rstrip("/")
TOKEN = os.environ.get("ANALYTICS_TOKEN", "")


def call(path, params):
    qs = "&".join("%s=%s" % (k, v) for k, v in params.items() if v is not None)
    url = BASE + path + ("?" + qs if qs else "")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOKEN})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    site = "default"
    for i, a in enumerate(argv):
        if a == "--site" and i + 1 < len(argv):
            site = argv[i + 1]
    if not args:
        sys.stderr.write(__doc__)
        return 2
    cmd = args[0]
    if cmd == "overview":
        out = call("/api/overview", {"site": site, "date": args[1] if len(args) > 1 else None})
    elif cmd == "trend":
        out = call("/api/trend", {"site": site, "days": args[1] if len(args) > 1 else "7"})
    elif cmd == "pages":
        out = call("/api/pages", {"site": site, "date": args[1] if len(args) > 1 else None})
    else:
        sys.stderr.write("unknown command: %s\n" % cmd)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
