"""Build the Florida medical facilities Excel workbook from the downloaded registry data.

usage: python scripts/build_spreadsheet.py            (writes data/Florida_Medical_Facilities.xlsx)
"""
import datetime
import sys

import pandas as pd

from facilities import OTHER_CATEGORIES, ROOT, load_rows

OUT = sys.argv[1] if len(sys.argv) > 1 else ROOT / "data/Florida_Medical_Facilities.xlsx"
downloaded = datetime.date.fromisoformat((ROOT / "data/raw/DOWNLOADED_ON").read_text().strip())
DOWNLOADED = f"{downloaded:%b} {downloaded.day}, {downloaded.year}"

rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in load_rows()]

df = pd.DataFrame(rows).drop_duplicates("NPI Number").sort_values(["Category", "County", "City", "Name"], kind="stable")
facilities = df[~df["Category"].isin(OTHER_CATEGORIES)]
other = df[df["Category"].isin(OTHER_CATEGORIES)]
spine = facilities[(facilities["Spine / Scoliosis Related"] == "Yes")].copy()
spine["_s"] = spine["Why Spine-Flagged"].str.contains("scoliosis").map({True: 0, False: 1})
spine = spine.sort_values(["_s", "County", "City", "Name"]).drop(columns="_s")

by_cat = facilities["Category"].value_counts().rename_axis("Category").reset_index(name="Count")
by_county = (facilities.assign(County=facilities["County"].replace("", "(Unknown)"))
             .pivot_table(index="County", columns="Category", values="NPI Number", aggfunc="count", fill_value=0))
by_county.insert(0, "Total", by_county.sum(axis=1))
by_county = by_county.sort_values("Total", ascending=False).reset_index()

print("rows", len(df), "facilities", len(facilities), "other", len(other), "spine", len(spine))
print(by_cat.to_string())
print("missing county", (df["County"] == "").sum())

with pd.ExcelWriter(OUT, engine="xlsxwriter") as xw:
    wb = xw.book
    wrap = wb.add_format({"text_wrap": True, "valign": "top"})
    h1 = wb.add_format({"bold": True, "font_size": 16})
    bold = wb.add_format({"bold": True})

    readme = wb.add_worksheet("Read Me")
    readme.set_column(0, 0, 30)
    readme.set_column(1, 1, 100, wrap)
    readme.write(0, 0, "Florida Medical Facilities", h1)
    notes = [
        ("Source", "Official U.S. NPI Registry (CMS / NPPES), downloaded " + DOWNLOADED + ". Every healthcare organization "
                   "that bills insurance must register here. Includes all Florida organizations with an active "
                   "registration and a Florida practice address."),
        ("Sheets", "Facilities: places you go for care (hospitals, rehab, clinics, doctor's offices, etc.).\n"
                   "Spine & Scoliosis: facilities from the Facilities sheet that are spine- or scoliosis-related "
                   "(ones with 'scoliosis' in the name are listed first).\n"
                   "Other Healthcare Businesses: pharmacies, equipment suppliers, ambulance/transport, insurers, etc.\n"
                   "Summary / By County: counts."),
        ("How to filter", "Every list sheet has filter arrows in the header row. Click an arrow (e.g. on 'County' "
                          "or 'Category') to show only what you want. The 'Yes' columns can be filtered the same way."),
        ("Category / Facility Type", "Category is a simple grouping. Facility Type is the official type the "
                                     "organization registered as."),
        ("Specialty columns", "Main Specialty and All Listed Specialties are the official specialties the "
                              "organization registered. The Yes/blank columns (Orthopedics, Surgery, etc.) are flags "
                              "based on those specialties and on words in the name."),
        ("Spine / Scoliosis Related", "Official records do not track individual conditions like scoliosis. A facility is "
                                      "flagged if its name mentions scoliosis or spine, if it registered as spine surgery, "
                                      "neurosurgery, pediatric orthopedics, or spinal cord injury medicine, or if it makes "
                                      "or fits braces. 'Why Spine-Flagged' says which. Always call or check the website "
                                      "to confirm they treat scoliosis."),
        ("Limitations", "- Self-reported registrations: some may be out of date, and a few may have closed.\n"
                        "- Large hospital systems often register many separate departments, so the same hospital "
                        "may appear several times.\n"
                        "- Only the main practice address is shown; some organizations have additional locations.\n"
                        "- Doctor's offices are listed when the practice is registered as an organization; "
                        "solo doctors registered only as individuals are not included.\n"
                        "- County comes from the ZIP code; a few ZIPs cross county lines."),
    ]
    for i, (k, v) in enumerate(notes, start=2):
        readme.write(i, 0, k, bold)
        readme.write(i, 1, v, wrap)

    widths = {"Name": 40, "Also Known As": 30, "Category": 28, "Facility Type": 34, "Main Specialty": 30,
              "All Listed Specialties": 45, "Why Spine-Flagged": 35, "Street Address": 34, "City": 18,
              "County": 20, "ZIP": 8, "Phone": 16, "NPI Number": 13, "Record Last Updated": 14}

    def sheet(frame, name):
        frame = frame.reset_index(drop=True)
        frame.to_excel(xw, sheet_name=name, index=False)
        ws = xw.sheets[name]
        n, m = frame.shape
        ws.add_table(0, 0, max(n, 1), m - 1, {"columns": [{"header": c} for c in frame.columns],
                                               "style": "Table Style Light 9", "autofilter": True})
        for j, c in enumerate(frame.columns):
            ws.set_column(j, j, widths.get(c, 12))
        ws.freeze_panes(1, 1)

    sheet(facilities, "Facilities")
    sheet(spine, "Spine & Scoliosis")
    sheet(other, "Other Healthcare Businesses")

    by_cat.to_excel(xw, sheet_name="Summary", index=False)
    ws = xw.sheets["Summary"]
    ws.set_column(0, 0, 40)
    ws.set_column(1, 1, 10)
    flag_cols = ["Spine / Scoliosis Related", "Orthopedics", "Surgery", "Rehab / Physical Therapy",
                 "Pediatric / Children", "Mental Health"]
    fc = pd.DataFrame({"Specialty Flag": flag_cols,
                       "Facilities Flagged": [(facilities[c] == "Yes").sum() for c in flag_cols]})
    fc.to_excel(xw, sheet_name="Summary", index=False, startcol=3)
    ws.set_column(3, 3, 28)
    ws.set_column(4, 4, 18)

    by_county.to_excel(xw, sheet_name="By County", index=False)
    ws = xw.sheets["By County"]
    ws.set_column(0, 0, 24)
    ws.set_column(1, by_county.shape[1], 14)
    ws.freeze_panes(1, 1)
