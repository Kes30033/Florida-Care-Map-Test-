"""Shared rules for turning raw NPI Registry records into categorized Florida facilities.

Both the spreadsheet (build_spreadsheet.py) and the website (build_site.py) use load_rows(),
so the two always agree on categories and specialty flags.
"""
import csv
import difflib
import gzip
import json
import re
from collections import Counter
from pathlib import Path

import zipcodes

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw/fl_orgs.jsonl.gz"
TAXONOMY = ROOT / "data/reference/nucc_taxonomy_261.csv"

tax = {r["Code"]: r for r in csv.DictReader(open(TAXONOMY, encoding="latin-1"))}  # NUCC publishes this file as Latin-1

# Categories that are businesses supporting care rather than places you go for care
OTHER_CATEGORIES = {"Pharmacy", "Medical Equipment & Supplies", "Ambulance & Medical Transport",
                    "Insurance & Managed Care", "Other Health Services"}


def category(code):
    t = tax.get(code, {})
    g, c = t.get("Grouping", ""), t.get("Classification", "")
    if code in ("283X00000X", "283XC2000X", "273Y00000X") or code.startswith("261QR04") and code != "261QR0405X":
        return "Rehabilitation Center"
    if code in ("222Z00000X", "224P00000X", "225000000X", "224L00000X", "335E00000X"):
        return "Orthotics & Prosthetics (Braces)"
    if g in ("Hospitals", "Hospital Units") or code == "261QC0050X":
        return "Mental Health & Addiction" if code in ("273R00000X", "276400000X") else "Hospital"
    if g == "Ambulatory Health Care Facilities":
        if code in ("261QA1903X", "261QS0132X", "261QS0112X", "261QE0800X", "261QL0400X"):
            return "Surgery Center"
        if code in ("261QU0200X", "261QE0002X"):
            return "Urgent & Emergency Care"
        if code == "261QE0700X":
            return "Dialysis Center"
        if code.startswith("261QR02") or code in ("261QM1200X", "261QS1200X"):
            return "Imaging & Lab"
        if code in ("261QM0855X", "261QM0850X", "261QM0801X", "261QM2800X", "261QR0405X"):
            return "Mental Health & Addiction"
        if code == "261QD0000X":
            return "Dental"
        if code in ("261QP2000X", "261QH0700X"):
            return "Physical, Occupational & Speech Therapy"
        return "Clinic / Outpatient Center"
    if g in ("Nursing & Custodial Care Facilities", "Respite Care Facility"):
        return "Home Health & Hospice" if code == "315D00000X" else "Nursing Home & Long-Term Care"
    if g == "Agencies":
        if code in ("251E00000X", "251F00000X", "251G00000X", "251J00000X", "253Z00000X", "251T00000X"):
            return "Home Health & Hospice"
        if code == "251S00000X":
            return "Mental Health & Addiction"
        if code == "251K00000X":
            return "Clinic / Outpatient Center"
        return "Other Health Services"
    if g in ("Nursing Service Providers", "Nursing Service Related Providers"):
        return "Home Health & Hospice"
    if g in ("Residential Treatment Facilities", "Behavioral Health & Social Service Providers"):
        return "Mental Health & Addiction"
    if g in ("Allopathic & Osteopathic Physicians", "Group", "Podiatric Medicine & Surgery Service Providers",
             "Physician Assistants & Advanced Practice Nursing Providers"):
        return "Doctor's Office / Medical Group"
    if g == "Dental Providers":
        return "Dental"
    if g in ("Respiratory, Developmental, Rehabilitative and Restorative Service Providers",
             "Speech, Language and Hearing Service Providers"):
        return "Physical, Occupational & Speech Therapy"
    if g == "Chiropractic Providers":
        return "Chiropractic"
    if g == "Eye and Vision Services Providers":
        return "Eye Care"
    if g == "Laboratories" or code == "335V00000X":
        return "Imaging & Lab"
    if c == "Pharmacy" or code in ("332100000X", "332800000X", "332000000X"):
        return "Pharmacy"
    if g == "Suppliers":
        return "Medical Equipment & Supplies"
    if g in ("Transportation Services", "Emergency Medical Service Providers"):
        return "Ambulance & Medical Transport"
    if g == "Managed Care Organizations":
        return "Insurance & Managed Care"
    return "Other Health Services"


def display(code, fallback=""):
    t = tax.get(code)
    if not t:
        return fallback
    return t["Display Name"] or (t["Classification"] + (f" - {t['Specialization']}" if t["Specialization"] else ""))


