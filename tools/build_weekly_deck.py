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
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

REPO = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = REPO / "dashboard" / "data" / "weekly.js"
OUT_DIR = REPO / "decks"

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

HEAD = "Arial"
MONO = "Courier New"

#: The flow, lane by lane. `station` is the weekly bundle's key; `external`
#: names the team that measures a step we do not. VBB is deliberately absent.
LANES = [
    ("ASIC", "@Sigurd", [
        {"label": "WST", "kind": "test", "external": "wst"},
        {"label": "FT", "kind": "test", "external": "ft"},
        {"label": "SLT", "kind": "test", "owner": "Sigurd"},
    ]),
    ("PCBA L6", "@Pega", [
        {"label": "SMT / ICT", "kind": "build"},
        {"label": "ASSY", "kind": "build"},
        {"label": "MLT", "kind": "test", "station": "mlt"},
        {"label": "HTT", "kind": "test", "station": "htt"},
    ]),
    ("FATP L10 2U/4U", "", [
        {"label": "ASSY", "kind": "build", "note": "4U / 2U"},
    ]),
    ("FATP L10 6U", "", [
        {"label": "ASSY", "kind": "build"},
        {"label": "2U", "kind": "test", "station": "l10_2u"},
        {"label": "FAT", "kind": "test", "station": "l10_fat"},
        {"label": "SFT", "kind": "test", "station": "l10_sft"},
        {"label": "Runin", "kind": "test", "station": "l10_rin"},
    ]),
    ("Rack L11", "", [
        {"label": "ASSY", "kind": "build"},
        {"label": "Provisioning", "kind": "test", "station": "l11_provision"},
        {"label": "SFT / Runin", "kind": "test", "station": "l11_test"},
        {"label": "Pack", "kind": "pack"},
    ]),
]


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


def flow_slide(prs, data, week, by_station, external):
    slide = title_slide(
        prs,
        "Production test flow — yield and quantity",
        "{} · {} to {}{} · UTC · first-pass yield, units in the box".format(
            week["week"], week["from"], week["endsOn"],
            ", week still running" if week["partial"] else ""))

    lane_w = Inches(2.42)
    left0 = Inches(0.42)
    top0 = Inches(1.72)
    box_w = Inches(2.02)
    box_h = Inches(0.86)
    gap = Inches(0.22)

    anchors = {}
    for index, (lane, owner, nodes) in enumerate(LANES):
        x = left0 + Emu(int(lane_w * index))
        textbox(slide, x, Inches(1.4), lane_w, Inches(0.3),
                [[(lane, {"size": 12, "bold": True}),
                  ("  " + owner, {"size": 10, "color": MUTE})]], space=0)

        prev = None
        for row, node in enumerate(nodes):
            y = top0 + Emu(int((box_h + gap) * row))
            shape = draw_box(slide, x, y, box_w, box_h, node,
                             by_station, external, data)
            anchors[(index, row)] = (x, y, shape)
            if prev is not None:
                arrow(slide, x + Emu(int(box_w / 2)), prev, x + Emu(int(box_w / 2)), y)
            prev = y + box_h
        # Hand-off to the next lane, from the last box of this one.
        if index + 1 < len(LANES):
            last_y = top0 + Emu(int((box_h + gap) * (len(nodes) - 1)))
            arrow(slide,
                  x + box_w, last_y + Emu(int(box_h / 2)),
                  x + Emu(int(lane_w)), top0 + Emu(int(box_h / 2)))

    footnote(slide, data, week)
    return slide


def draw_box(slide, x, y, w, h, node, by_station, external, data):
    row = by_station.get(node.get("station"))
    ext = external.get(node.get("external"))

    fill, edge = GREY, GREY_EDGE
    if node["kind"] == "pack":
        fill, edge = BLUE, BLUE_EDGE
    elif node["kind"] == "test":
        fill, edge = GREEN, GREEN_EDGE
        if row is not None and not row.get("readable"):
            fill, edge = THIN, THIN_EDGE

    shape = slide.shapes.add_shape(5, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = edge
    shape.line.width = Pt(1)
    shape.shadow.inherit = False
    shape.text_frame.word_wrap = True

    lines = [[(node["label"], {"size": 13, "bold": node["kind"] == "test"})]]
    if ext is not None:
        lines.append([(pct(ext["yield"]), {"size": 15, "bold": True,
                                           "color": tone(ext["yield"])}),
                      ("  reported", {"size": 8.5, "color": MUTE})])
    elif row is not None and row.get("readable"):
        lines.append([(pct(row["fpy"]), {"size": 17, "bold": True,
                                         "color": tone(row["fpy"])}),
                      ("   {} units".format(row["units"]),
                       {"size": 9, "color": MUTE})])
    elif row is not None:
        # Ran, but under the floor. The count is the honest answer.
        lines.append([("{} units".format(row["units"]),
                       {"size": 12, "bold": True}),
                      ("  too few for a yield", {"size": 8.5, "color": MUTE})])
    elif node.get("owner"):
        lines.append([("at " + node["owner"], {"size": 9, "color": MUTE})])
    elif node.get("note"):
        lines.append([(node["note"], {"size": 9, "color": MUTE})])

    textbox(slide, x + Inches(0.11), y + Inches(0.1),
            w - Inches(0.22), h - Inches(0.16), lines, space=1)
    return shape


def arrow(slide, x1, y1, x2, y2):
    line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x1, y1, x2, y2)
    line.line.color.rgb = RGBColor(0x9A, 0x99, 0x92)
    line.line.width = Pt(1.1)


def footnote(slide, data, week):
    thin = (week["totals"] or {}).get("excludedThin") or []
    textbox(slide, Inches(0.42), Inches(6.62), W - Inches(0.84), Inches(0.7), [
        [("Green = the step yields and we measure it. ", {"size": 9.5, "color": MUTE}),
         ("Amber = it ran, under {} units, so no yield is reported — the count is. "
          .format(data["minCohort"]), {"size": 9.5, "color": MUTE}),
         ("Grey = builds or moves, no verdict.", {"size": 9.5, "color": MUTE})],
        [("Source: {}, one row per unit. WST and FT reported by Sigurd. "
          "VBB provisioning omitted — not part of the product test flow. "
          "Amber this week: {}."
          .format((data.get("source") or {}).get("label", "pega2–pega5"),
                  ", ".join("{} ({}u)".format(t["label"], t["units"])
                            for t in thin) or "none"),
          {"size": 9, "color": MUTE})],
    ], space=2)


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
        textbox(slide, cols[3], y, widths[3], Inches(0.3),
                [(pct(row["fpy"]) if readable else "not enough units",
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
    data, week = load(label)
    by_station = {row["key"]: row for row in week["rows"]}
    external = {item["key"]: item for item in (week.get("external") or [])}

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    flow_slide(prs, data, week, by_station, external)
    table_slide(prs, data, week, external)

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "weekly-{}.pptx".format(week["week"])
    prs.save(out)
    print("{} — {} slides, {} KB".format(out, len(prs.slides._sldIdLst),
                                         out.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
