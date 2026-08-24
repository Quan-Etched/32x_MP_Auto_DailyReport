#!/usr/bin/env python3
"""Result types as slides: the four outcomes, and the MLT -> HTT flow.

WHY A SANKEY
Two stacked bars can say MLT had ten retest passes and HTT had none. Only the
flow says what became of the ten — whether the modules MLT recovered went on to
pass HTT, failed it, or never turned up. The question underneath the whole
retest discussion is what happens to a module *after* it fails, and that is a
question about the step between two stations.

Drawn with plain shapes, one freeform per ribbon. python-pptx has no Sankey and
a ribbon is four bezier segments, so the alternative would have been pasting an
image — which nobody can edit in the room, and editable was the requirement.

One slide per week, plus a trend slide. Same numbers as doe.html by
construction: both read src/factory/outcomes.py.
"""

from __future__ import annotations

import json
import pathlib
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Inches, Pt

REPO = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = REPO / "dashboard" / "data" / "outcomes.js"
OUT_DIR = REPO / "decks"

W, H = Inches(13.333), Inches(7.5)
#: Left and right margin every slide here keeps.
MARGIN = Inches(0.55)
INK = RGBColor(0x1F, 0x1F, 0x1F)
MUTE = RGBColor(0x6B, 0x6B, 0x6B)
RULE = RGBColor(0xD8, 0xD6, 0xD0)

#: The bands that are not outcomes. Grey, and named in full, so nobody reads
#: them as a verdict.
GONE = "did-not-arrive"
ABSENT = "not-seen-here"
EXTRA = {
    GONE: ("did not reach HTT", RGBColor(0xB9, 0xB7, 0xB0)),
    ABSENT: ("not seen at MLT", RGBColor(0xD0, 0xCE, 0xC7)),
}


def load():
    text = BUNDLE.read_text(encoding="utf-8")
    return json.loads(text.split("= ", 1)[1].rstrip().rstrip(";"))


def rgb(value):
    value = value.lstrip("#")
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def colour_of(key, data):
    if key in EXTRA:
        return EXTRA[key][1]
    return rgb((data.get("colours") or {}).get(key, "#8a8882"))


def name_of(key, data):
    if key in EXTRA:
        return EXTRA[key][0]
    return ((data.get("labels") or {}).get(key) or {}).get("label", key)


def textbox(slide, x, y, w, h, lines, space=4):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    for index, line in enumerate(lines):
        para = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        para.space_after = Pt(space)
        for text, style in line:
            run = para.add_run()
            run.text = text
            run.font.size = Pt(style.get("size", 12))
            run.font.bold = style.get("bold", False)
            run.font.color.rgb = style.get("color", INK)
    return box


def rule(slide, x, y, w):
    line = slide.shapes.add_shape(1, x, y, w, Pt(1))
    line.fill.solid()
    line.fill.fore_color.rgb = RULE
    line.line.fill.background()
    line.shadow.inherit = False


