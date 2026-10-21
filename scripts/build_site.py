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
import datetime
import json
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from facilities import CITY_WORDS, ROOT, load_rows
from geocode_census import load_cache
from geocode_osm import load_cache_osm

SITE = ROOT / "site"

CATEGORY_ORDER = [
    # group 0: hospitals & emergency
    "Hospital", "Urgent & Emergency Care", "Surgery Center",
    # group 1: rehab, therapy & braces
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


def in_florida(ll):
    return bool(ll) and FLORIDA[0] < ll[0] < FLORIDA[1] and FLORIDA[2] < ll[1] < FLORIDA[3]


def coordinates():
    """Address key -> (lat, lon): the Census match, or an OpenStreetMap house-level match where Census had none."""
    coords = {k: (v["lat"], v["lon"]) for k, v in load_cache().items() if v["status"] == "Match"}
    census = len(coords)
    for k, v in load_cache_osm().items():
        if "lat" in v and k not in coords:
            coords[k] = (v["lat"], v["lon"])
    print(f"exact positions: {census} from Census, {len(coords) - census} from OpenStreetMap")
    return coords


def output_dir(args):
    if not args.artifact:
        return ROOT / "docs"
    out = Path(args.artifact).resolve()
    if out == ROOT or out in ROOT.parents or ROOT in out.parents:
        sys.exit("Choose a folder outside the project for --artifact")
    data = out / "data"
    if data.exists() and {p.name for p in data.iterdir()} - {"points.json", "basemap.json", "d"}:
        sys.exit(f"{data} has files this script didn't make; refusing to replace it")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", metavar="DIR", help="build the Claude artifact version into DIR")
    args = ap.parse_args()
    out_dir = output_dir(args)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Build into a fresh folder and swap it in at the end, so a failed build leaves the old site intact
    new_data = out_dir / "data.new"
    shutil.rmtree(new_data, ignore_errors=True)
    (new_data / "d").mkdir(parents=True)

    coords = coordinates()
    base = json.loads((ROOT / "data/basemap/basemap.json").read_text(encoding="utf-8"))
    zip_center = {z: tuple(ll) for z, ll in base["zips"].items()}
    rows = load_rows()

    # Fallback for places whose ZIP code isn't a known Florida ZIP: the middle of their city
    by_city_exact = defaultdict(list)
    for row in rows:
        if row["_key"] in coords:
            by_city_exact[row["City"]].append(coords[row["_key"]])
    city_center = {c: (statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts))
                   for c, pts in by_city_exact.items()}

    types, specs, cities, counties = {}, {}, {}, {}

    def intern(d, v):
        if v not in d:
            d[v] = len(d)
        return d[v]

    cat_idx = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    places, approx, dropped = [], 0, []
    for row in rows:
        ll = coords.get(row["_key"])
        is_approx = not in_florida(ll)
        if is_approx:
            ll = zip_center.get(row["ZIP"]) or city_center.get(row["City"])
        if not in_florida(ll):
            dropped.append(f'{row["Name"]} ({row["Street Address"]}, {row["City"]} {row["ZIP"]})')
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
    print(f"{len(places)} places on the map, {approx} at their ZIP-code (or city) center")
    if dropped:
        print(f"{len(dropped)} left off the map (no usable position):\n  " + "\n  ".join(dropped))

    places.sort(key=lambda r: (r["z"], r["d"][0]))
    groups = []  # [zip3, first index]
    for i, r in enumerate(places):
        if not groups or groups[-1][0] != r["z"] // 100:
            groups.append([r["z"] // 100, i])
    for gi, (z3, start) in enumerate(groups):
        end = groups[gi + 1][1] if gi + 1 < len(groups) else len(places)
        (new_data / "d" / f"{z3}.json").write_text(
            json.dumps([r["d"] for r in places[start:end]], separators=(",", ":")), encoding="utf-8")

    updated = (ROOT / "data/raw/DOWNLOADED_ON").read_text(encoding="utf-8").strip()
    inv = lambda d: [k for k, _ in sorted(d.items(), key=lambda kv: kv[1])]
    points = {
        "updated": updated,
        "categories": CATEGORY_ORDER, "groupOf": [GROUP_OF[c] for c in CATEGORY_ORDER],
        "types": inv(types), "specialties": inv(specs), "cities": inv(cities), "counties": inv(counties),
        "zip3": groups,
        **{k: [r[k] for r in places] for k in ("y", "x", "c", "f", "z", "t")},
    }
    (new_data / "points.json").write_text(json.dumps(points, separators=(",", ":")), encoding="utf-8")

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
    (new_data / "basemap.json").write_text(json.dumps(base, separators=(",", ":")), encoding="utf-8")

    page = (SITE / "index.template.html").read_text(encoding="utf-8")
    d = datetime.date.fromisoformat(updated)
    page = page.replace("<!--UPDATED-->", f"{d:%b} {d.day}, {d.year}")
    page = page.replace("/*CITY_WORDS*/{}", json.dumps(CITY_WORDS, sort_keys=True))
    if args.artifact:
        # Claude artifacts wrap the page in their own <html> skeleton and only allow scripts from CDNs
        css = (SITE / "vendor/leaflet-1.9.4.css").read_text(encoding="utf-8")
        page = page.replace("<!--LEAFLET_CSS-->", f"<style>\n{css}\n</style>").replace("/*TILES*/true", "false")
    else:
        page = ('<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                '<meta name="description" content="Interactive map of every registered healthcare place in Florida, '
                'searchable by ZIP code or city.">\n'
                + page.replace("<!--LEAFLET_CSS-->", '<link rel="stylesheet" '
                               'href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css">'))

    # Swap in the new build: move the old data aside first, so nothing is deleted until the new data is in place
    old_data, data = out_dir / "data.old", out_dir / "data"
    shutil.rmtree(old_data, ignore_errors=True)
    if data.exists():
        data.rename(old_data)
    new_data.rename(data)
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    shutil.rmtree(old_data)
    size = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
    print(f"wrote {out_dir} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