def has(pattern, text):
    return bool(re.search(pattern, text))


SPINE_CODES = {"207XS0117X", "207XP3100X", "207T00000X", "2081P0004X"}
BRACE_CODES = {"222Z00000X", "225000000X", "335E00000X"}  # orthotist, orthotic fitter, orthotic supplier


def flags(codes, cls_text, name, cat):
    ortho = any(c.startswith("207X") for c in codes) or bool(
        {"111NX0800X", "2251X0800X", "163WX0800X", "246ZX2200X"} & codes) or has(r"ORTHOP|ORTHOPAED|ORTHOPED", name)
    spine_why = []
    if "SCOLIOSIS" in name:
        spine_why.append("Name mentions scoliosis")
    if codes & SPINE_CODES:
        spine_why.append("Spine / neuro / pediatric orthopedic surgery or spinal cord injury specialty")
    if has(r"\bSPINE\b|\bSPINAL\b", name):
        spine_why.append("Name mentions spine")
    if codes & BRACE_CODES:
        spine_why.append("Makes or fits braces (orthotics)")
    surgery = ("SURGERY" in cls_text or "SURGICAL" in cls_text or cat == "Surgery Center"
               or bool({"282N00000X", "282NC2000X", "282NC0060X", "282NR1301X", "282NW0100X", "261QC0050X"} & codes)
               or has(r"SURG", name))
    rehab = (cat in ("Rehabilitation Center", "Physical, Occupational & Speech Therapy")
             or any(c.startswith(("2081", "2251", "225X", "261QR04")) for c in codes if c != "261QR0405X")
             or "111NR0400X" in codes or has(r"REHAB|PHYSICAL THERAP", name))
    peds = has(r"PEDIATRIC|CHILDREN|PEDIATRICS", cls_text) or has(r"PEDIATRIC|CHILDREN|\bKIDS?\b|\bCHILD\b", name)
    mental = cat == "Mental Health & Addiction" or has(r"PSYCH|MENTAL|BEHAVIOR", cls_text)
    yn = lambda b: "Yes" if b else ""
    return {
        "Spine / Scoliosis Related": yn(spine_why),
        "Why Spine-Flagged": "; ".join(spine_why),
        "Orthopedics": yn(ortho),
        "Surgery": yn(surgery),
        "Rehab / Physical Therapy": yn(rehab),
        "Pediatric / Children": yn(peds),
        "Mental Health": yn(mental),
    }


def fmt_phone(p):
    d = re.sub(r"\D", "", p or "")
    return f"({d[:3]}) {d[3:6]}-{d[6:10]}" if len(d) == 10 else (p or "")


KEEP_UPPER = {"LLC", "PA", "P.A.", "PLLC", "LLP", "LP", "MD", "DO", "DDS", "DMD", "DPM", "PC", "P.C.",
              "USA", "US", "FL", "II", "III", "IV", "ENT", "ASC", "ICU", "HCA", "UF", "VA", "PT", "OT", "MRI",
              "ABA", "ALF", "DME", "NE", "NW", "SE", "SW", "PO", "P.O.", "LLC.", "M.D.", "D.O.", "N.A."}


def title(s):
    s = (s or "").strip()
    if not s.isupper():
        return s
    out = []
    for w in s.title().split(" "):
        core = w.rstrip(",")
        out.append(w.upper() if core.upper() in KEEP_UPPER else w)
    s = " ".join(out)
    s = re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), s)  # 21St -> 21st
    return re.sub(r"(\w)'S\b", r"\1's", s)  # Children'S -> Children's


county_cache = {}


def county(z):
    if z not in county_cache:
        m = zipcodes.matching(z) if len(z) == 5 and z.isdigit() else []
        county_cache[z] = m[0]["county"] if m else ""
    return county_cache[z]


def city_key(c):
    """Spelling-insensitive key for a city name: 'St. Petersburg, FL' and 'Saint Petersburg' match.
    site/index.template.html has the same rules in cityKey(); keep the two in step."""
    k = re.sub(r"[.,'’\-]", " ", (c or "").lower())
    k = re.sub(r"\s+(fl|florida)(\s+\d{5})?\s*$", "", k)
    k = re.sub(r"\s+\d{5}\s*$", "", k)
    for short, full in (("st", "saint"), ("ste", "sainte"), ("ft", "fort"), ("pt", "port"), ("mt", "mount"),
                        ("n", "north"), ("s", "south"), ("e", "east"), ("w", "west")):
        k = re.sub(rf"\b{short}\b", full, k)
    return re.sub(r"\s+", " ", k).strip()


