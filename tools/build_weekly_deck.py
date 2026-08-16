#!/usr/bin/env python3
"""The weekly deck, built from the weekly bundle.

    python3 tools/build_weekly_deck.py [WEEK]

Run `make weekly` first; this reads dashboard/data/weekly.js and writes
decks/weekly-<week>.pptx. WEEK defaults to the most recent one.

WHY THE FLOW AND THE TABLE ARE ONE SLIDE
----------------------------------------
They were two, and the room had to hold the flowchart in its head while reading
the table. The numbers belong *in* the boxes: a step's yield next to the step
it belongs to, in the order a unit travels. The table then only has to carry
what a box cannot — the retest rate and what actually failed.

WHAT THE BOXES SAY
------------------
A step with enough units shows its first-pass yield. A step with fewer than the
cohort floor shows its unit count and no yield, because a 0.0% over two chassis
is not a yield. A step nobody here collects shows who does. Those three states
are drawn differently on purpose — the worst outcome for this slide is a number
whose provenance is invisible.
"""

from __future__ import annotations

import json
import pathlib
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.oxml.ns import qn
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

REPO = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = REPO / "dashboard" / "data" / "weekly.js"
OUT_DIR = REPO / "decks"

#: Where the published dashboard lives. Every link on the appendix slide is
#: built from this, so a move is one edit rather than nine.
SITE = "32x-production.i.etched.com"

W, H = Inches(13.333), Inches(7.5)

INK = RGBColor(0x14, 0x14, 0x14)
MUTE = RGBColor(0x6B, 0x6B, 0x6B)
RULE = RGBColor(0xD8, 0xD6, 0xCF)
ACC = RGBColor(0x1C, 0x62, 0xB8)
GOOD = RGBColor(0x1B, 0x7F, 0x3B)
WARN = RGBColor(0xB5, 0x6B, 0x00)
BAD = RGBColor(0xB3, 0x28, 0x1E)

# The line's own palette, kept so the slide reads as the same diagram.
GREEN = RGBColor(0xD5, 0xE8, 0xD4)
GREEN_EDGE = RGBColor(0x82, 0xB3, 0x66)
GREY = RGBColor(0xD9, 0xD9, 0xD9)
GREY_EDGE = RGBColor(0xA5, 0xA5, 0xA5)
BLUE = RGBColor(0xDA, 0xE8, 0xFC)
BLUE_EDGE = RGBColor(0x7E, 0xA6, 0xD9)
THIN = RGBColor(0xF2, 0xEC, 0xD9)          # ran, but too few units to read
THIN_EDGE = RGBColor(0xC9, 0xB4, 0x6B)
PINK = RGBColor(0xE6, 0xD0, 0xDE)
PINK_EDGE = RGBColor(0xC2, 0x9F, 0xB8)

HEAD = "Arial"
MONO = "Courier New"

#: The line's own flowchart, box for box and position for position.
#:
#: The previous slide laid every lane out as one vertical stack, which was
#: tidier and wrong: the L6 boards split and rejoin, the 2U and 4U paths
#: diverge at one assembly and meet at another, and a single column cannot say
#: either. This is the drawing the floor already reads, with the week's numbers
#: put inside the boxes.
#:
#: Coordinates are inches on a 13.333 x 7.5 slide. ROW is the vertical grid the
#: original draws on; a box names its row rather than its y, so the whole chart
#: moves by changing two numbers.
ROW0, ROW_PITCH, BOX_H = 1.62, 0.92, 0.70


def row_y(row):
    return Inches(ROW0 + ROW_PITCH * row)


#: label, x, width, row, kind, and what the box is measuring.
#:   station  — one of our station keys
#:   stations — two, where the line runs them as one box (FAT/SFT)
#:   external — reported by Sigurd
#:   note     — fixed caption, for boxes that measure nothing
LANES = [
    {"title": "ASIC", "owner": "@Sigurd", "divider": 2.42, "boxes": [
        {"label": "ASIC",  "x": 0.72, "w": 1.42, "row": 0, "kind": "build"},
        {"label": "WST",   "x": 0.72, "w": 1.42, "row": 1, "kind": "test",
         "external": "wst"},
        {"label": "FT",    "x": 0.72, "w": 1.42, "row": 2, "kind": "test",
         "external": "ft"},
        {"label": "SLT",   "x": 0.72, "w": 1.42, "row": 3, "kind": "test",
         "note": "at Sigurd"},
    ]},
    {"title": "PCBA L6", "owner": "@Pega", "divider": 5.78, "boxes": [
        {"label": "SMT / ICT", "x": 2.60, "w": 1.42, "row": 0, "kind": "build",
         "note": "HPB & VBB & PV1 & PDB"},
        {"label": "Flash / BFT", "x": 2.60, "w": 1.42, "row": 3, "kind": "flash",
         "note": "VBB — not in the yield view"},
        {"label": "HTT",  "x": 4.20, "w": 1.42, "row": 0, "kind": "test",
         "station": "htt"},
        {"label": "MLT",  "x": 4.20, "w": 1.42, "row": 1, "kind": "test",
         "station": "mlt"},
        {"label": "ASSY", "x": 4.20, "w": 1.42, "row": 2, "kind": "build"},
    ]},
    {"title": "FATP L10 2U/4U", "owner": "", "divider": 7.72, "boxes": [
        {"label": "ASSY", "x": 5.86, "w": 1.18, "row": 0, "kind": "build",
         "tags": ["4U", "2U"]},
    ]},
    {"title": "FATP L10 6U", "owner": "", "divider": 11.16, "boxes": [
        {"label": "FAT / SFT", "x": 7.92, "w": 1.52, "row": 1, "kind": "test",
         "stations": ["l10_fat", "l10_sft"]},
        {"label": "2U",   "x": 7.92, "w": 1.52, "row": 2, "kind": "test",
         "station": "l10_2u"},
        {"label": "ASSY", "x": 7.92, "w": 1.52, "row": 3, "kind": "build"},
        {"label": "Runin", "x": 9.56, "w": 1.42, "row": 1, "kind": "test",
         "station": "l10_rin"},
    ]},
    {"title": "Rack L11", "owner": "", "divider": None, "boxes": [
        {"label": "ASSY", "x": 11.34, "w": 1.52, "row": 1, "kind": "build"},
        {"label": "FAT / SFT", "x": 11.34, "w": 1.52, "row": 2, "kind": "test",
         "station": "l11_test"},
        {"label": "Runin", "x": 11.34, "w": 1.52, "row": 3, "kind": "test",
         "note": "counted with FAT / SFT"},
        {"label": "Pack", "x": 11.34, "w": 1.52, "row": 4, "kind": "pack"},
    ]},
]

