"""A minimal .xlsx reader — standard library only.

WHY NOT openpyxl
----------------
The whole project installs nothing: it runs on a factory laptop and on a
dashboard host whose only package permission is ``dnf install``. An .xlsx is a
zip of XML, and the part of it this repo needs — cell text, hyperlink targets
and fill colours — is a few hundred lines of ``zipfile`` and
``xml.etree``. Adding a dependency to avoid them would cost more than it saves.

WHAT IT READS, AND WHAT IT DELIBERATELY DOES NOT
------------------------------------------------
Reads: sheet names in workbook order, cell values (shared, inline, formula
result and numeric), per-cell hyperlink targets, per-cell fill and font colour,
and column widths. That is exactly what it takes to reproduce a tracker sheet
faithfully in HTML.

Does not read: formulas themselves (only their cached result), charts, images,
conditional formatting, data validation, or merged ranges. None of them appear
in the sheets this reads, and a reader that pretended to handle them would be
worse than one whose limits are written down.

Numbers come back as text, unchanged, *except* where the cell's number format
says it is a date — then it is rendered ISO. Excel stores dates as a serial day
count, so a sheet that switched its Date column from text to real dates would
otherwise start publishing ``45900`` and nobody would notice until someone read
a row closely.
"""

from __future__ import annotations

import re
import zipfile
from datetime import datetime, timedelta
from typing import Dict, List, NamedTuple, Optional
from xml.etree import ElementTree as ET

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"

_M = "{%s}" % MAIN
_R = "{%s}" % RELS

#: Built-in number-format ids that mean "date" or "date time". 14-22 and 45-47
#: are fixed by the spec; anything custom is sniffed from its format string.
_DATE_FMT_IDS = set(range(14, 23)) | set(range(45, 48))
_DATE_FMT_CHARS = re.compile(r"[ymd]", re.IGNORECASE)

#: Excel's day zero, with the 1900 leap-year bug already accounted for by
#: starting two days early — the same convention every spreadsheet uses.
_EPOCH = datetime(1899, 12, 30)

_CELL_REF = re.compile(r"([A-Z]+)(\d+)")


class Cell(NamedTuple):
    """One cell: what it says, where it points, and how it is painted."""

    ref: str
    column: str
    row: int
    value: str
    href: Optional[str] = None
    fill: Optional[str] = None       # 'FFD1FAE5' style ARGB, or None
    color: Optional[str] = None      # font colour, same encoding
    bold: bool = False


class Sheet(NamedTuple):
    name: str
    rows: List[List[Cell]]           # dense per row, in column order
    widths: Dict[str, float]         # column letter -> width in characters


def column_of(ref: str) -> str:
    match = _CELL_REF.match(ref)
    return match.group(1) if match else ref


def row_of(ref: str) -> int:
    match = _CELL_REF.match(ref)
    return int(match.group(2)) if match else 0


def column_index(letters: str) -> int:
    """``A`` -> 0, ``K`` -> 10. Used to place cells in a dense row."""
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - 64)
    return index - 1


