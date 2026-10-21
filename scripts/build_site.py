"""Build the Florida Care Map website from the registry data and the address lookups.

  python scripts/build_site.py                      -> docs/  (GitHub Pages: street + satellite maps)
  python scripts/build_site.py --artifact <dir>     -> <dir>  (Claude artifact: hand-drawn map only,
                                                              because outside map images are blocked there)

Output:
  index.html          the page
  data/points.json    every place: position, category, flags, ZIP, city (loaded on open)
  data/d/<zip3>.json  names, addresses, phones... per 3-digit ZIP prefix (loaded on demand)
  data/basemap.json   counties, highways, city labels, ZIP centers
"""
import argparse
import csv
import json
import shutil
import statistics
from collections import defaultdict

from facilities import ROOT, load_rows

GEO = ROOT / "data/geocode"
SITE = ROOT / "site"

CATEGORY_ORDER = [
    # group 0: hospitals & emergency
    "Hospital", "Urgent & Emergency Care", "Surgery Center",
    # group 1: rehab, therapy & spine
    "Rehabilitation Center", "Physical, Occupational & Speech Therapy", "Chiropractic",
    "Orthotics & Prosthetics (Braces)",
    # group 2: doctors & clinics
    "Doctor's Office / Medical Group", "Clinic / Outpatient Center", "Dental", "Eye Care", "Dialysis Center",
    "Imaging & Lab",
    # group 3: other care & services
    "Mental Health & Addiction", "Nursing Home & Long-Term Care", "Home Health & Hospice",
    "Pharmacy", "Medical Equipment & Supplies", "Ambulance & Medical Transport", "Insurance & Managed Care",
    "Other Health Services",
]
GROUP_OF = {c: (0 if i < 3 else 1 if i < 7 else 2 if i < 13 else 3) for i, c in enumerate(CATEGORY_ORDER)}
FLAG_COLUMNS = ["Spine / Scoliosis Related", "Orthopedics", "Surgery", "Rehab / Physical Therapy",
                "Pediatric / Children", "Mental Health"]
APPROX, SCOLIOSIS_NAME, SPINE_SPECIALTY, SPINE_NAME, BRACES = 64, 128, 256, 512, 1024
FLORIDA = (24.3, 31.1, -87.7, -79.9)