def zip_cities(z):
    """USPS city names that are valid for a ZIP code, primary first."""
    m = zipcodes.matching(z) if len(z) == 5 and z.isdigit() else []
    return [m[0]["city"], *m[0]["acceptable_cities"]] if m else []


def canonical_cities(pairs):
    """Map each (registry city, ZIP) to one clean spelling.

    Uses the USPS name for the ZIP when the registry city is that name in another spelling or with a
    small typo ('Ft Lauderdale', 'Fort Lauderdle'); otherwise the most common registry spelling of the city."""
    spellings = {}
    for c, _ in pairs:
        spellings.setdefault(city_key(c), Counter())[title(c).strip(" ,.")] += 1
    common = {k: cnt.most_common(1)[0][0] for k, cnt in spellings.items()}
    out = {}
    for c, z in set(pairs):
        k = city_key(c)
        usps = {city_key(u): title(u) for u in zip_cities(z)}
        if k in usps:
            name = usps[k]
        else:
            close = difflib.get_close_matches(k, list(usps), n=1, cutoff=0.85) if k else []
            name = usps[close[0]] if close else common.get(k) or title(c)
        out[c, z] = readable_city(name)
    return out


def readable_city(name):
    """Spell out postal abbreviations the way the cities write their own names: Ft Lauderdale -> Fort Lauderdale,
    St Petersburg -> St. Petersburg, N Miami Beach -> North Miami Beach."""
    for short, full in ((r"Ft\.?", "Fort"), (r"Pt\.?", "Port"), (r"Mt\.?", "Mount"), (r"St(?!\.)", "St."),
                        (r"N\.?", "North"), (r"S\.?", "South"), (r"E\.?", "East"), (r"W\.?", "West")):
        name = re.sub(rf"\b{short}(?= \w)", full, name)
    return name


def location(r):
    """The practice-location address of a raw registry record, or None if it isn't in Florida."""
    loc = next((a for a in r["addresses"] if a["address_purpose"] == "LOCATION"), None)
    return loc if loc and loc.get("state") == "FL" else None


def address_key(loc):
    """The (street, city, ZIP) key used for address lookups; shared by geocoding and the site build."""
    return ((loc.get("address_1") or "").strip().upper(), (loc.get("city") or "").upper(),
            (loc.get("postal_code") or "")[:5])


def raw_records(path=RAW):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)


def load_rows(path=RAW):
    """One dict per Florida organization, plus its "_key" for address lookups."""
    records, seen = [], set()
    for r in raw_records(path):
        loc = location(r)
        if loc and r["number"] not in seen:
            seen.add(r["number"])
            records.append((r, loc))
    cities = canonical_cities([(loc.get("city", ""), (loc.get("postal_code") or "")[:5]) for _, loc in records])
    rows = []
    for r, loc in records:
        taxes = r.get("taxonomies", [])
        primary = next((t for t in taxes if t.get("primary")), taxes[0] if taxes else {})
        pcode = primary.get("code", "")
        codes = {t["code"] for t in taxes}
        cat = category(pcode)
        cls_text = " ".join((tax.get(c, {}).get("Classification", "") + " " + tax.get(c, {}).get("Specialization", ""))
                            for c in codes).upper()
        b = r["basic"]
        name = b.get("organization_name", "")
        dba = [o["organization_name"] for o in r.get("other_names", []) if o.get("organization_name")]
        all_names = (name + " " + " ".join(dba)).upper()
        specialties = sorted({display(t["code"], t.get("desc", "")) for t in taxes} - {""})
        z = (loc.get("postal_code") or "")[:5]
        addr = ", ".join(x for x in [loc.get("address_1", ""), loc.get("address_2", "")] if x)
        rows.append({
            "Name": title(name),
            "Also Known As": "; ".join(title(d) for d in dba),
            "Category": cat,
            "Facility Type": display(pcode, primary.get("desc", "")),
            "Main Specialty": tax.get(pcode, {}).get("Specialization") or tax.get(pcode, {}).get("Classification")
            or primary.get("desc", ""),
            "All Listed Specialties": "; ".join(specialties),
            **flags(codes, cls_text, all_names, cat),
            "Street Address": title(addr),
            "City": cities[loc.get("city", ""), z],
            "County": county(z),
            "ZIP": z,
            "Phone": fmt_phone(loc.get("telephone_number")),
            "NPI Number": r["number"],
            "Record Last Updated": b.get("last_updated", ""),
            "_key": address_key(loc),
        })
    return rows
