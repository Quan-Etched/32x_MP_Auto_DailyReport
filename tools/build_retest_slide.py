#!/usr/bin/env python3
"""Add the retest / bonepile-recovery slide to the weekly deck.

WHY THIS ANSWERS A SLACK MESSAGE
Chris Zhu asked, on 2026-08-23:

    Do we also have some re-test data (which, I assume is primarily at the L6
    level)? Specifically, what % of first-pass-failed units are recovered from
    the bonepile and added back to production flow.

and the reply was to check "first fail and then pass (with same or different
software release)". So the slide answers exactly that, in that order: the share
recovered, and then the split that says what recovered them.

The split is the finding, not decoration. Recovered on the SAME release means
the first failure did not reproduce — the unit was probably always good and the
test let it through the second time, which is a test-escape question. Recovered
on a DIFFERENT release means a software fix released it, which is a schedule
item. A single "recovery rate" hides which of those is happening, and for W34
the answer is mostly the first.

APPENDS RATHER THAN REBUILDS
The current deck is hand-edited (weekly-2026-W34_V2.pptx: the flow slide has
callouts nobody generated). So this opens it, appends one slide, and writes a
new file — the hand work is preserved and the generated slide carries the
numbers. It never overwrites its input.
"""

from __future__ import annotations

import json
import pathlib
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

REPO = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = REPO / "dashboard" / "data" / "weekly.js"
DECKS = REPO / "decks"

#: The stations Chris meant by "primarily at the L6 level", in flow order.
#: MLT and HTT only — TIM is a bake, its repeats are a soak being re-run rather
#: than a module being given a second chance, and putting it on this slide
#: invited its number to be read as the same kind of thing.
STATIONS = ("mlt", "htt")

INK = RGBColor(0x1F, 0x1F, 0x1F)
MUTE = RGBColor(0x6B, 0x6B, 0x6B)
GOOD = RGBColor(0x1E, 0x7B, 0x36)
WARN = RGBColor(0xB5, 0x6E, 0x00)
BAD = RGBColor(0xC0, 0x39, 0x2B)
RULE = RGBColor(0xD8, 0xD6, 0xD0)


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
        raise SystemExit("no week {} in the bundle".format(week_label))
    return data, weeks[0]


def pct(value, places=1):
    if value is None:
        return "—"
    return "{:.{}f}%".format(value * 100, places)


def tone(rate):
    """Recovery is good when high — the opposite of a failure rate."""
    if rate is None:
        return MUTE
    if rate >= 0.5:
        return GOOD
    if rate >= 0.15:
        return WARN
    return BAD


def textbox(slide, x, y, w, h, lines, space=4, align=None):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    for index, line in enumerate(lines):
        para = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        para.space_after = Pt(space)
        if align is not None:
            para.alignment = align
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


