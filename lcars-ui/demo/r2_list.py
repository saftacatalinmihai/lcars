#!/usr/bin/env python3
"""List the objects under a prefix of an R2 bucket, read-only, from
Cloudflare's API (docs/design/demo-static.md, "Upload").

    python3 lcars-ui/demo/r2_list.py [--bucket test] [--prefix lcars-demo/] [--out FILE]

Prints (or writes to FILE) JSON {key: {"etag": ..., "size": ...}}. The
etag of a single-part put is the MD5 of its bytes, which is how r2_sync.py
tells a changed file from an unchanged one. Wrangler 3 (what Node 20 runs)
has no list command, hence the API.

The credentials come from the environment only, CLOUDFLARE_API_TOKEN and
CLOUDFLARE_ACCOUNT_ID (source ~/.env into the command's environment:
set -a; . ~/.env; set +a), and are never printed: an error names the
variable that is missing, never its value.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

BUCKET = "test"
PREFIX = "lcars-demo/"
API = "https://api.cloudflare.com/client/v4/accounts/{acct}/r2/buckets/{bucket}/objects"


def creds():
    missing = [v for v in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID") if not os.environ.get(v)]
    if missing:
        sys.exit("r2: not in the environment: " + ", ".join(missing))
    return os.environ["CLOUDFLARE_ACCOUNT_ID"], os.environ["CLOUDFLARE_API_TOKEN"]


def list_objects(bucket=BUCKET, prefix=PREFIX):
    """{key: {"etag", "size"}} for every object under prefix, following the
    cursor: a page holds at most 1000."""
    acct, tok = creds()
    out, cursor = {}, None
    while True:
        q = {"prefix": prefix, "per_page": 1000}
        if cursor:
            q["cursor"] = cursor
        url = API.format(acct=acct, bucket=bucket) + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
        with urllib.request.urlopen(req, timeout=60) as r:
            page = json.load(r)
        if not page.get("success", True):
            sys.exit(f"r2: listing {bucket}/{prefix} failed: {page.get('errors')}")
        for o in page["result"]:
            out[o["key"]] = {"etag": o.get("etag", "").strip('"'), "size": o.get("size")}
        info = page.get("result_info") or {}
        cursor = info.get("cursor")
        if not info.get("is_truncated") or not cursor:
            return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--prefix", default=PREFIX)
    ap.add_argument("--out", help="write the JSON here instead of stdout")
    a = ap.parse_args()
    objs = list_objects(a.bucket, a.prefix)
    text = json.dumps(objs, indent=0, sort_keys=True) + "\n"
    if a.out:
        open(a.out, "w").write(text)
        print(f"{len(objs)} objects under {a.bucket}/{a.prefix} -> {a.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
