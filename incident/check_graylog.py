#!/usr/bin/env python3
"""One read-only smoke test of the Graylog transport against your server: run a single search and print only the field NAMES of one message.

    GRAYLOG_URL=https://graylog.example.org GRAYLOG_TOKEN=... python3 -I incident/check_graylog.py

You create the token (a read-only user's API token) and set it in your own shell; nothing here stores it. No message values are printed, so
the output is safe to paste back when the request or response shape needs adjusting.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from incident import sources as S


def check(search):
    rows = search("*", 300, 1)
    return {"rows": len(rows), "fields": sorted(rows[0]) if rows else []}


def main():
    url, token = os.environ.get("GRAYLOG_URL"), os.environ.get("GRAYLOG_TOKEN")
    if not url or not token:
        sys.exit("set GRAYLOG_URL and GRAYLOG_TOKEN (a read-only API token you created) in your shell")
    try:
        print(json.dumps(check(S.graylog_transport(url, token)), indent=1))
    except Exception as e:   # the type and HTTP status only; never the request or the token
        sys.exit(f"failed: {type(e).__name__}: {getattr(e, 'code', '')} {getattr(e, 'reason', '')}".strip())


if __name__ == "__main__":
    main()