#: from, to, and how the wire runs. "v" drops straight down, "h" goes straight
#: across, "vh"/"hv" turn once. The 2U path is the only one that needs two
#: turns, and it is the one the old layout could not draw at all.
WIRES = [
    ("ASIC", "WST", "v"), ("WST", "FT", "v"), ("FT", "SLT", "v"),
    ("FT", "SMT / ICT", "hv"),
    # SMT/ICT builds four boards and they go three different ways. The earlier
    # version drew only the VBB branch and then had it rejoin the module line,
    # which put the VBB board through MLT — it does not go near it. HPB and PDB
    # skip the module line entirely and meet the modules at L10 assembly.
    # Two boards leave the bottom of SMT/ICT, so the wires are nudged apart —
    # drawn from the same point they overlap and read as one.
    ("SMT / ICT", "Flash / BFT", "v", "VBB", -0.30),
    ("SMT / ICT", "ASSY@L6", "vh", "PV1", 0.34),
    ("SMT / ICT", "ASSY@2U4U", "over", "HPB & PDB"),
    ("Flash / BFT", "ASSY@2U4U", "hv"),
    ("ASSY@L6", "MLT", "v"), ("MLT", "HTT", "v"),
    ("HTT", "ASSY@2U4U", "hv"),
    ("ASSY@2U4U", "FAT / SFT@6U", "hv"),
    ("ASSY@2U4U", "ASSY@6U", "vh"),
    ("ASSY@6U", "2U", "v"), ("2U", "FAT / SFT@6U", "v"),
    ("FAT / SFT@6U", "Runin@6U", "h"),
    ("Runin@6U", "ASSY@L11", "h"),
    ("ASSY@L11", "FAT / SFT@L11", "v"),
    ("FAT / SFT@L11", "Runin@L11", "v"),
    ("Runin@L11", "Pack", "v"),
]

#: Boxes whose label repeats across lanes need a lane suffix in the wire list.
SUFFIX = {("PCBA L6", "ASSY"): "ASSY@L6",
          ("FATP L10 2U/4U", "ASSY"): "ASSY@2U4U",
          ("FATP L10 6U", "ASSY"): "ASSY@6U",
          ("FATP L10 6U", "FAT / SFT"): "FAT / SFT@6U",
          ("FATP L10 6U", "Runin"): "Runin@6U",
          ("Rack L11", "ASSY"): "ASSY@L11",
          ("Rack L11", "FAT / SFT"): "FAT / SFT@L11",
          ("Rack L11", "Runin"): "Runin@L11"}


def load(week_label=None):
    text = BUNDLE.read_text(encoding="utf-8")
    data = json.loads(text.split("= ", 1)[1].rstrip().rstrip(";"))
    weeks = data.get("weeks") or []
    if not weeks:
        raise SystemExit("no weeks in {} — run `make weekly`".format(BUNDLE))
    if week_label:
        for week in weeks:
            if week["week"] == week_label:
                return data, week
        raise SystemExit("no such week: {}".format(week_label))
    return data, weeks[0]


def pct(value):
    return "—" if value is None else "{:.1f}%".format(value * 100)


def tone(value):
    if value is None:
        return MUTE
    return GOOD if value >= 0.9 else WARN if value >= 0.6 else BAD


# --------------------------------------------------------------------- draw

def textbox(slide, x, y, w, h, lines, size=12, align=PP_ALIGN.LEFT, space=3):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0
    first = True
    for line in lines:
        para = frame.paragraphs[0] if first else frame.add_paragraph()
        first = False
        para.alignment = align
        para.space_after = Pt(space)
        for piece in (line if isinstance(line, list) else [line]):
            text, opts = piece if isinstance(piece, tuple) else (piece, {})
            run = para.add_run()
            run.text = text
            run.font.size = Pt(opts.get("size", size))
            run.font.bold = opts.get("bold", False)
            run.font.name = opts.get("font", HEAD)
            run.font.color.rgb = opts.get("color", INK)
    return box


def title_slide(prs, title, kicker):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    textbox(slide, Inches(0.55), Inches(0.34), W - Inches(1.1), Inches(0.8), [
        (title, {"size": 27, "bold": True}),
        (kicker, {"size": 12.5, "color": MUTE}),
    ], space=1)
    rule = slide.shapes.add_shape(1, Inches(0.55), Inches(1.28),
                                  W - Inches(1.1), Pt(1.1))
    rule.fill.solid()
    rule.fill.fore_color.rgb = RULE
    rule.line.fill.background()
    rule.shadow.inherit = False
    return slide