def column_letters(index: int) -> str:
    """Inverse of :func:`column_index`."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


class Workbook:
    """An open .xlsx. Cheap to construct; sheets are parsed on demand."""

    def __init__(self, path) -> None:
        self.path = path
        self._zip = zipfile.ZipFile(str(path))
        self._shared = self._read_shared_strings()
        self._fills, self._fonts, self._date_styles = self._read_styles()
        self._sheets = self._read_sheet_index()

    # ------------------------------------------------------------------ parts

    def _xml(self, name: str):
        return ET.fromstring(self._zip.read(name))

    def _read_shared_strings(self) -> List[str]:
        try:
            root = self._xml("xl/sharedStrings.xml")
        except KeyError:
            return []
        strings = []
        for si in root.findall(_M + "si"):
            # Rich text splits one string across many <r><t> runs; phonetic
            # hints (<rPh>) are pronunciation guides, not content.
            parts = []
            for node in si.iter():
                if node.tag == _M + "t" and not self._inside_phonetic(si, node):
                    parts.append(node.text or "")
            strings.append("".join(parts))
        return strings

    @staticmethod
    def _inside_phonetic(si, node) -> bool:
        for parent in si.iter(_M + "rPh"):
            for child in parent.iter():
                if child is node:
                    return True
        return False

    def _read_styles(self):
        """Return (fill per style index, font per style index, date style set)."""
        try:
            root = self._xml("xl/styles.xml")
        except KeyError:
            return {}, {}, set()

        fills: List[Optional[str]] = []
        for fill in root.find(_M + "fills") or []:
            pattern = fill.find(_M + "patternFill")
            rgb = None
            if pattern is not None and pattern.get("patternType") not in (None, "none"):
                fg = pattern.find(_M + "fgColor")
                if fg is not None:
                    rgb = fg.get("rgb")     # theme/indexed colours resolve to None
            fills.append(rgb)

        fonts = []
        for font in root.find(_M + "fonts") or []:
            color = font.find(_M + "color")
            fonts.append({
                "color": color.get("rgb") if color is not None else None,
                "bold": font.find(_M + "b") is not None,
            })

        custom_dates = set()
        formats = root.find(_M + "numFmts")
        if formats is not None:
            for fmt in formats:
                code = fmt.get("formatCode") or ""
                # Strip colour/condition prefixes like [Red] before sniffing.
                if _DATE_FMT_CHARS.search(re.sub(r"\[[^\]]*\]", "", code)):
                    custom_dates.add(int(fmt.get("numFmtId")))

        cell_fills: Dict[int, Optional[str]] = {}
        cell_fonts: Dict[int, dict] = {}
        date_styles = set()
        xfs = root.find(_M + "cellXfs")
        for index, xf in enumerate(xfs or []):
            fill_id = int(xf.get("fillId") or 0)
            font_id = int(xf.get("fontId") or 0)
            fmt_id = int(xf.get("numFmtId") or 0)
            cell_fills[index] = fills[fill_id] if fill_id < len(fills) else None
            cell_fonts[index] = fonts[font_id] if font_id < len(fonts) else {}
            if fmt_id in _DATE_FMT_IDS or fmt_id in custom_dates:
                date_styles.add(index)
        return cell_fills, cell_fonts, date_styles

    def _read_sheet_index(self) -> Dict[str, str]:
        """Sheet name -> part name, in workbook (tab) order."""
        rels = {}
        for rel in self._xml("xl/_rels/workbook.xml.rels"):
            rels[rel.get("Id")] = rel.get("Target")

        sheets = {}
        book = self._xml("xl/workbook.xml")
        for sheet in book.iter(_M + "sheet"):
            target = rels.get(sheet.get(_R + "id"), "")
            if target.startswith("/"):
                part = target.lstrip("/")
            else:
                part = "xl/" + target.lstrip("./")
            sheets[sheet.get("name")] = part
        return sheets

    # ------------------------------------------------------------------- read

    def sheet_names(self) -> List[str]:
        return list(self._sheets)

    def sheet(self, name: str) -> Sheet:
        part = self._sheets[name]
        links = self._hyperlinks(part)
        root = self._xml(part)

        widths = {}
        for col in root.iter(_M + "col"):
            width = col.get("width")
            if not width:
                continue
            for index in range(int(col.get("min")), int(col.get("max")) + 1):
                widths[column_letters(index - 1)] = float(width)

        rows: List[List[Cell]] = []
        for row in root.iter(_M + "row"):
            cells = {}
            widest = -1
            for node in row.iter(_M + "c"):
                cell = self._cell(node, links)
                index = column_index(cell.column)
                cells[index] = cell
                widest = max(widest, index)
            if widest < 0:
                rows.append([])
                continue
            number = row_of(next(iter(cells.values())).ref)
            dense = []
            for index in range(widest + 1):
                dense.append(cells.get(index) or Cell(
                    ref="%s%d" % (column_letters(index), number),
                    column=column_letters(index), row=number, value=""))
            rows.append(dense)
        return Sheet(name=name, rows=rows, widths=widths)

    def _hyperlinks(self, part: str) -> Dict[str, str]:
        """Cell ref -> target. External links live in the sheet's rels part."""
        folder, _, filename = part.rpartition("/")
        rels_part = "%s/_rels/%s.rels" % (folder, filename)
        targets = {}
        try:
            for rel in self._xml(rels_part):
                targets[rel.get("Id")] = rel.get("Target")
        except KeyError:
            pass

        links = {}
        for node in self._xml(part).iter(_M + "hyperlink"):
            ref = node.get("ref") or ""
            target = targets.get(node.get(_R + "id")) or node.get("location") or ""
            # A merged anchor can be a range; the value sits in its first cell.
            ref = ref.split(":")[0]
            if ref and target:
                links[ref] = target
        return links

    def _cell(self, node, links: Dict[str, str]) -> Cell:
        ref = node.get("r") or ""
        kind = node.get("t")
        style = node.get("s")
        style_index = int(style) if style is not None else None

        value = ""
        if kind == "inlineStr":
            inline = node.find(_M + "is")
            if inline is not None:
                value = "".join(t.text or "" for t in inline.iter(_M + "t"))
        else:
            raw = node.find(_M + "v")
            text = raw.text if raw is not None else None
            if text is None:
                value = ""
            elif kind == "s":
                index = int(text)
                value = self._shared[index] if index < len(self._shared) else ""
            elif kind == "b":
                value = "TRUE" if text == "1" else "FALSE"
            else:
                value = self._maybe_date(text, style_index)

        font = self._fonts.get(style_index) or {}
        return Cell(
            ref=ref,
            column=column_of(ref),
            row=row_of(ref),
            value=value,
            href=links.get(ref),
            fill=self._fills.get(style_index),
            color=font.get("color"),
            bold=bool(font.get("bold")),
        )

    def _maybe_date(self, text: str, style_index: Optional[int]) -> str:
        if style_index not in self._date_styles:
            return text
        try:
            serial = float(text)
        except (TypeError, ValueError):
            return text
        moment = _EPOCH + timedelta(days=serial)
        if moment.hour or moment.minute:
            return moment.strftime("%Y-%m-%d %H:%M")
        return moment.strftime("%Y-%m-%d")
