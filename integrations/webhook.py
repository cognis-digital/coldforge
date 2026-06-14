#!/usr/bin/env python3
"""Minimal, dependency-free webhook forwarder for Cognis findings.

Reads JSON findings on stdin and POSTs them to a URL (SIEM/Slack/Jira bridge).
Usage:  <tool> scan . --format json | python integrations/webhook.py --url URL
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Webhook URL to POST to")
    ap.add_argument("--header", action="append", default=[], help="Key: Value")
    args = ap.parse_args()

    if not args.url.startswith(("http://", "https://")):
        print(
            f"error: --url must start with http:// or https://, got: {args.url!r}",
            file=sys.stderr,
        )
        return 1

    raw = sys.stdin.read()
    if not raw.strip():
        print("error: no input on stdin — pipe JSON findings", file=sys.stderr)
        return 1
    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: stdin is not valid JSON: {exc}", file=sys.stderr)
        return 1

    payload = raw.encode("utf-8")
    req = urllib.request.Request(args.url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    for h in args.header:
        if ":" not in h:
            print(
                f"error: --header value must be 'Key: Value', got: {h!r}",
                file=sys.stderr,
            )
            return 1
        k, _, v = h.partition(":")
        req.add_header(k.strip(), v.strip())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"posted {len(payload)} bytes -> {r.status}")
        return 0
    except Exception as e:
        print(f"webhook error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
