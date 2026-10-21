# Florida Care Map

An interactive map and spreadsheet of every healthcare organization registered in Florida:
hospitals, rehab centers, clinics, doctor's offices, surgery centers, nursing homes and more,
about 175,000 places in all.

- **Website:** https://kes30033.github.io/Florida-Care-Map-Test-/
- **Spreadsheet:** [data/Florida_Medical_Facilities.xlsx](data/Florida_Medical_Facilities.xlsx) (click it, then "Download raw file")

## What you can do on the website

- Search by **ZIP code** or **city**, or scroll and zoom around the map.
- Switch between **Streets**, **Satellite** and **Simple** map styles (top-left of the map).
- Filter by **type of place** and by **specialty tags**: spine & scoliosis, orthopedics, surgery,
  rehab & therapy, children, mental health. Tags come from each place's registered specialties and
  from words in its name, so call to confirm a service.
- Click any place for its type, registered specialties, address, phone number, a Google Maps link
  and its official government record.

## Where the data comes from

| What | Source |
|---|---|
| Places, types, specialties, addresses, phones | [NPI Registry](https://npiregistry.cms.hhs.gov/) (U.S. Centers for Medicare & Medicaid Services). Every healthcare organization that bills insurance must register. Downloaded on the date in `data/raw/DOWNLOADED_ON`. |
| Specialty names | [NUCC Health Care Provider Taxonomy](https://www.nucc.org/), version 26.1 |
| Map positions | [U.S. Census Bureau geocoder](https://geocoding.geo.census.gov/), then [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/) for addresses the Census couldn't match |
| Counties, highways (Simple map) | U.S. Census Bureau cartographic boundary and TIGER files |
| Street and satellite maps | Esri World Street Map and World Imagery |

### Things to know

- **Registrations are self-reported.** Some are out of date, a few places may have closed, and
  some types look odd (organizations pick their own). Call ahead to confirm services.
- **Scoliosis isn't tracked by name** in official records. A place is marked "Spine & scoliosis" if
  its name mentions scoliosis or spine, it registered as spine surgery, neurosurgery, pediatric
  orthopedics or spinal cord injury medicine, or it makes or fits braces. Each place's page says why.
- **Big hospital systems register many departments separately**, so one hospital can appear several times.
- **Only the main practice address is shown**, even if a place has other locations.
- **Solo doctors** registered only as individuals (not as a business) aren't included.
- **Map positions:** most places sit at their exact street address. Places whose address couldn't
  be matched sit at the center of their ZIP code, and their page says so.
- **Map images:** Esri's free map images are fine for a test site. For heavy public use, create a
  free [ArcGIS Location Platform](https://location.arcgis.com/) account and follow Esri's terms.

## What's in this repository

```
docs/                     the website (published by GitHub Pages)
data/
  Florida_Medical_Facilities.xlsx   the spreadsheet
  raw/fl_orgs.jsonl.gz      raw registry download (compressed)
  reference/                specialty code list
  geocode/                  map-position lookups, saved by address (census_cache.csv, osm_cache.jsonl)
  basemap/basemap.json      counties, highways and ZIP centers for the Simple map
scripts/                  the steps that build everything (below)
site/index.template.html  the website's page, before data is added
```

## Updating the data

Needs Python 3.10+ and `pip install -r requirements.txt`. Run from the repository folder:

```
python scripts/download_registry.py   # ~30 min: fresh download from the NPI Registry
python scripts/build_spreadsheet.py   # ~1 min: rebuilds the spreadsheet
python scripts/geocode_census.py      # map positions for new addresses (~20 min the first time, minutes after)
python scripts/geocode_osm.py         # second try for addresses Census couldn't match (~2.5 h the first time)
python scripts/make_basemap.py        # ~10 s: counties and highways (only needed once)
python scripts/build_site.py          # ~1 min: rebuilds the website in docs/
```

Both address lookups remember every answer by address, so after a fresh download they only look up
addresses that are new. Then commit and push; GitHub Pages republishes the website within a few minutes.
The Claude-hosted copy of the map is built with `python scripts/build_site.py --artifact <folder>`.
