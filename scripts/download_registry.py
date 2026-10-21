"""Download every Florida healthcare organization (NPI-2) from the NPI Registry API
into data/raw/fl_orgs.jsonl.gz. Takes about 30 minutes.

The API returns at most 1,200 rows per query (limit 200, skip <= 1000), so we
partition by ZIP prefix and recurse into longer prefixes when a query saturates.

usage: python scripts/download_registry.py
"""
import datetime
import gzip
import json
import sys
import itertools
import string
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://npiregistry.cms.hhs.gov/api/"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/raw/fl_orgs.jsonl.gz"
results = {}
saturated_zips = []


def fetch(params):
    q = {"version": "2.1", "state": "FL", "enumeration_type": "NPI-2",
         "address_purpose": "LOCATION", "limit": 200, **params}
    url = API + "?" + urllib.parse.urlencode(q)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                d = json.load(r)
            if "Errors" in d:
                raise RuntimeError(d["Errors"])
            return d.get("results", [])
        except Exception as e:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)


def pull(params):
    """Return (rows, saturated) for one partition."""
    rows = []
    for skip in range(0, 1001, 200):
        page = fetch({**params, "skip": skip})
        rows.extend(page)
        if len(page) < 200:
            return rows, False
    return rows, True


def crawl_prefix(prefix):
    # postal_code wildcard needs >= 2 chars; 5 digits is an exact ZIP match
    params = {"postal_code": prefix if len(prefix) == 5 else prefix + "*"}
    rows, sat = pull(params)
    if not sat:
        return rows
    if len(prefix) < 5:
        out = []
        for d in "0123456789":
            out.extend(crawl_prefix(prefix + d))
        return out
    # Saturated single ZIP: split by organization name prefix
    saturated_zips.append(prefix)
    out = list(rows)
    chars = string.ascii_uppercase + string.digits
    for a, b in itertools.product(chars, chars):
        r, s = pull({**params, "organization_name": a + b + "*"})
        if s:
            print("STILL SATURATED", prefix, a + b, file=sys.stderr)
        out.extend(r)
    return out


def main():
    prefixes = [f"3{d}{e}" for d in "234" for e in "0123456789"]
    with ThreadPoolExecutor(6) as ex:
        for p, rows in zip(prefixes, ex.map(crawl_prefix, prefixes)):
            for r in rows:
                results[r["number"]] = r
            print(p, len(rows), "total", len(results), file=sys.stderr, flush=True)
    with gzip.open(OUT, "wt") as f:
        for r in results.values():
            f.write(json.dumps(r) + "\n")
    (ROOT / "data/raw/DOWNLOADED_ON").write_text(datetime.date.today().isoformat() + "\n")
    print("saturated zips:", saturated_zips, file=sys.stderr)
    print("DONE", len(results), file=sys.stderr)


main()
