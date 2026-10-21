"""Second-pass address lookup with OpenStreetMap (Nominatim) for addresses the Census
geocoder could not match. Run geocode_census.py first.

Follows the Nominatim usage policy for small one-time jobs: one request at a time, at most one
per second, an identifying User-Agent, and every answer cached in data/geocode/osm_cache.jsonl
(keyed by the address itself). A re-run skips addresses already answered and retries lookups that
failed because of a network error. Only house-level matches inside the same ZIP code or city are
kept; anything vaguer stays at the ZIP-code center.

Takes about 4 hours for ~9,000 addresses. Safe to stop and re-run.

usage: python scripts/geocode_osm.py
"""
import json
import re
import time
import urllib.parse
import urllib.request

from facilities import ROOT
from geocode_census import current_addresses, load_cache

CACHE = ROOT / "data/geocode/osm_cache.jsonl"
UA = "FloridaCareMap/0.1 (+https://github.com/Kes30033/Florida-Care-Map-Test-)"
SUITE = re.compile(r"\s*(,|\b(STE|SUITE|UNIT|APT|BLDG|BUILDING|RM|ROOM|FL|FLOOR|LOT|SPC|SPACE|OFC|OFFICE)\b\.?|#).*$")


def load_cache_osm():
    """(street, city, zip) -> {"ok": bool, "lat": ..., "lon": ...}; later lines win."""
    cache = {}
    if CACHE.exists():
        with open(CACHE, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                cache[tuple(r["key"])] = r
    return cache


def lookup(street, city, zip5):
    params = {"street": SUITE.sub("", street).strip(), "city": city, "state": "FL", "countrycodes": "us",
              "format": "jsonv2", "addressdetails": 1, "limit": 3}
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                return json.load(r)
        except Exception:
            time.sleep(5 * (attempt + 1))
    return None


def best_match(results, city, zip5):
    for res in results:
        a = res.get("address", {})
        same_place = (a.get("postcode", "")[:5] == zip5 or
                      city.lower() in {(a.get(k) or "").lower() for k in ("city", "town", "village", "hamlet", "suburb")})
        if a.get("house_number") and same_place:
            return {"lat": float(res["lat"]), "lon": float(res["lon"])}
    return None


def main():
    census = load_cache()
    cache = load_cache_osm()
    unmatched = [k for k in current_addresses() if census.get(k, {}).get("status") != "Match"]
    todo = [k for k in unmatched if not cache.get(k, {}).get("ok")]
    print(f"{len(unmatched)} addresses without a Census match, {len(todo)} still to look up", flush=True)
    failed = 0
    last = 0.0
    with open(CACHE, "a", encoding="utf-8") as out:
        for n, key in enumerate(todo, 1):
            wait = 1.1 - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.time()
            results = lookup(*key)
            failed += results is None
            hit = best_match(results or [], key[1], key[2])
            out.write(json.dumps({"key": list(key), "ok": results is not None, **(hit or {})}) + "\n")
            out.flush()
            if n % 250 == 0:
                print(f"{n}/{len(todo)} looked up", flush=True)
    print(f"FINISHED ({failed} lookups failed; run again later to retry them)" if failed else "FINISHED", flush=True)


if __name__ == "__main__":
    main()