def band(slide, x, y, w, h, colour):
    shape = slide.shapes.add_shape(5, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = colour
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def ribbon(slide, x1, y1, x2, y2, thickness, colour):
    """One flow, as a filled freeform between two vertical edges."""
    builder = slide.shapes.build_freeform(Emu(int(x1)), Emu(int(y1)))
    mid = (x1 + x2) / 2
    # out along the top edge, down the far side, back along the bottom
    builder.add_line_segments([
        (Emu(int(mid)), Emu(int(y1))),
        (Emu(int(mid)), Emu(int(y2))),
        (Emu(int(x2)), Emu(int(y2))),
        (Emu(int(x2)), Emu(int(y2 + thickness))),
        (Emu(int(mid)), Emu(int(y2 + thickness))),
        (Emu(int(mid)), Emu(int(y1 + thickness))),
        (Emu(int(x1)), Emu(int(y1 + thickness))),
    ], close=True)
    shape = builder.convert_to_shape()
    shape.fill.solid()
    shape.fill.fore_color.rgb = colour
    shape.fill.transparency = 0.62
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def stack(order, sizes, total, top, height, gap):
    used = [key for key in order if sizes.get(key)]
    room = height - gap * max(0, len(used) - 1)
    out, y = {}, top
    for key in used:
        span = (sizes[key] / total) * room if total else 0
        out[key] = {"y": y, "h": max(span, Inches(0.03)), "n": sizes[key]}
        y += out[key]["h"] + gap
    return out


def flow_slide(prs, data, week):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    flow = week.get("flow") or {}
    ribbons = [r for r in (flow.get("ribbons") or []) if r["units"]]

    textbox(slide, Inches(0.55), Inches(0.30), Inches(12.2), Inches(0.9), [
        [("MLT → HTT by result type", {"size": 25, "bold": True})],
        [("{} · {} to {} · every unit MLT saw, and what happened to it at HTT"
          .format(week["week"], week["from"], week["to"]),
          {"size": 12, "color": MUTE})],
    ], space=2)
    rule(slide, Inches(0.55), Inches(1.22), Inches(12.2))

    if not ribbons:
        textbox(slide, Inches(0.55), Inches(1.5), Inches(12.2), Inches(0.5),
                [[("No units ran both stations this week.",
                   {"size": 13, "color": MUTE})]])
        return slide

    exclusive = data.get("exclusive") or []
    left_order = list(exclusive) + [ABSENT]
    right_order = list(exclusive) + [GONE]

    left_size, right_size, total = {}, {}, 0
    for item in ribbons:
        left_size[item["source"]] = left_size.get(item["source"], 0) + item["units"]
        right_size[item["target"]] = right_size.get(item["target"], 0) + item["units"]
        total += item["units"]

    top, height, gap = Inches(1.72), Inches(4.55), Inches(0.12)
    node_w = Inches(0.20)
    left_x, right_x = Inches(3.15), Inches(9.55)

    left = stack(left_order, left_size, total, top, height, gap)
    right = stack(right_order, right_size, total, top, height, gap)

    # Ribbons first, so the thin ones sit over the fat ones rather than under.
    used_l, used_r = {}, {}
    for item in sorted(ribbons, key=lambda r: -r["units"]):
        a, b = left.get(item["source"]), right.get(item["target"])
        if not a or not b:
            continue
        thick = max((item["units"] / total) * (height - gap * 4), Inches(0.02))
        y1 = a["y"] + used_l.get(item["source"], 0)
        y2 = b["y"] + used_r.get(item["target"], 0)
        used_l[item["source"]] = used_l.get(item["source"], 0) + thick
        used_r[item["target"]] = used_r.get(item["target"], 0) + thick
        ribbon(slide, left_x + node_w, y1, right_x, y2, thick,
               colour_of(item["source"], data))

    for bands, x, align_left in ((left, left_x, False), (right, right_x, True)):
        for key, spec in bands.items():
            band(slide, x, spec["y"], node_w, spec["h"], colour_of(key, data))
            label = "{}   {}".format(name_of(key, data), spec["n"])
            # The left column's labels sit left of its band, so the box has to
            # start at the margin and be as wide as the gap — anchoring it at
            # x - width put it off the slide, which python-pptx accepts and
            # PowerPoint then renders as nothing.
            from pptx.enum.text import PP_ALIGN
            if align_left:
                box = textbox(slide, x + node_w + Inches(0.10),
                              spec["y"] + spec["h"] / 2 - Inches(0.11),
                              Inches(3.2), Inches(0.24),
                              [[(label, {"size": 10.5})]], space=0)
            else:
                width = x - MARGIN - Inches(0.12)
                box = textbox(slide, MARGIN,
                              spec["y"] + spec["h"] / 2 - Inches(0.11),
                              width, Inches(0.24),
                              [[(label, {"size": 10.5})]], space=0)
                box.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT

    textbox(slide, Inches(0.55), Inches(1.36), Inches(3.0), Inches(0.3),
            [[("MLT RESULT", {"size": 9.5, "color": MUTE, "bold": True})]],
            space=0)
    textbox(slide, Inches(9.80), Inches(1.36), Inches(3.0), Inches(0.3),
            [[("HTT RESULT", {"size": 9.5, "color": MUTE, "bold": True})]],
            space=0)

    biggest = max(ribbons, key=lambda r: r["units"])
    loss = [r for r in ribbons
            if r["source"] == "pass" and r["target"] == "bonepile"]
    notes = [
        "Ribbon width is units. The two grey bands are not results: “did not "
        "reach HTT” is a unit MLT saw and HTT did not — mostly correct, since a "
        "module that failed MLT should not be at HTT — and “not seen at MLT” "
        "arrived from before this week.",
        "Largest flow: {} units, {} at MLT to {} at HTT.".format(
            biggest["units"], name_of(biggest["source"], data),
            name_of(biggest["target"], data)),
    ]
    if loss:
        notes.append(
            "{} units passed MLT first time and are now in the HTT bonepile — "
            "the single biggest loss on this chart, and it is not a retest "
            "problem.".format(loss[0]["units"]))
    textbox(slide, Inches(0.55), Inches(6.42), Inches(12.2), Inches(0.9),
            [[(text, {"size": 10, "color": MUTE})] for text in notes], space=2)
    return slide


def tally_slide(prs, data, week):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    textbox(slide, Inches(0.55), Inches(0.30), Inches(12.2), Inches(0.9), [
        [("Result types", {"size": 25, "bold": True})],
        [("{} · {} to {} · one outcome per unit per station"
          .format(week["week"], week["from"], week["to"]),
          {"size": 12, "color": MUTE})],
    ], space=2)
    rule(slide, Inches(0.55), Inches(1.22), Inches(12.2))

    exclusive = data.get("exclusive") or []
    for index, row in enumerate(week.get("stations") or []):
        x = Inches(0.55 + index * 6.35)
        counts = row.get("counts") or {}
        textbox(slide, x, Inches(1.50), Inches(6.0), Inches(0.5), [
            [(row["label"], {"size": 17, "bold": True}),
             ("    {} units".format(row["units"]),
              {"size": 11, "color": MUTE})],
        ], space=2)

        # One bar, four segments. Proportions are the point.
        bar_y, bar_h, bar_w = Inches(2.10), Inches(0.30), Inches(5.9)
        at = x
        for key in exclusive:
            n = counts.get(key) or 0
            if not n:
                continue
            span = bar_w * n / row["units"] if row["units"] else 0
            band(slide, at, bar_y, span, bar_h, colour_of(key, data))
            at += span

        lines = []
        for key in exclusive:
            n = counts.get(key) or 0
            share = ("{:.0f}%".format(100 * n / row["units"])
                     if row["units"] else "—")
            colour = INK if n else MUTE
            lines.append([
                ("{:<14}".format(name_of(key, data)),
                 {"size": 12, "color": colour}),
                ("{:>6}".format(n), {"size": 14, "bold": True,
                                     "color": colour}),
                ("{:>7}".format(share), {"size": 11, "color": MUTE}),
            ])
        textbox(slide, x, Inches(2.62), Inches(6.0), Inches(1.7), lines,
                space=6)

        back = counts.get("retest-pass") or 0
        said = ("{} of {} first-attempt failures came back ({}){}".format(
            back, row["fail"],
            "—" if row["recoveryRate"] is None
            else "{:.1f}%".format(row["recoveryRate"] * 100),
            " — {} on the same build, {} on a new one.".format(
                row["sameRelease"], row["differentRelease"]) if back else ".")
            if row["fail"] else "Nothing failed its first attempt.")
        textbox(slide, x, Inches(4.44), Inches(6.0), Inches(0.7),
                [[(said, {"size": 11, "color": MUTE})]], space=2)

    textbox(slide, Inches(0.55), Inches(6.42), Inches(12.2), Inches(0.9), [
        [("Pass is a first attempt that passed. Retest Pass failed first and "
          "passed later — back in the flow, at the cost of a second insertion, "
          "which is why it is amber and not a second green. Bonepile failed "
          "first and has never passed: no retest, or every retest failed.",
          {"size": 10, "color": MUTE})],
        [("Fail is not a fifth type — it is Retest Pass plus Bonepile. MLT and "
          "HTT only; TIM is a bake and is reported separately.",
          {"size": 10, "color": MUTE})],
    ], space=2)
    return slide


def trend_slide(prs, data, weeks):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    textbox(slide, Inches(0.55), Inches(0.30), Inches(12.2), Inches(0.9), [
        [("Result types week over week", {"size": 25, "bold": True})],
        [("MLT · the share of each week in each outcome, and how much of the "
          "week's first-attempt failure came back",
          {"size": 12, "color": MUTE})],
    ], space=2)
    rule(slide, Inches(0.55), Inches(1.22), Inches(12.2))

    exclusive = data.get("exclusive") or []
    rows = []
    for week in weeks:
        for row in week.get("stations") or []:
            if row["key"] == "mlt":
                rows.append((week["week"], row))
    top, pitch, bar_h = Inches(1.62), Inches(0.62), Inches(0.34)
    bar_x, bar_w = Inches(1.72), Inches(8.6)

    for index, (label, row) in enumerate(rows):
        y = top + pitch * index
        textbox(slide, Inches(0.55), y + Inches(0.03), Inches(1.1),
                Inches(0.3), [[(label, {"size": 11})]], space=0)
        counts = row.get("counts") or {}
        at = bar_x
        for key in exclusive:
            n = counts.get(key) or 0
            if not n:
                continue
            span = bar_w * n / row["units"] if row["units"] else 0
            band(slide, at, y, span, bar_h, colour_of(key, data))
            at += span
        textbox(slide, bar_x + bar_w + Inches(0.18), y + Inches(0.03),
                Inches(2.6), Inches(0.3), [[
                    ("{} units".format(row["units"]),
                     {"size": 10, "color": MUTE}),
                    ("    {} back".format(
                        "—" if row["recoveryRate"] is None
                        else "{:.0f}%".format(row["recoveryRate"] * 100)),
                     {"size": 11, "bold": True}),
                ]], space=0)

    first, last = rows[0], rows[-1]
    textbox(slide, Inches(0.55), Inches(6.42), Inches(12.2), Inches(0.9), [
        [("Recovery went from {} of {} first-attempt failures in {} to {} of "
          "{} in {}. The bonepile share is what is left on the floor."
          .format(first[1]["counts"].get("retest-pass"), first[1]["fail"],
                  first[0], last[1]["counts"].get("retest-pass"),
                  last[1]["fail"], last[0]),
          {"size": 10.5, "color": MUTE})],
    ], space=2)
    return slide


def main(argv):
    wanted = [arg for arg in argv[1:] if arg.startswith("2026-W")] or None
    data = load()
    weeks = data.get("weeks") or []
    if not weeks:
        raise SystemExit("no weeks in {} — run `make outcomes`".format(BUNDLE))
    if wanted:
        weeks = [w for w in weeks if w["week"] in wanted]
        if not weeks:
            raise SystemExit("none of {} in the bundle".format(wanted))

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    for week in weeks:
        tally_slide(prs, data, week)
        flow_slide(prs, data, week)
    if len(data["weeks"]) > 1:
        trend_slide(prs, data, data["weeks"])

    OUT_DIR.mkdir(exist_ok=True)
    label = "-".join(w["week"] for w in weeks)
    out = OUT_DIR / "result-types-{}.pptx".format(label)
    prs.save(out)
    print("{} — {} slides, {} KB".format(
        out, len(prs.slides._sldIdLst), out.stat().st_size // 1024))
    for week in weeks:
        for row in week.get("stations") or []:
            counts = row["counts"]
            print("  {} {:<4} pass {:>4}  retest-pass {:>3}  bonepile {:>4}  "
                  "no-result {:>3}".format(
                      week["week"], row["label"], counts["pass"],
                      counts["retest-pass"], counts["bonepile"],
                      counts["no-result"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
