#!/usr/bin/env python3
"""The two-slide ramp deck the all-hands page hands out.

WHY THIS IS SEPARATE FROM build_weekly_deck
The weekly deck is the long form — metrics, actions, appendix, five slides of
it. What gets pasted into the all-hands is two slides: the ramp status flow
with this week's numbers in the boxes, and the end-to-end flow behind it. Asked
for a deck, someone wants those two and not the other three, and wants them
editable rather than a screenshot of the web page.

Everything is drawn with build_weekly_deck's primitives, so a change to how a
box reports a yield lands on both decks at once. The only thing this file owns
is the end-to-end layout — the one chart the weekly deck does not draw.

Output goes to decks/, next to the weekly deck, and publish.sh copies it into
the web root as data/32x-ramp-latest.pptx. It cannot be written straight into
dashboard/data/: that directory is excluded from the rsync to the box, because
the box generates those bundles itself — and it cannot be built on the box,
which has no python-pptx and is not going to get one for the hourly pipeline.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pptx import Presentation
from pptx.util import Inches

from tools.build_weekly_deck import (
    GEOM, LANES, MUTE, SUFFIX, W, H, WIRES,
    draw_flow, footnote, load, textbox, title_slide,
)

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "decks"

#: Where the deck lives for the people who are told to go and get it.
GO_LINK = "go/32x-ramp"

#: The end-to-end chart, transcribed from dashboard/flowe2e.js so the slide and
#: the page draw the same graph. Eight rows against the weekly slide's five, so
#: it gets its own geometry: at the weekly pitch, row 7 hangs off the slide.
#:
#: Columns, left to right, with the gutters that carry the long risers:
#:   ASIC 0.58   L6 2.10 / 3.48 / 4.92   [5.50-5.76]   2U/4U 5.88
#:   [7.30-7.48]   6U 7.48 / 9.04   L11 10.50
E2E_GEOM = (1.52, 0.63, 0.52)
E2E_HEAD_Y = 0.96
E2E_BOTTOM = 6.50

E2E_LANES = [
    {"title": "ASIC", "owner": "@Sigurd", "divider": 1.98, "boxes": [
        {"label": "ASIC", "x": 0.58, "w": 1.28, "row": 0, "kind": "build"},
        {"label": "WST",  "x": 0.58, "w": 1.28, "row": 1, "kind": "test",
         "external": "wst", "note": "Wafer sort"},
        {"label": "FT",   "x": 0.58, "w": 1.28, "row": 2, "kind": "test",
         "external": "ft", "note": "Final test"},
        {"label": "SLT",  "x": 0.58, "w": 1.28, "row": 3, "kind": "test",
         "note": "at Sigurd"},
    ]},
    {"title": "PCBA L6", "owner": "@Pega", "divider": 5.76, "boxes": [
        # Column 1: the four boards SMT/ICT builds. The comprehensive chart
        # draws them as one box; here each has its own, because they leave for
        # three different places and only one of them goes near the module line.
        {"label": "BB",  "x": 2.10, "w": 1.24, "row": 0, "kind": "build",
         "note": "SMT / ICT"},
        {"label": "HPB", "x": 2.10, "w": 1.24, "row": 1, "kind": "build",
         "note": "SMT / ICT"},
        {"label": "PV1", "x": 2.10, "w": 1.24, "row": 5, "kind": "build",
         "note": "SMT / ICT"},
        {"label": "VBB", "x": 2.10, "w": 1.24, "row": 6, "kind": "build",
         "note": "SMT / ICT"},
        {"label": "PDB", "x": 2.10, "w": 1.24, "row": 7, "kind": "build",
         "note": "SMT / ICT"},
        # Column 2: the module line, ascending, as the line draws it.
        {"label": "HTT", "x": 3.48, "w": 1.30, "row": 2, "kind": "test",
         "station": "htt"},
        {"label": "MLT", "x": 3.48, "w": 1.30, "row": 3, "kind": "test",
         "station": "mlt"},
        {"label": "TIM", "x": 3.48, "w": 1.30, "row": 4, "kind": "test",
         "station": "tim", "note": "Coldplate bake"},
        {"label": "PV1 ASSY", "x": 3.48, "w": 1.30, "row": 5, "kind": "build"},
        # ROT OTP, production certificate, bootloader lock — the VBB
        # provisioning suites this repo does collect.
        {"label": "Flash", "x": 3.48, "w": 1.30, "row": 6, "kind": "flash",
         "station": "vbb_provision", "note": "OTP · cert · lock BL"},
        # Column 3: checkpoints and the board functional test. None of the
        # three reports to a controller, and each has its own box so that shows
        # — drawn inside a neighbour they borrow its yield.
        {"label": "CK",  "x": 4.92, "w": 0.58, "row": 2, "kind": "test",
         "note": "not collected"},
        {"label": "BFT", "x": 4.92, "w": 0.58, "row": 5, "kind": "test",
         "note": "not collected · ETCH-39584"},
        {"label": "PDB CK", "x": 4.92, "w": 0.58, "row": 7, "kind": "test",
         "note": "not collected"},
    ]},
    {"title": "FATP L10 2U/4U", "owner": "", "divider": 7.36, "boxes": [
        {"label": "4U ASSY", "x": 5.88, "w": 1.42, "row": 0, "kind": "build"},
        {"label": "2U ASSY", "x": 5.88, "w": 1.42, "row": 1, "kind": "build"},
        # Same station key as 2U System, one insertion earlier. The number is
        # printed once, at 6U, so the two boxes cannot disagree.
        {"label": "2U Component", "x": 5.88, "w": 1.42, "row": 2,
         "kind": "test", "note": "counted with 2U System"},
    ]},
    {"title": "FATP L10 6U", "owner": "", "divider": 10.38, "boxes": [
        {"label": "SFT",  "x": 7.48, "w": 1.42, "row": 0, "kind": "test",
         "station": "l10_sft"},
        {"label": "FAT",  "x": 7.48, "w": 1.42, "row": 1, "kind": "test",
         "station": "l10_fat"},
        {"label": "2U System", "x": 7.48, "w": 1.42, "row": 2, "kind": "test",
         "station": "l10_2u"},
        {"label": "ASSY", "x": 7.48, "w": 1.42, "row": 3, "kind": "build"},
        {"label": "Runin", "x": 9.04, "w": 1.24, "row": 0, "kind": "test",
         "station": "l10_rin"},
    ]},
    {"title": "Rack L11", "owner": "", "divider": None, "boxes": [
        {"label": "ASSY", "x": 10.50, "w": 1.55, "row": 0, "kind": "build"},
        {"label": "Provision", "x": 10.50, "w": 1.55, "row": 1, "kind": "test",
         "station": "l11_provision"},
        # FAT, SFT and Runin at L11 are one station key. Printing it three
        # times would read as three measurements of three things.
        {"label": "FAT",   "x": 10.50, "w": 1.55, "row": 2, "kind": "test",
         "station": "l11_test"},
        {"label": "SFT",   "x": 10.50, "w": 1.55, "row": 3, "kind": "test",
         "note": "counted with FAT"},
        {"label": "Runin", "x": 10.50, "w": 1.55, "row": 4, "kind": "test",
         "note": "counted with FAT"},
        {"label": "Pack",  "x": 10.50, "w": 1.55, "row": 5, "kind": "pack"},
    ]},
]

E2E_SUFFIX = {("FATP L10 6U", "SFT"): "SFT@6U",
              ("FATP L10 6U", "FAT"): "FAT@6U",
              ("FATP L10 6U", "Runin"): "Runin@6U",
              ("FATP L10 6U", "ASSY"): "ASSY@6U",
              ("Rack L11", "FAT"): "FAT@L11",
              ("Rack L11", "SFT"): "SFT@L11",
              ("Rack L11", "Runin"): "Runin@L11",
              ("Rack L11", "ASSY"): "ASSY@L11"}

#: from, to, route, label, dx, over_top. The dx values are not decoration: the
#: 2U/4U lane is one column deep, so anything reaching it from below runs
#: through the box above its target. Those wires are nudged into the gutter
#: between the lanes and come in at their target's own centre line instead.
E2E_WIRES = [
    ("ASIC", "WST", "v"), ("WST", "FT", "v"), ("FT", "SLT", "v"),
    ("FT", "PV1", "hv"),

    ("PV1", "PV1 ASSY", "h"),
    ("PV1 ASSY", "TIM", "v"), ("TIM", "MLT", "v"), ("MLT", "HTT", "v"),
    ("HTT", "CK", "h"),
    ("CK", "4U ASSY", "vh"),
    # BB runs straight across at its own row; HPB is directly under it, so its
    # wire goes over the top rather than through the BB box.
    ("BB", "4U ASSY", "h"),
    ("HPB", "4U ASSY", "over", None, 0.0, 1.30),

    ("VBB", "Flash", "h"), ("Flash", "BFT", "hv"),
    ("BFT", "4U ASSY", "vh", None, 0.37),

    ("PDB", "PDB CK", "h"),
    ("PDB CK", "2U ASSY", "vh", None, 0.47),

    ("2U ASSY", "2U Component", "v"),
    ("4U ASSY", "ASSY@6U", "vh", None, 0.83),
    ("2U Component", "ASSY@6U", "vh"),

    ("ASSY@6U", "2U System", "v"), ("2U System", "FAT@6U", "v"),
    ("FAT@6U", "SFT@6U", "v"), ("SFT@6U", "Runin@6U", "h"),
    ("Runin@6U", "ASSY@L11", "h"),

    ("ASSY@L11", "Provision", "v"), ("Provision", "FAT@L11", "v"),
    ("FAT@L11", "SFT@L11", "v"), ("SFT@L11", "Runin@L11", "v"),
    ("Runin@L11", "Pack", "v"),
]


def ramp_slide(prs, data, week, by_station, external):
    """Slide 1 — the status flow, in the format the all-hands already uses."""
    slide = title_slide(
        prs,
        "32x Ramp Status ({})".format(week["week"]),
        "{} to {}{} · first-pass yield and units, in the box · UTC".format(
            week["from"], week["endsOn"],
            ", week still running" if week["partial"] else ""))
    draw_flow(slide, LANES, WIRES, SUFFIX, by_station, external, data)
    footnote(slide, data, week)
    textbox(slide, W - Inches(3.0), Inches(0.46), Inches(2.4), Inches(0.3),
            [[("Link: ", {"size": 11, "color": MUTE}),
              (GO_LINK, {"size": 11, "bold": True})]], space=0)
    return slide


def e2e_slide(prs, data, week, by_station, external):
    """Slide 2 — the same week, drawn over every station on the line."""
    slide = title_slide(
        prs,
        "End-to-end test flow",
        "{} · every insertion, including the ones nothing reports · "
        "grey test boxes are not collected".format(week["week"]))
    draw_flow(slide, E2E_LANES, E2E_WIRES, E2E_SUFFIX, by_station, external,
              data, E2E_GEOM, E2E_HEAD_Y, E2E_BOTTOM)
    textbox(slide, Inches(0.58), Inches(6.62), W - Inches(1.16), Inches(0.6), [
        [("Flash and BFT are two boxes, not one. ", {"size": 8.5, "bold": True,
                                                     "color": MUTE}),
         ("Flash is the VBB provisioning we collect — ROT OTP, production "
          "certificate, bootloader lock. BFT is I2C, UART, GPIO, power-on and "
          "PRBS (ETCH-39584) and reports to no controller; drawn as one box it "
          "borrowed the provisioning yield.", {"size": 8.5, "color": MUTE})],
        [("2U Component and 2U System are one station key at two insertions, "
          "and FAT / SFT / Runin at L11 are one key at three — the number is "
          "printed once so the boxes cannot disagree. Source: {}."
          .format((data.get("source") or {}).get("label", "pega2–pega6")),
          {"size": 8.5, "color": MUTE})],
    ], space=1)
    return slide


#: Slide 2, matching the all-hands page's second page and the line's own deck:
#: what is worth showing off. The serials are the floor's; what is said about
#: their state comes from the week bundle, so a rack cannot be described as
#: tested when nothing has tested it.
WIN = {
    "title": "32x Rack 2",
    "where": "Pegatron",
    "on": "2026-08-22",
    "sn": "268708630001",
    "servers": [("SS1", "268645410001"), ("SS2", "268645440007"),
                ("SS3", "268645430002"), ("SS4", "268645430004")],
}


def rack_l11_runs():
    """L11 runs against this rack's serials. None is "cannot tell".

    Read from the run bundle rather than from the week's station rows, because
    those rows are the whole line: the first version of this slide counted the
    week's L11 provision units and reported them as runs against rack 2, which
    is a different claim entirely and happened to be non-zero. If the bundle is
    not there the slide says it does not know, rather than saying zero.
    """
    bundle = REPO / "dashboard" / "data" / "runs_pega.js"
    if not bundle.exists():
        return None
    import json
    text = bundle.read_text(encoding="utf-8")
    data = json.loads(text.split("= ", 1)[1].rstrip().rstrip(";"))
    mine = {WIN["sn"]} | {serial for _, serial in WIN["servers"]}
    return sum(1 for run in data.get("runs") or []
               if str(run.get("d")) in mine
               and str(run.get("k", "")).startswith("l11"))


def win_slide(prs, data, week, by_station):
    """The achievement, as its own slide.

    Text only, and deliberately: the page has the photo, and a 250 KB JPEG in
    every weekly deck for a picture everyone in the room has already seen is a
    poor trade. What the slide carries is the part that is checkable.
    """
    tested = rack_l11_runs()

    slide = title_slide(
        prs, WIN["title"],
        "{} · {} · assembled this week".format(WIN["where"], WIN["on"]))

    textbox(slide, Inches(0.72), Inches(1.62), W - Inches(1.44), Inches(0.9), [
        [("Four Sohu servers, cabled and standing.", {"size": 17, "bold": True})],
        [("Rack serial {}".format(WIN["sn"]), {"size": 12, "color": MUTE})],
    ], space=2)

    rows = [[("Slot", {"size": 11, "bold": True, "color": MUTE}),
             ("    Serial", {"size": 11, "bold": True, "color": MUTE})]]
    for slot, serial in WIN["servers"]:
        rows.append([(slot, {"size": 13, "bold": True}),
                     ("    " + serial, {"size": 13})])
    textbox(slide, Inches(0.72), Inches(2.72), Inches(4.2), Inches(2.2),
            rows, space=3)

    # What is true, and what is not yet. The second half is the point: a slide
    # that says "rack 2 is built" and stops gets read as "rack 2 is ready".
    if tested is None:
        said = ("Assembled. Rack test state is not in this deck — the run "
                "bundle was not available when it was built; the all-hands "
                "page has it live.")
    elif tested == 0:
        said = ("Assembled, not yet tested: no controller has an L11 run "
                "against this rack or its four servers. Provisioning and rack "
                "test are still ahead of it.")
    else:
        said = ("In test: {} L11 run{} recorded against this rack and its "
                "servers so far.".format(tested, "" if tested == 1 else "s"))
    textbox(slide, Inches(5.30), Inches(2.72), W - Inches(6.02), Inches(2.2), [
        [("Where it stands", {"size": 11, "bold": True, "color": MUTE})],
        [(said, {"size": 13})],
        [("The all-hands page keeps this current from the controllers; this "
          "slide is a snapshot of {}.".format(week["week"]),
          {"size": 9, "color": MUTE})],
    ], space=4)
    return slide


def main(argv):
    label = argv[1] if len(argv) > 1 else None
    data, week = load(label)
    by_station = {row["key"]: row for row in week["rows"]}
    external = {item["key"]: item for item in (week.get("external") or [])}

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    # The order the all-hands runs in: this week, then the achievement, then
    # the detailed flow behind both.
    ramp_slide(prs, data, week, by_station, external)
    win_slide(prs, data, week, by_station)
    e2e_slide(prs, data, week, by_station, external)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "32x-ramp-{}.pptx".format(week["week"])
    prs.save(out)
    # And again at a fixed name. The page needs one URL it can hard-code — a
    # link built from a week label goes 404 the first Monday nobody rebuilds —
    # and go/32x-ramp needs somewhere to point. The week-stamped copy stays as
    # the archive.
    latest = OUT_DIR / "32x-ramp-latest.pptx"
    prs.save(latest)
    print("{} — {} slides, {} KB (also {})".format(
        out, len(prs.slides._sldIdLst), out.stat().st_size // 1024,
        latest.name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