def coordinates():
    """Address id -> (lat, lon) from the Census lookup, filled in by OpenStreetMap where Census had no match."""
    coords = {}
    for fn in sorted((GEO / "census").glob("batch_*.csv.out")):
        for rec in csv.reader(open(fn)):
            if len(rec) >= 6 and rec[2] == "Match" and rec[5]:
                lon, lat = map(float, rec[5].split(","))
                coords[int(rec[0])] = (lat, lon)
    census = len(coords)
    osm = GEO / "osm_cache.jsonl"
    if osm.exists():
        for line in open(osm):
            r = json.loads(line)
            if "lat" in r and r["id"] not in coords:
                coords[r["id"]] = (r["lat"], r["lon"])
    print(f"exact positions: {census} from Census, {len(coords) - census} from OpenStreetMap")
    return coords


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", metavar="DIR", help="build the Claude artifact version into DIR")
    args = ap.parse_args()
    out_dir = ROOT / "docs" if not args.artifact else __import__("pathlib").Path(args.artifact)
    data_dir = out_dir / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    (data_dir / "d").mkdir(parents=True)

    addresses = json.loads((GEO / "addresses.json").read_text())
    addr_id = {tuple(a): i for i, a in enumerate(addresses)}
    coords = coordinates()
    base = json.loads((ROOT / "data/basemap/basemap.json").read_text())
    zip_center = {z: tuple(ll) for z, ll in base["zips"].items()}

    types, specs, cities, counties = {}, {}, {}, {}

    def intern(d, v):
        if v not in d:
            d[v] = len(d)
        return d[v]

    cat_idx = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    places, approx, dropped = [], 0, 0
    for row in load_rows():
        ll = coords.get(addr_id.get(row["_key"], -1))
        is_approx = ll is None
        if is_approx:
            ll = zip_center.get(row["ZIP"])
        if not ll or not (FLORIDA[0] < ll[0] < FLORIDA[1] and FLORIDA[2] < ll[1] < FLORIDA[3]):
            dropped += 1
            continue
        approx += is_approx
        why = row["Why Spine-Flagged"]
        f = sum(1 << b for b, col in enumerate(FLAG_COLUMNS) if row[col])
        f |= (APPROX if is_approx else 0) | (SCOLIOSIS_NAME if "scoliosis" in why else 0) \
            | (SPINE_SPECIALTY if "Spine / neuro" in why else 0) | (SPINE_NAME if "Name mentions spine" in why else 0) \
            | (BRACES if "braces" in why else 0)
        places.append({
            "y": round((ll[0] - 24) * 1e5), "x": round((-ll[1] - 79) * 1e5),
            "c": cat_idx[row["Category"]], "f": f, "z": int(row["ZIP"]), "t": intern(cities, row["City"]),
            "d": [row["Name"], row["Also Known As"], intern(types, row["Facility Type"]),
                  [intern(specs, s) for s in row["All Listed Specialties"].split("; ") if s],
                  row["Street Address"], row["Phone"], row["NPI Number"], intern(counties, row["County"]),
                  row["Record Last Updated"]],
        })
    print(f"{len(places)} places on the map, {approx} at their ZIP-code center, {dropped} left off (no usable position)")

    places.sort(key=lambda r: (r["z"], r["d"][0]))
    groups = []  # [zip3, first index]
    for i, r in enumerate(places):
        if not groups or groups[-1][0] != r["z"] // 100:
            groups.append([r["z"] // 100, i])
    for gi, (z3, start) in enumerate(groups):
        end = groups[gi + 1][1] if gi + 1 < len(groups) else len(places)
        (data_dir / "d" / f"{z3}.json").write_text(json.dumps([r["d"] for r in places[start:end]], separators=(",", ":")))

    inv = lambda d: [k for k, _ in sorted(d.items(), key=lambda kv: kv[1])]
    points = {
        "updated": (ROOT / "data/raw/DOWNLOADED_ON").read_text().strip(),
        "categories": CATEGORY_ORDER, "groupOf": [GROUP_OF[c] for c in CATEGORY_ORDER],
        "types": inv(types), "specialties": inv(specs), "cities": inv(cities), "counties": inv(counties),
        "zip3": groups,
        **{k: [r[k] for r in places] for k in ("y", "x", "c", "f", "z", "t")},
    }
    (data_dir / "points.json").write_text(json.dumps(points, separators=(",", ":")))

    # City labels for the hand-drawn map: median position of each city's exactly placed places
    by_city = defaultdict(list)
    for r in places:
        if not r["f"] & APPROX:
            by_city[r["t"]].append((r["y"], r["x"]))
    names = inv(cities)
    labels = []
    for t, pts in by_city.items():
        if len(pts) >= 15:
            labels.append([names[t], round(statistics.median(p[0] for p in pts) / 1e5 + 24, 4),
                           round(-(statistics.median(p[1] for p in pts) / 1e5 + 79), 4), len(pts)])
    labels.sort(key=lambda l: -l[3])
    base["cities"] = labels
    (data_dir / "basemap.json").write_text(json.dumps(base, separators=(",", ":")))

    page = (SITE / "index.template.html").read_text()
    if args.artifact:
        # Claude artifacts wrap the page in their own <html> skeleton and only allow scripts from CDNs
        css = (SITE / "vendor/leaflet-1.9.4.css").read_text()
        page = page.replace("<!--LEAFLET_CSS-->", f"<style>\n{css}\n</style>").replace("/*TILES*/true", "false")
    else:
        page = ('<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                '<meta name="description" content="Interactive map of every registered healthcare place in Florida, '
                'searchable by ZIP code or city.">\n'
                + page.replace("<!--LEAFLET_CSS-->", '<link rel="stylesheet" '
                               'href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css">'))
    (out_dir / "index.html").write_text(page)
    size = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
    print(f"wrote {out_dir} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
