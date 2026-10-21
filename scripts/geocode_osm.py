"""Second-pass address lookup with OpenStreetMap (Nominatim) for addresses the Census
geocoder could not match.

Follows the Nominatim usage policy for small one-time jobs: one request at a time,
at most one per second, an identifying User-Agent, and every answer cached so a
re-run never repeats a request. Only house-level matches inside the same ZIP code
or city are kept; anything vaguer stays at the ZIP-code center.

Run geocode_census.py first. Takes about 2.5 hours for ~9,000 addresses; safe to stop and re-run.

usage: python scripts/geocode_osm.py
"""
import csv
import glob
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

GEO = Path(__file__).resolve().parent.parent / "data/geocode"
batch_dir, addresses_path, cache_path = (sys.argv[1:4] if len(sys.argv) > 3 else
                                         (GEO / "census", GEO / "addresses.json", GEO / "osm_cache.jsonl"))
UA = "FloridaCareMap/0.1 (+https://github.com/Kes30033/Florida-Care-Map-Test-)"
SUITE = re.compile(r"\s*(,|\b(STE|SUITE|UNIT|APT|BLDG|BUILDING|RM|ROOM|FL|FLOOR|LOT|SPC|SPACE|OFC|OFFICE)\b\.?|#).*$")

addresses = json.load(open(addresses_path))
unmatched = []
for fn in sorted(glob.glob(f"{batch_dir}/batch_*.csv.out")):
    for rec in csv.reader(open(fn)):
        if len(rec) > 2 and rec[2] != "Match":
            unmatched.append(int(rec[0]))
unmatched.sort()

done = set()
try:
    for line in open(cache_path):
        done.add(json.loads(line)["id"])
except FileNotFoundError:
    pass
todo = [i for i in unmatched if i not in done]
print(f"{len(unmatched)} unmatched, {len(done)} cached, {len(todo)} to look up", flush=True)

out = open(cache_path, "a")
last = 0.0
for n, i in enumerate(todo, 1):
    street, city, zip5 = addresses[i]
    street = SUITE.sub("", street).strip()
    params = {"street": street, "city": city, "state": "FL", "countrycodes": "us",
              "format": "jsonv2", "addressdetails": 1, "limit": 3}
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
    wait = 1.1 - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    results = None
    for attempt in range(4):
        try:
            last = time.time()
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                results = json.load(r)
            break
        except Exception as e:
            time.sleep(5 * (attempt + 1))
    hit = None
    for res in results or []:
        a = res.get("address", {})
        same_place = (a.get("postcode", "")[:5] == zip5 or
                      city.lower() in {(a.get(k) or "").lower() for k in ("city", "town", "village", "hamlet", "suburb")})
        if a.get("house_number") and same_place:
            hit = {"lat": float(res["lat"]), "lon": float(res["lon"])}
            break
    out.write(json.dumps({"id": i, "ok": results is not None, **(hit or {})}) + "\n")
    out.flush()
    if n % 250 == 0:
        print(f"{n}/{len(todo)} looked up", flush=True)
print("FINISHED", flush=True)
