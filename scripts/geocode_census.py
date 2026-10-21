"""Look up map positions for Florida practice addresses with the U.S. Census batch geocoder
(free, no key, up to 10,000 addresses per request).

Answers are kept in data/geocode/census_cache.csv, keyed by the address itself, so a re-run (or a
run after a fresh registry download) only looks up addresses that aren't in the cache yet.

usage: python scripts/geocode_census.py
"""
import csv
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

from facilities import ROOT, address_key, location, raw_records

GEO = ROOT / "data/geocode"
CACHE = GEO / "census_cache.csv"
TMP = GEO / "census_tmp"
BATCH = 9500
URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
FIELDS = ["street", "city", "zip", "status", "lat", "lon"]


def load_cache():
    """(street, city, zip) -> {"status": Match | No_Match | Tie, "lat": float | None, "lon": float | None}"""
    cache = {}
    if CACHE.exists():
        with open(CACHE, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                cache[r["street"], r["city"], r["zip"]] = {
                    "status": r["status"],
                    "lat": float(r["lat"]) if r["lat"] else None,
                    "lon": float(r["lon"]) if r["lon"] else None,
                }
    return cache


def save_cache(cache):
    tmp = CACHE.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for (street, city, z), v in sorted(cache.items()):
            w.writerow([street, city, z, v["status"], v["lat"] or "", v["lon"] or ""])
    tmp.replace(CACHE)


def current_addresses():
    keys = {}
    for r in raw_records():
        loc = location(r)
        if loc:
            keys.setdefault(address_key(loc), None)
    return list(keys)


def lines(path):
    with open(path, encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def run(batch):
    out = batch.with_suffix(".csv.out")
    for attempt in range(4):
        subprocess.run(["curl", "-sS", "-m", "1800", "-F", f"addressFile=@{batch}", "-F",
                        "benchmark=Public_AR_Current", URL, "-o", str(out)], check=False)
        if out.exists() and lines(out) == lines(batch):
            return out
    print(f"{batch.name}: no complete answer after 4 tries; re-run the script to retry it")
    return None


def parse(out):
    """Census batch output -> {row id: (status, lat, lon)}"""
    answers = {}
    with open(out, newline="", encoding="utf-8") as fh:
        for rec in csv.reader(fh):
            if len(rec) < 3 or rec[2] not in ("Match", "No_Match", "Tie"):
                continue  # header or error row: leave it out so it is retried next time
            lat = lon = None
            if rec[2] == "Match" and len(rec) >= 6 and rec[5]:
                lon, lat = map(float, rec[5].split(","))
            answers[int(rec[0])] = (rec[2], lat, lon)
    return answers


def main():
    cache = load_cache()
    todo = [k for k in current_addresses() if k not in cache]
    print(f"{len(cache)} addresses already looked up, {len(todo)} new")
    if not todo:
        return
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    batches = []
    for b in range(0, len(todo), BATCH):
        path = TMP / f"batch_{b // BATCH:03d}.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            for i in range(b, min(b + BATCH, len(todo))):
                street, city, z = todo[i]
                w.writerow([i, street, city, "FL", z])
        batches.append(path)
    with ThreadPoolExecutor(4) as ex:
        for out in ex.map(run, batches):
            if out:
                for i, (status, lat, lon) in parse(out).items():
                    cache[todo[i]] = {"status": status, "lat": lat, "lon": lon}
                save_cache(cache)   # after every batch, so an interrupted run keeps what's done
    shutil.rmtree(TMP, ignore_errors=True)
    matched = sum(1 for k in todo if cache.get(k, {}).get("status") == "Match")
    print(f"looked up {len(todo)}: {matched} matched exactly")


if __name__ == "__main__":
    main()