#: The line's own chart, as exported. Callouts are anchored to pixel rectangles
#: measured from this exact file, so the check below refuses to place them on
#: an image of a different size — a swapped export would otherwise scatter the
#: numbers across the picture and still produce a slide.
FLOW_IMAGE = REPO / "decks" / "img" / "production-test-flow.png"
FLOW_IMAGE_SIZE = (1662, 920)

#: label -> (x0, y0, x1, y1) in that image, and what the callout should say.
#: Measured by flood-filling the box fills rather than by eye.
FLOW_BOXES = {
    "ASIC":        (91, 218, 235, 299),
    "WST":         (91, 345, 235, 426),
    "FT":          (91, 472, 235, 553),
    "SLT":         (88, 598, 232, 679),
    "SMT / ICT":   (300, 239, 444, 320),
    "Flash / BFT": (323, 655, 438, 726),
    "HTT":         (491, 297, 635, 378),
    "MLT":         (491, 423, 635, 504),
    "ASSY@L6":     (491, 548, 635, 630),
    "ASSY@2U4U":   (756, 298, 900, 379),
    "FAT / SFT@6U": (1068, 346, 1212, 427),
    "2U":          (1068, 485, 1212, 566),
    "ASSY@6U":     (1068, 623, 1212, 705),
    "Runin@6U":    (1252, 346, 1396, 427),
    "ASSY@L11":    (1444, 345, 1588, 426),
    "FAT / SFT@L11": (1444, 494, 1588, 575),
    "Runin@L11":   (1444, 643, 1588, 724),
    "Pack":        (1444, 776, 1588, 857),
}

#: Which box carries which station's number, and what to say where there is no
#: number to carry.
FLOW_CALLOUTS = [
    ("WST", {"external": "wst"}),
    ("FT", {"external": "ft"}),
    ("SLT", {"note": "at Sigurd — not collected here"}),
    ("MLT", {"station": "mlt"}),
    ("HTT", {"station": "htt"}),
    ("Flash / BFT", {"note": "VBB — outside the yield view"}),
    ("FAT / SFT@6U", {"stations": ["l10_fat", "l10_sft"]}),
    ("2U", {"station": "l10_2u"}),
    ("Runin@6U", {"station": "l10_rin"}),
    ("FAT / SFT@L11", {"station": "l11_test"}),
    ("Runin@L11", {"note": "counted with FAT / SFT"}),
]


def flow_image_slide(prs, data, week, by_station, external):
    """Page 2 on the line's own exported chart, with the numbers written under
    the boxes.

    Drawing the chart ourselves kept it in step with the data automatically;
    using the export keeps it in step with the *line*, which is the version
    everyone else is already looking at. The trade is real and worth naming:
    when the line redraws the flow, this image and the rectangles below must be
    replaced together, and the size check is what stops that being silent.
    """
    slide = title_slide(
        prs,
        "Production test flow — yield and quantity",
        "{} · {} to {}{} · UTC · first-pass yield and units, under each step"
        .format(week["week"], week["from"], week["endsOn"],
                ", week still running" if week["partial"] else ""))

    # Fit the export by height, leaving a column at the right for the week's
    # headline figures.
    img_x, img_y, img_h = 0.30, 1.30, 5.80
    img_w = img_h * (FLOW_IMAGE_SIZE[0] / FLOW_IMAGE_SIZE[1])
    slide.shapes.add_picture(str(FLOW_IMAGE), Inches(img_x), Inches(img_y),
                             Inches(img_w), Inches(img_h))

    def place(px, py):
        return (img_x + px * img_w / FLOW_IMAGE_SIZE[0],
                img_y + py * img_h / FLOW_IMAGE_SIZE[1])

    for name, spec in FLOW_CALLOUTS:
        box = FLOW_BOXES[name]
        lines = callout_lines(spec, by_station, external)
        if not lines:
            continue
        x, y = place(box[0], box[3] + 3)
        width = (box[2] - box[0]) * img_w / FLOW_IMAGE_SIZE[0]
        # A shade wider than the box so "65.5%  228 units" fits on one line,
        # centred so the overhang is even and stays inside its own lane.
        pad = 0.34
        chip = textbox(slide, Inches(x - pad / 2), Inches(y),
                       Inches(width + pad), Inches(0.24), lines,
                       align=PP_ALIGN.CENTER, space=0)
        # Opaque: the gap under a box is where its incoming arrow runs, and
        # text laid straight over a line is unreadable at the back of a room.
        chip.fill.solid()
        chip.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        chip.line.color.rgb = RGBColor(0xC8, 0xC6, 0xC0)
        chip.line.width = Pt(0.6)
        chip.shadow.inherit = False

    headline(slide, data, week, Inches(img_x + img_w + 0.16))
    return slide


def callout_lines(spec, by_station, external):
    """One line under a box: the number, or why there is not one."""
    ext = external.get(spec.get("external")) if spec.get("external") else None
    if ext is not None:
        return [[(pct(ext["yield"]), {"size": 11, "bold": True,
                                      "color": tone(ext["yield"])}),
                 ("  reported", {"size": 8, "color": MUTE})]]

    keys = spec.get("stations") or ([spec["station"]] if spec.get("station") else [])
    rows = [by_station[k] for k in keys if k in by_station]
    if not rows:
        return ([[(spec["note"], {"size": 8, "color": MUTE})]]
                if spec.get("note") else None)

    if len(rows) == 1 and rows[0].get("readable"):
        row = rows[0]
        return [[(pct(row["fpy"]), {"size": 12, "bold": True,
                                    "color": tone(row["fpy"])}),
                 ("  {} units".format(row["units"]), {"size": 8.5, "color": MUTE})]]

    counts = " · ".join(
        "{} {}u".format(r["label"].split()[-1], r["units"]) if len(rows) > 1
        else "{} unit{}".format(r["units"], "" if r["units"] == 1 else "s")
        for r in rows)
    return [[(counts, {"size": 10, "bold": True}),
             ("  quantity only", {"size": 8, "color": MUTE})]]


