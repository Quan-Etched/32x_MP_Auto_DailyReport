#!/usr/bin/env python3
"""Rebuild errors/catalogue.json from an export of the error-code sheet.

The sheet is the line's, maintained by Ulysses Kao, and it moves. Nothing in
the hourly build reaches for it — the catalogue is committed, so a rebuild on
the box never depends on Google being up or on anyone's credentials. This is
the step that refreshes it, run by hand when the sheet has changed.

    # export the sheet as .xlsx or .csv into diff/, then:
    python3 tools/refresh_error_catalogue.py diff/error-codes.xlsx

It reads the three tables the sheet keeps (1X Module, L10, L11), each with its
own columns, keyed on "Error Code ID". A table it cannot find a header row for
is reported rather than skipped quietly: a silently empty catalogue would make
every failure look uncatalogued.
"""

from __future__ import annotations

import csv
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / "errors" / "catalogue.json"
SHEET = ("https://docs.google.com/spreadsheets/d/"
         "1zKcxEXyYFLAQkI0AnVtZnSQ7Z-sxGqzGBpc9-0qhrqk/edit"
         "?gid=1353335746#gid=1353335746")

CODE = re.compile(r"^[A-Z]{2,4}-[A-Z0-9]+-\d+")


def rows_from_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            yield [cell.strip() for cell in row]


def rows_from_xlsx(path):
    """openpyxl if it is there, else say so. Not a hard dependency: the CSV
    path is stdlib and is what the box would ever need."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise SystemExit(
            "openpyxl is not installed, so .xlsx cannot be read here. Export "
            "the sheet as CSV instead, or pip install openpyxl.")
    book = load_workbook(path, read_only=True, data_only=True)
    for sheet in book.worksheets:
        for row in sheet.iter_rows(values_only=True):
            yield [("" if cell is None else str(cell)).strip() for cell in row]


def parse(rows):
    """Walk the tables, tracking whichever header row was last seen."""
    header, codes, tables = None, {}, 0
    for row in rows:
        if "Error Code ID" in row:
            header = row
            tables += 1
            continue
        if not header or len(row) != len(header):
            continue
        record = dict(zip(header, row))
        code = record.get("Error Code ID", "")
        if not CODE.match(code):
            continue
        entry = codes.setdefault(code, {
            "code": code,
            "message": record.get("Message") or record.get("Name") or "",
            "action": record.get("Quick_Action", ""),
            "component": record.get("Component", ""),
            "type": record.get("Error_Type", ""),
            "source": record.get("Source", ""),
            "bugs": record.get("Bugs", ""),
            "cases": [],
        })
        for case in re.split(r"[,\s]+", record.get("Test_Case", "")):
            case = case.strip()
            if case and case not in entry["cases"]:
                entry["cases"].append(case)
    return codes, tables


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = pathlib.Path(argv[1])
    if not path.exists():
        print("no such file: {}".format(path), file=sys.stderr)
        return 1
    reader = rows_from_xlsx if path.suffix.lower() in (".xlsx", ".xlsm") \
        else rows_from_csv
    codes, tables = parse(reader(path))
    if not codes:
        print("no error codes found in {} — is it the right export? The "
              "parser looks for a row containing 'Error Code ID'."
              .format(path), file=sys.stderr)
        return 1

    cases = {case for entry in codes.values() for case in entry["cases"]}
    from datetime import date
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": SHEET,
        "readOn": date.today().isoformat(),
        "codes": sorted(codes.values(), key=lambda entry: entry["code"]),
    }, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("{} codes over {} test cases, from {} table(s) -> {}".format(
        len(codes), len(cases), tables, OUT))
    print("Now run `make errors` to re-join the failures.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
