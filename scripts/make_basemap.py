"""Build the hand-drawn map layers (Florida counties, neighboring states, highways, ZIP centers)
from U.S. Census Bureau boundary files. Used by the "Simple" map style and for county labels.

Downloads the source shapefiles into data/basemap/source/ (not saved to git) on first run and
writes data/basemap/basemap.json.

usage: python scripts/make_basemap.py
"""
import io
import json
import urllib.request
import zipfile

import shapefile
import zipcodes
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

from facilities import ROOT

OUT = ROOT / "data/basemap"
SRC = OUT / "source"
FILES = {
    "counties": "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip",
    "states": "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip",
    "roads": "https://www2.census.gov/geo/tiger/TIGER2023/PRISECROADS/tl_2023_12_prisecroads.zip",
}
BBOX = box(-88.2, 24.3, -79.8, 31.3)


def fetch(name):
    path = SRC / FILES[name].rsplit("/", 1)[1]
    if not path.exists():
        SRC.mkdir(parents=True, exist_ok=True)
        print("downloading", path.name)
        urllib.request.urlretrieve(FILES[name], path)
    return path


def read(name):
    z = zipfile.ZipFile(fetch(name))
    base = [n[:-4] for n in z.namelist() if n.endswith(".shp")][0]
    r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")),
                         shx=io.BytesIO(z.read(base + ".shx")))
    fields = [f[0] for f in r.fields[1:]]
    for sr in r.iterShapeRecords():
        yield dict(zip(fields, sr.record)), shape(sr.shape.__geo_interface__)


def rnd(g, p=4):
    def fix(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], p), round(c[1], p)]
        return [fix(x) for x in c]
    m = mapping(g)
    return {"type": m["type"], "coordinates": fix(m["coordinates"])}


def label_point(g):
    part = max(g.geoms, key=lambda x: x.area) if g.geom_type == "MultiPolygon" else g
    p = part.representative_point()
    return [round(p.y, 3), round(p.x, 3)]


def main():
    counties = []
    for rec, g in read("counties"):
        if rec["STATEFP"] == "12":
            counties.append({"type": "Feature",
                             "properties": {"name": rec["NAME"] + " County", "lp": label_point(g)},
                             "geometry": rnd(g.simplify(0.0015, preserve_topology=True))})
    neighbors = []
    for rec, g in read("states"):
        if rec["STUSPS"] in ("GA", "AL"):
            s = g.intersection(BBOX).simplify(0.003, preserve_topology=True)
            if not s.is_empty:
                neighbors.append({"type": "Feature", "properties": {"name": rec["NAME"]}, "geometry": rnd(s)})
    roads = {}
    for rec, g in read("roads"):
        kind = ("primary" if rec["MTFCC"] == "S1100" else "us" if rec["RTTYP"] == "U"
                else "state" if rec["MTFCC"] == "S1200" else None)
        if kind:
            roads.setdefault((rec["FULLNAME"] or "", kind), []).append(g)
    road_feats = [{"type": "Feature", "properties": {"name": name, "kind": kind},
                   "geometry": rnd(unary_union(gs).simplify(0.0008 if kind == "state" else 0.0012))}
                  for (name, kind), gs in roads.items()]
    zips = {z["zip_code"]: [round(float(z["lat"]), 4), round(float(z["long"]), 4)]
            for z in zipcodes.filter_by(state="FL") if z["lat"]}
    out = {"counties": counties, "neighbors": neighbors, "roads": road_feats, "zips": zips}
    (OUT / "basemap.json").write_text(json.dumps(out, separators=(",", ":")))
    print(len(counties), "counties,", len(road_feats), "roads,", len(zips), "ZIP codes")


if __name__ == "__main__":
    main()