def headline(slide, data, week, x):
    """The week in three figures, beside the chart.

    Width is fixed at 2.2in and the caller places it right after the image;
    at 2.35 it ran off the slide by a tenth of an inch, which PowerPoint shows
    happily and a projector crops.
    """
    totals = week["totals"]
    thin = [t["label"] for t in (totals.get("excludedThin") or [])]
    counts = [row["label"] for row in week["rows"] if row.get("countsOnly")]

    textbox(slide, x, Inches(1.42), Inches(2.20), Inches(1.0),
            [[("Rolled first-pass", {"size": 10, "color": MUTE})],
             [(pct(totals["rolledFpy"]), {"size": 26, "bold": True, "color": ACC})],
             [(" × ".join(totals["rolledOver"]), {"size": 9, "color": MUTE})]],
            space=1)
    textbox(slide, x, Inches(2.72), Inches(2.20), Inches(1.0),
            [[("Through the line", {"size": 10, "color": MUTE})],
             [("{} units".format(sum(r["units"] for r in week["rows"])),
               {"size": 18, "bold": True})],
             [("{} runs across {} steps".format(
                 sum(r["runs"] for r in week["rows"]), len(week["rows"])),
               {"size": 9, "color": MUTE})]], space=1)
    textbox(slide, x, Inches(3.85), Inches(2.20), Inches(2.9),
            [[("Reading the numbers", {"size": 10, "bold": True, "color": MUTE})],
             [("A percentage is a first-pass yield: units that passed at their "
               "first attempt that week.", {"size": 8.5})],
             [("A count means no yield is reported. {} are chassis and rack "
               "level and in bring-up — a percentage over three units swings "
               "33 points on one of them.".format(", ".join(counts) or "None"),
               {"size": 8.5})],
             [("{}WST and FT are reported by Sigurd. VBB is drawn for the flow "
               "and left out of the yield view."
               .format("Too few units this week: {}. ".format(", ".join(thin))
                       if thin else ""), {"size": 8.5})],
             [("Source: {}, one row per unit."
               .format((data.get("source") or {}).get("label", "pega2–pega5")),
               {"size": 8, "color": MUTE})]], space=5)


def flow_slide(prs, data, week, by_station, external):
    slide = title_slide(
        prs,
        "Production test flow — yield and quantity",
        "{} · {} to {}{} · UTC · first-pass yield and units, in the box".format(
            week["week"], week["from"], week["endsOn"],
            ", week still running" if week["partial"] else ""))

    placed = {}
    for lane in LANES:
        # Lane heading, then the dashed rule the original draws between lanes.
        first_x = min(box["x"] for box in lane["boxes"])
        # Clamped: the last lane starts at 11.34in and a fixed 3in heading
        # would hang 1in off a 13.333in slide.
        head_w = min(3.0, 13.15 - first_x)
        textbox(slide, Inches(first_x), Inches(1.20), Inches(head_w), Inches(0.26),
                [[(lane["owner"] + "   " if lane["owner"] else "",
                   {"size": 10, "color": MUTE}),
                  (lane["title"], {"size": 12.5, "bold": True})]], space=0)
        if lane["divider"] is not None:
            divider(slide, lane["divider"])

        for box in lane["boxes"]:
            key = SUFFIX.get((lane["title"], box["label"]), box["label"])
            placed[key] = draw_box(slide, box, by_station, external, data)

    for wire in WIRES:
        src, dst, route = wire[0], wire[1], wire[2]
        label = wire[3] if len(wire) > 3 else None
        dx = wire[4] if len(wire) > 4 else 0.0
        if src in placed and dst in placed:
            connect(slide, placed[src], placed[dst], route, label, dx)

    footnote(slide, data, week)
    return slide


def divider(slide, x):
    """The dashed rule between two lanes, as on the line's own chart."""
    line = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(1.24), Inches(x), Inches(6.35))
    line.line.color.rgb = RGBColor(0xB5, 0xB3, 0xAC)
    line.line.width = Pt(0.9)
    line.line.dash_style = MSO_LINE_DASH_STYLE.DASH