def retest_slide(prs, week, rows):
    slide = prs.slides.add_slide(prs.slide_layouts[0])       # BLANK

    textbox(slide, Inches(0.55), Inches(0.30), Inches(12.2), Inches(0.9), [
        [("Retest — recovery from the bonepile", {"size": 26, "bold": True})],
        [("{} · {} to {} · L6 module line".format(
            week["week"], week["from"], week["endsOn"]),
          {"size": 12.5, "color": MUTE})],
    ], space=2)
    rule(slide, Inches(0.55), Inches(1.24), Inches(12.2))

    # The question, quoted. It is the reason the slide exists and the wording
    # is what everyone agreed to measure.
    textbox(slide, Inches(0.55), Inches(1.42), Inches(12.2), Inches(0.5), [
        [("Asked: ", {"size": 11, "bold": True, "color": MUTE}),
         ("“what % of first-pass-failed units are recovered from the "
          "bonepile and added back to production flow”",
          {"size": 11, "color": MUTE})],
    ], space=0)

    # One column per station.
    left, width, gap = 0.55, 3.9, 0.35
    for index, row in enumerate(rows):
        bone = row.get("bonepile") or {}
        failed = bone.get("firstPassFailed") or 0
        back = bone.get("recovered") or 0
        rate = bone.get("recoveryRate")
        x = Inches(left + index * (width + gap))

        textbox(slide, x, Inches(2.12), Inches(width), Inches(0.4), [
            [(row["label"], {"size": 15, "bold": True})],
            [("first-pass yield {} · {} units".format(
                pct(row["fpy"]), row["units"]), {"size": 10, "color": MUTE})],
        ], space=1)

        textbox(slide, x, Inches(2.78), Inches(width), Inches(0.95), [
            [(pct(rate), {"size": 40, "bold": True, "color": tone(rate)})],
            [("{} of {} first-pass failures came back".format(back, failed),
              {"size": 11, "color": MUTE})],
        ], space=2)

        # The split. Named even when it is zero, because "0 on a new build" is
        # the statement that no software fix has released anything yet.
        same = bone.get("sameRelease") or 0
        other = bone.get("differentRelease") or 0
        lines = [[("What brought them back",
                   {"size": 10.5, "bold": True, "color": MUTE})]]
        if back:
            lines.append([
                ("{}".format(same), {"size": 15, "bold": True}),
                ("  same software release — the first failure did not "
                 "reproduce", {"size": 10.5})])
            lines.append([
                ("{}".format(other), {"size": 15, "bold": True}),
                ("  a different release — a fix released the unit",
                 {"size": 10.5})])
        else:
            lines.append([("Nothing has been recovered yet.",
                           {"size": 11, "color": MUTE})])
        lines.append([("{} still in the bonepile".format(
            bone.get("stillOut") or 0), {"size": 11, "bold": True,
                                         "color": BAD})])
        textbox(slide, x, Inches(3.92), Inches(width), Inches(1.9), lines,
                space=5)

    rule(slide, Inches(0.55), Inches(5.98), Inches(12.2))

    # What the numbers mean, and what they do not. The definition has to travel
    # with the figure: a recovery rate quoted without its population is the
    # thing that gets misread in a meeting.
    tim, mlt, htt = (next((r for r in rows if r["key"] == k), None)
                     for k in ("tim", "mlt", "htt"))
    same_share = None
    if mlt and (mlt.get("bonepile") or {}).get("recovered"):
        bone = mlt["bonepile"]
        same_share = bone["sameRelease"] / bone["recovered"]

    findings = []
    if same_share is not None and same_share >= 0.5:
        findings.append(
            "Most of what comes back at MLT passes on the build it failed on, "
            "so the recovery we have is mostly first failures not reproducing "
            "rather than fixes landing.")
    if htt and (htt.get("bonepile") or {}).get("firstPassFailed"):
        if not (htt["bonepile"].get("recovered") or 0):
            findings.append(
                "Nothing has come back at HTT: all {} first-pass failures are "
                "still out.".format(htt["bonepile"]["firstPassFailed"]))
    findings.append(
        "Counted per station against each unit's first attempt this week, the "
        "same population the first-pass yield uses — so first-pass failures "
        "and yield reconcile. A module that failed MLT and later passed MLT is "
        "recovered here even if it then failed HTT; the all-hands page counts "
        "recovery per stage and reads lower for MLT + HTT for that reason.")

    textbox(slide, Inches(0.55), Inches(6.14), Inches(12.2), Inches(1.0),
            [[(text, {"size": 10.5, "color": MUTE})] for text in findings],
            space=3)
    return slide


def main(argv):
    source = pathlib.Path(argv[1]) if len(argv) > 1 else None
    label = argv[2] if len(argv) > 2 else None
    if source is None:
        candidates = sorted(DECKS.glob("weekly-*.pptx"))
        if not candidates:
            raise SystemExit("no weekly-*.pptx in {}".format(DECKS))
        source = candidates[-1]
    if not source.exists():
        raise SystemExit("no such deck: {}".format(source))

    data, week = load(label)
    by_key = {row["key"]: row for row in week["rows"]}
    rows = [by_key[key] for key in STATIONS if key in by_key]
    if not rows:
        raise SystemExit("none of {} in {}".format(STATIONS, week["week"]))

    prs = Presentation(str(source))
    retest_slide(prs, week, rows)

    out = DECKS / "{}_retest.pptx".format(source.stem)
    prs.save(out)
    print("{} -> {} ({} slides, {} KB)".format(
        source.name, out.name, len(prs.slides._sldIdLst),
        out.stat().st_size // 1024))
    for row in rows:
        bone = row.get("bonepile") or {}
        print("  {:<5} first-pass failed {:>3}   recovered {:>3} ({})   "
              "same build {:>2}   new build {:>2}   still out {:>3}".format(
                  row["label"], bone.get("firstPassFailed"),
                  bone.get("recovered"), pct(bone.get("recoveryRate")),
                  bone.get("sameRelease"), bone.get("differentRelease"),
                  bone.get("stillOut")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
