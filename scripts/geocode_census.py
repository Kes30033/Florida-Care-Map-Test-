"""Look up map positions for every unique Florida practice address with the U.S. Census
batch geocoder (free, no key, up to 10,000 addresses per request).

Writes data/geocode/addresses.json (the unique address list) and
data/geocode/census/batch_NNN.csv(.out). Batches that already have a complete .out file
are skipped, so the script can be re-run after an interruption.

usage: python scripts/geocode_census.py
"""
import csv
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

from facilities import ROOT, address_key, location, raw_records

GEO = ROOT / "data/geocode"
BATCH = 9500
URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"


def lines(path):
    with open(path) as fh:
        return sum(1 for _ in fh)


def run(batch):
    out = batch.with_suffix(".csv.out")
    if out.exists() and lines(out) == lines(batch):
        return f"{batch.name}: already done"
    for attempt in range(4):
        subprocess.run(["curl", "-sS", "-m", "1800", "-F", f"addressFile=@{batch}", "-F",
                        "benchmark=Public_AR_Current", URL, "-o", str(out)], check=False)
        if out.exists() and lines(out) == lines(batch):
            return f"{batch.name}: {lines(out)} answers"
    return f"{batch.name}: FAILED after 4 tries; re-run the script to retry"


def main():
    keys = {}
    for r in raw_records():
        loc = location(r)
        if loc:
            keys.setdefault(address_key(loc), len(keys))
    addresses = [list(k) for k in keys]
    (GEO / "census").mkdir(parents=True, exist_ok=True)
    old = GEO / "addresses.json"
    if old.exists() and json.loads(old.read_text()) != addresses:
        # Address list changed (new download): old batch answers no longer line up
        for f in (GEO / "census").glob("batch_*"):
            f.unlink()
    old.write_text(json.dumps(addresses))
    print(f"{len(addresses)} unique addresses")

    batches = []
    for b in range(0, len(addresses), BATCH):
        path = GEO / "census" / f"batch_{b // BATCH:03d}.csv"
        if not path.exists():
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                for i in range(b, min(b + BATCH, len(addresses))):
                    w.writerow([i, *addresses[i][:2], "FL", addresses[i][2]])
        batches.append(path)
    with ThreadPoolExecutor(4) as ex:
        for msg in ex.map(run, batches):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