def draw_box(slide, box, by_station, external, data):
    """One box, with whatever it is entitled to say about the week."""
    x, y = Inches(box["x"]), row_y(box["row"])
    w, h = Inches(box["w"]), Inches(BOX_H)

    rows = [by_station[k] for k in box.get("stations",
                                           [box.get("station")] if box.get("station") else [])
            if k in by_station]
    ext = external.get(box.get("external"))
    readable = bool(rows) and all(r.get("readable") for r in rows)

    fill, edge = GREY, GREY_EDGE
    if box["kind"] == "pack":
        fill, edge = BLUE, BLUE_EDGE
    elif box["kind"] == "flash":
        fill, edge = PINK, PINK_EDGE
    elif box["kind"] == "test":
        fill, edge = (GREEN, GREEN_EDGE) if (readable or ext) else (THIN, THIN_EDGE)
        if not rows and not ext:
            fill, edge = GREY, GREY_EDGE          # a test we do not measure

    shape = slide.shapes.add_shape(5, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = edge
    shape.line.width = Pt(1)
    shape.shadow.inherit = False

    lines = [[(box["label"], {"size": 12.5, "bold": box["kind"] == "test"})]]
    if ext is not None:
        lines.append([(pct(ext["yield"]), {"size": 15, "bold": True,
                                           "color": tone(ext["yield"])}),
                      ("  reported", {"size": 8, "color": MUTE})])
    elif readable and len(rows) == 1:
        lines.append([(pct(rows[0]["fpy"]), {"size": 16, "bold": True,
                                             "color": tone(rows[0]["fpy"])}),
                      ("  {}u".format(rows[0]["units"]),
                       {"size": 9, "color": MUTE})])
    elif rows:
        # One box, one or two stations, none with enough units. Name each with
        # its count — "2 units" over a box the line calls FAT/SFT hides which
        # of the two actually ran.
        if len(rows) == 1:
            lines.append([("{} unit{}".format(
                rows[0]["units"], "" if rows[0]["units"] == 1 else "s"),
                {"size": 13, "bold": True})])
        else:
            # Two stations behind one box: "3 units" would hide which of them
            # ran, and on this chart that is the whole question.
            lines.append([(" · ".join(
                "{} {}u".format(r["label"].split()[-1], r["units"])
                for r in rows), {"size": 11, "bold": True})])
        reason = ("quantity only" if all(r.get("countsOnly") for r in rows)
                  else "too few for a yield")
        lines.append([(reason, {"size": 8, "color": MUTE})])
    elif box.get("note"):
        lines.append([(box["note"], {"size": 8.5, "color": MUTE})])

    textbox(slide, x + Inches(0.09), y + Inches(0.07),
            w - Inches(0.18), h - Inches(0.12), lines, space=1)

    if box.get("tags"):
        for index, tag in enumerate(box["tags"]):
            chip(slide, x + w + Inches(0.06),
                 y + Inches(0.04 + 0.31 * index), tag)

    return {"x": box["x"], "y": ROW0 + ROW_PITCH * box["row"],
            "w": box["w"], "h": BOX_H}


def chip(slide, x, y, text):
    """The 4U / 2U configuration flags that hang off the L10 assembly."""
    fill = {"4U": RGBColor(0xCF, 0xE2, 0xF3), "2U": RGBColor(0xFF, 0xF2, 0xCC),
            "6U": RGBColor(0xE8, 0x91, 0x2A)}.get(text, GREY)
    shape = slide.shapes.add_shape(1, x, y, Inches(0.42), Inches(0.25))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = RGBColor(0x8A, 0x88, 0x82)
    shape.line.width = Pt(0.6)
    shape.shadow.inherit = False
    textbox(slide, x, y + Inches(0.03), Inches(0.42), Inches(0.2),
            [(text, {"size": 9, "bold": True})], align=PP_ALIGN.CENTER, space=0)


def connect(slide, a, b, route, label=None, dx=0.0):
    """An orthogonal wire from box a to box b, arrow on the far end.

    Drawn as explicit segments rather than as an elbow connector: PowerPoint
    routes elbows by its own rules, and on a chart this dense they cross boxes.
    """
    ax, ay, aw, ah = a["x"], a["y"], a["w"], a["h"]
    bx, by, bw, bh = b["x"], b["y"], b["w"], b["h"]
    acx, acy = ax + aw / 2 + dx, ay + ah / 2
    bcx, bcy = bx + bw / 2, by + bh / 2

    # Same row: whatever the wire list says, the only sane route is straight
    # across. "hv" here sent the wire out sideways *through* the target box
    # and then up to its top edge — HTT into the L10 assembly, the most looked
    # at hand-off on the chart.
    if abs(ay - by) < 0.01 and route in ("hv", "vh"):
        route = "h"

    if route == "v":
        down = by > ay
        points = [(acx, ay + ah if down else ay), (bcx, by if down else by + bh)]
    elif route == "h":
        right = bx > ax
        points = [(ax + aw if right else ax, acy), (bx if right else bx + bw, bcy)]
    elif route == "hv":
        # out sideways, then up or down into the far box's near edge
        right = bx > ax
        turn = (bcx if right else bcx)
        points = [(ax + aw if right else ax, acy), (turn, acy),
                  (turn, by + bh if by < ay else by)]
    elif route == "over":
        # Up over the top of the chart and down into the target. The HPB and
        # PDB boards cross three lanes without touching anything in them, and
        # any route through the body of the chart would imply they do.
        top = 1.52
        points = [(acx, ay), (acx, top), (bcx, top), (bcx, by)]
    else:
        # "vh": clear of the source vertically, then straight in at the
        # target's own centre line. Turning early instead put the wire along
        # the left edges of every box it passed, which reads as a box outline.
        down = by > ay
        points = [(acx, ay + ah if down else ay), (acx, bcy),
                  (bx if bx > ax else bx + bw, bcy)]

    for index in range(len(points) - 1):
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        line = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        line.line.color.rgb = RGBColor(0x8A, 0x88, 0x82)
        line.line.width = Pt(1.1)
        if index == len(points) - 2:
            arrowhead(line)

    if label:
        if route == "over":
            lx = (points[1][0] + points[2][0]) / 2 - 0.35
            ly = points[1][1] - 0.19
        else:
            lx, ly = points[len(points) // 2]
            lx, ly = lx + 0.05, ly - 0.20
        textbox(slide, Inches(lx), Inches(ly), Inches(1.1), Inches(0.2),
                [(label, {"size": 8.5, "color": MUTE})], space=0)


def arrowhead(connector):
    """python-pptx has no arrow API; the line's tail end is one XML element."""
    line = connector.line._get_or_add_ln()
    tail = line.makeelement(qn("a:tailEnd"), {"type": "triangle",
                                              "w": "sm", "len": "sm"})
    line.append(tail)


def footnote(slide, data, week):
    counts = [row["label"] for row in week["rows"] if row.get("countsOnly")]
    thin = [t["label"] for t in (week["totals"] or {}).get("excludedThin") or []]
    textbox(slide, Inches(0.72), Inches(6.55), W - Inches(1.4), Inches(0.8), [
        [("Green", {"size": 9.5, "bold": True, "color": MUTE}),
         (" = yields, and we measure it.   ", {"size": 9.5, "color": MUTE}),
         ("Amber", {"size": 9.5, "bold": True, "color": MUTE}),
         (" = quantity only, no yield reported.   ", {"size": 9.5, "color": MUTE}),
         ("Grey", {"size": 9.5, "bold": True, "color": MUTE}),
         (" = builds, moves, or measured elsewhere.", {"size": 9.5, "color": MUTE})],
        [("Quantity only: {}. {}L10 and L11 are chassis and rack level and in "
          "bring-up — a percentage over three chassis swings 33 points on one "
          "unit, so the counts are published and the yields are not."
          .format(", ".join(counts) or "none",
                  "Too few units this week: {}. ".format(", ".join(thin))
                  if thin else ""),
          {"size": 8.5, "color": MUTE})],
        [("Source: {}, one row per unit. WST and FT reported by Sigurd. VBB "
          "provisioning drawn for the flow but left out of the yield view."
          .format((data.get("source") or {}).get("label", "pega2–pega5")),
          {"size": 8.5, "color": MUTE})],
    ], space=1)


def metrics_slide(prs, data, week, by_station):
    """Page 0: the three numbers, in the words the line uses for them.

    The definitions here are the ones written on the reviewed deck rather than
    the ones this file used to generate. They are shorter and they are better:
    "how stable is the test" is what a retest rate is for, and a paragraph
    about denominators at the top of a deck loses the room before the data
    arrives. The measured figure sits beside each so the vocabulary and this
    week's number are read together.
    """
    slide = title_slide(
        prs, "Basic Level of Production Metrics",
        "{} · the three numbers this deck reports, and what each one is for"
        .format(week["week"]))

    mlt = by_station.get("mlt") or {}
    htt = by_station.get("htt") or {}
    totals = week["totals"]

    blocks = [
        ("1.  Capacity", "How many units we are producing",
         "{} units through {} steps this week, across {} runs."
         .format(sum(r["units"] for r in week["rows"]), len(week["rows"]),
                 sum(r["runs"] for r in week["rows"])),
         "It sets the schedule: a station cannot ship what it cannot test."),
        ("2.  Yield", "How many percentage we can ship vs total production",
         "First pass {} at MLT and {} at HTT — {} rolled across the two."
         .format(pct(mlt.get("fpy")), pct(htt.get("fpy")),
                 pct(totals["rolledFpy"])),
         "It sets how many units must be started to ship one."),
        ("3.  Retest", "How stable is the test",
         "{} of MLT units and {} of HTT units had to be run again — {} and {} "
         "units.".format(pct(mlt.get("retestRatio")), pct(htt.get("retestRatio")),
                         mlt.get("retestUnits"), htt.get("retestUnits")),
         "It is where yield loss turns into lost capacity."),
    ]

    y = Inches(1.72)
    for head, what, figure, why in blocks:
        textbox(slide, Inches(0.75), y, Inches(2.2), Inches(0.5),
                [(head, {"size": 18, "bold": True})], space=0)
        textbox(slide, Inches(3.15), y, Inches(4.6), Inches(0.8),
                [(what, {"size": 15})], space=0)
        textbox(slide, Inches(8.05), y + Inches(0.02), Inches(4.6), Inches(1.0),
                [[(figure, {"size": 11.5, "bold": True})],
                 [(why, {"size": 11, "color": MUTE})]], space=3)
        y = y + Inches(1.5)

    rule = slide.shapes.add_shape(1, Inches(0.75), Inches(6.35),
                                  W - Inches(1.5), Pt(1))
    rule.fill.solid()
    rule.fill.fore_color.rgb = RULE
    rule.line.fill.background()
    rule.shadow.inherit = False
    textbox(slide, Inches(0.75), Inches(6.55), W - Inches(1.5), Inches(0.6),
            [[("Why it is broken out by test step:  ", {"size": 12.5, "bold": True}),
              ("a line ships at the rate of its worst step, not its average — "
               "so the only useful version of these three numbers is one per "
               "step, in the order a unit travels.", {"size": 12.5})]], space=0)
    return slide


def actions_slide(prs, data, week, by_station):
    """Page 3: the two actions, with the targets set on the reviewed deck.

    Targets are quoted rather than invented — 85% yield and under 10% retest at
    L6, three to ten units at L10 — and each is shown against where the week
    actually landed. An action item with a number beside today's number is a
    decision; one without is a sentiment.
    """
    slide = title_slide(
        prs, "What's next",
        "two actions, each against a target and where {} finished"
        .format(week["week"]))

    mlt = by_station.get("mlt") or {}
    htt = by_station.get("htt") or {}
    l10 = [row for row in week["rows"] if row["key"].startswith("l10_")]
    l10_units = sum(row["units"] for row in l10)

    actions = [
        ("a", "Improve the yield / stability of L6 test", None,
         [("Yield target", "85%",
           "today {} at MLT, {} at HTT".format(pct(mlt.get("fpy")),
                                               pct(htt.get("fpy")))),
          ("Stability", "< 10% retest",
           "today {} at MLT, {} at HTT".format(pct(mlt.get("retestRatio")),
                                               pct(htt.get("retestRatio"))))],
         "L6 is the only level with the volume to be measured against a "
         "target at all, and it is where the line loses most of its units."),
        ("b", "Speed up development of multiple L10 test units",
         "only 1–2 units onsite",
         [("Target", "3 to 10 units",
           "assembled for test development"),
          ("Coverage", "full coverage",
           "today {} units across four steps".format(l10_units))],
         "Not to improve the L10 yield — to make one exist. On single digits "
         "there is nothing to read, which is why every L10 box on this deck "
         "says quantity only."),
    ]

    y = Inches(1.66)
    for tag, title, gate, targets, why in actions:
        marker = slide.shapes.add_shape(9, Inches(0.72), y, Inches(0.38),
                                        Inches(0.38))
        marker.fill.solid()
        marker.fill.fore_color.rgb = ACC
        marker.line.fill.background()
        marker.shadow.inherit = False
        textbox(slide, Inches(0.72), y + Inches(0.06), Inches(0.38),
                Inches(0.3), [(tag, {"size": 13, "bold": True,
                                     "color": RGBColor(0xFF, 0xFF, 0xFF)})],
                align=PP_ALIGN.CENTER, space=0)

        head = [[(title, {"size": 17, "bold": True})]]
        if gate:
            head.append([("Gate: ", {"size": 11, "color": MUTE}),
                         (gate, {"size": 11, "bold": True, "color": BAD})])
        textbox(slide, Inches(1.26), y, Inches(6.4), Inches(0.7), head, space=2)

        ty = y + Inches(0.80)
        for label, target, today in targets:
            textbox(slide, Inches(1.42), ty, Inches(1.5), Inches(0.28),
                    [(label, {"size": 11, "color": MUTE})], space=0)
            textbox(slide, Inches(2.95), ty, Inches(1.7), Inches(0.28),
                    [(target, {"size": 14, "bold": True, "color": GOOD})], space=0)
            textbox(slide, Inches(4.75), ty, Inches(3.0), Inches(0.28),
                    [(today, {"size": 11, "color": MUTE})], space=0)
            ty = ty + Inches(0.38)

        textbox(slide, Inches(8.05), y + Inches(0.04), Inches(4.6), Inches(1.4),
                [(why, {"size": 12})], space=0)
        y = y + Inches(2.32)

    rule = slide.shapes.add_shape(1, Inches(0.72), Inches(6.42),
                                  W - Inches(1.44), Pt(1))
    rule.fill.solid()
    rule.fill.fore_color.rgb = RULE
    rule.line.fill.background()
    rule.shadow.inherit = False
    textbox(slide, Inches(0.72), Inches(6.58), W - Inches(1.44), Inches(0.6),
            [[("The ordering is the point.  ", {"size": 12, "bold": True}),
              ("Coverage, then stability, then efficiency — a station clears "
               "one gate before the next is worth measuring. L6 is at the "
               "first gate with the volume to prove it; L10 is not yet at a "
               "gate at all.", {"size": 12})]], space=0)
    return slide


def appendix_slide(prs, data, week):
    """Page 4: where every number on the deck came from, as addresses.

    A deck that cannot be checked gets argued with instead of acted on. The
    week's own page is first because it is the one that answers "which units",
    which is the question that has actually been asked of these numbers.
    """
    slide = title_slide(
        prs, "Appendix — where the data comes from",
        "every figure on this deck traces to one of these; the first one lists "
        "the units behind it")

    groups = [
        ("This week, unit by unit", [
            ("Source data for {} — every DUT serial, software release, "
             "verdict and a link to its run".format(week["week"]),
             "{}/week.html#week={}".format(SITE, week["week"])),
            ("Every week since collection began, one row each",
             "{}/weekly.html".format(SITE)),
        ]),
        ("The rest of the dashboard", [
            ("Daily tracker — the line's own MLT/HTT tabs, rebuilt from pega3",
             "{}/dailyexcel.html".format(SITE)),
            ("L10 daily tracker — FAT, SFT, RIN, 2U from pega4",
             "{}/l10.html".format(SITE)),
            ("Station yield, from the controllers",
             "{}/direct.html".format(SITE)),
            ("Station yield, from OCP Logs — and the measured gap between them",
             "{}/index.html".format(SITE)),
            ("Run drill-down, any serial or test name",
             "{}/runs.html".format(SITE)),
            ("Production test flow, with coverage",
             "{}/flow.html".format(SITE)),
        ]),
        ("Upstream of the dashboard", [
            ("The controllers themselves — ESVM login admin / admin",
             "pega2:3000 · pega3:3000 · pega4:3000 · pega5:3000"),
            ("OCP Logs / EOS, the other side of the discrepancy",
             "ocplogs.core.etched.com"),
            ("WST and FT — Sigurd's STDF and SPLM, asked for weekly in "
             "#production-test-eng",
             "strata6.sv9.i.etched.com:8235 · splm.i.etched.com"),
            ("This deck, the pipeline that built it, and every archived week",
             "github.com/etched-ai/factory_data_analysis · weekly/{}/".format(
                 week["week"])),
        ]),
    ]

    y = Inches(1.55)
    for title, rows in groups:
        textbox(slide, Inches(0.62), y, Inches(6.0), Inches(0.26),
                [(title, {"size": 12, "bold": True, "color": ACC})], space=0)
        y = y + Inches(0.32)
        for label, url in rows:
            textbox(slide, Inches(0.8), y, Inches(6.6), Inches(0.26),
                    [(label, {"size": 11})], space=0)
            textbox(slide, Inches(7.5), y, Inches(5.3), Inches(0.26),
                    [(url, {"size": 10.5, "font": MONO, "color": MUTE})], space=0)
            y = y + Inches(0.30)
        y = y + Inches(0.14)

    textbox(slide, Inches(0.62), Inches(6.92), W - Inches(1.24), Inches(0.4),
            [("All addresses are on the factory network. The dashboard rebuilds "
              "hourly; the archived copy of {} under weekly/ does not change."
              .format(week["week"]), {"size": 9.5, "color": MUTE})], space=0)
    return slide


def table_slide(prs, data, week, external):
    slide = title_slide(
        prs, "Every step, with the retest rate",
        "{} · retest rate is the share of units that had to be run again"
        .format(week["week"]))

    cols = [Inches(0.55), Inches(3.05), Inches(4.15), Inches(5.35),
            Inches(7.0), Inches(8.75), Inches(10.7)]
    widths = [Inches(2.4), Inches(1.0), Inches(1.1), Inches(1.5),
              Inches(1.6), Inches(1.85), Inches(2.1)]
    heads = ["Test step", "Units", "Runs", "First pass", "After retest",
             "Retest rate", "Top failure"]
    for x, w, head in zip(cols, widths, heads):
        textbox(slide, x, Inches(1.55), w, Inches(0.3),
                [(head, {"size": 10.5, "bold": True, "color": MUTE})])

    y = Inches(1.95)
    step = Inches(0.5)

    for item in external.values():
        textbox(slide, cols[0], y, widths[0], Inches(0.4),
                [[(item["label"], {"size": 13, "bold": True}),
                  ("  reported", {"size": 9, "color": MUTE})]])
        textbox(slide, cols[3], y, widths[3], Inches(0.3),
                [(pct(item["yield"]), {"size": 14, "bold": True,
                                       "color": tone(item["yield"])})])
        textbox(slide, cols[6], y, widths[6], Inches(0.4),
                [("Sigurd, as of " + item["asOf"], {"size": 9, "color": MUTE})])
        y = y + step

    for row in week["rows"]:
        readable = row.get("readable")
        colour = INK if readable else MUTE
        textbox(slide, cols[0], y, widths[0], Inches(0.4),
                [[(row["label"], {"size": 13, "bold": True, "color": colour}),
                  ("  " + (row.get("controller") or ""),
                   {"size": 9, "color": MUTE})]])
        textbox(slide, cols[1], y, widths[1], Inches(0.3),
                [(str(row["units"]), {"size": 12.5, "color": colour})])
        textbox(slide, cols[2], y, widths[2], Inches(0.3),
                [(str(row["runs"]), {"size": 12.5, "color": colour})])
        reason = ("quantity only" if row.get("countsOnly")
                  else "not enough units")
        textbox(slide, cols[3], y, widths[3], Inches(0.3),
                [(pct(row["fpy"]) if readable else reason,
                  {"size": 14 if readable else 10, "bold": readable,
                   "color": tone(row["fpy"]) if readable else MUTE})])
        textbox(slide, cols[4], y, widths[4], Inches(0.3),
                [(pct(row["finalYield"]), {"size": 12.5, "color": colour})])
        # The number the room is meant to act on, so it is the emphasised one
        # in this column and spelled out underneath.
        retest = row.get("retestRatio")
        textbox(slide, cols[5], y, widths[5], Inches(0.44),
                [[(pct(retest), {"size": 14, "bold": True,
                                 "color": BAD if (retest or 0) >= 0.25
                                 else INK})],
                 [("{} of {} units re-run".format(row.get("retestUnits"),
                                                  row["units"])
                   if row.get("retestUnits") is not None else
                   (row.get("retestNote") or ""), {"size": 8.5, "color": MUTE})]],
                space=0)
        top = row["topFailures"][0]["name"] if row["topFailures"] else "—"
        textbox(slide, cols[6], y, widths[6], Inches(0.44),
                [(top, {"size": 8.5, "color": MUTE, "font": MONO})])
        y = y + step

    textbox(slide, Inches(0.55), Inches(6.5), W - Inches(1.1), Inches(0.7), [
        [("Rolled first-pass across {}: ".format(
            " × ".join(week["totals"]["rolledOver"]) or "no step"),
          {"size": 12}),
         (pct(week["totals"]["rolledFpy"]), {"size": 14, "bold": True,
                                             "color": ACC})],
        [("Steps under {} first-time units report counts only. Full unit-level "
          "source data, every serial and release with a link to its run: "
          "32x-production.i.etched.com/week.html#week={}"
          .format(data["minCohort"], week["week"]),
          {"size": 9.5, "color": MUTE})],
    ], space=3)
    return slide


def main(argv):
    label = argv[1] if len(argv) > 1 else None
    if FLOW_IMAGE.exists():
        from PIL import Image
        with Image.open(FLOW_IMAGE) as probe:
            if probe.size != FLOW_IMAGE_SIZE:
                raise SystemExit(
                    "{} is {}, expected {} — the callout rectangles were "
                    "measured against that size and would land in the wrong "
                    "places. Re-measure FLOW_BOXES or restore the export."
                    .format(FLOW_IMAGE.name, probe.size, FLOW_IMAGE_SIZE))
    data, week = load(label)
    by_station = {row["key"]: row for row in week["rows"]}
    external = {item["key"]: item for item in (week.get("external") or [])}

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    metrics_slide(prs, data, week, by_station)
    if FLOW_IMAGE.exists():
        flow_image_slide(prs, data, week, by_station, external)
    else:
        # The drawn version stays: it needs no asset and cannot fall out of
        # step with the data, so a checkout without the image still builds.
        print("note: {} missing — drawing the flow instead".format(FLOW_IMAGE))
        flow_slide(prs, data, week, by_station, external)
    table_slide(prs, data, week, external)
    actions_slide(prs, data, week, by_station)
    appendix_slide(prs, data, week)

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "weekly-{}.pptx".format(week["week"])
    prs.save(out)
    print("{} — {} slides, {} KB".format(out, len(prs.slides._sldIdLst),
                                         out.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
