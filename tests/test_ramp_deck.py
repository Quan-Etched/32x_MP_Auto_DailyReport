"""The deck layouts, checked as geometry rather than by opening PowerPoint.

WHY THIS EXISTS
draw_flow places boxes into a dict keyed by label and then draws only the wires
whose endpoints are in that dict. A typo in a wire — "FAT/SFT" for "FAT / SFT",
"ASSY" where the lane suffix was needed — does not raise. The wire is simply not
drawn, and the slide looks finished: one arrow short, on a chart with thirty.
That is the bug class this file is for.

The same silence applies to two boxes claiming one key: the second overwrites
the first in the dict, every wire aimed at the first lands on the second, and
the chart is wrong rather than incomplete. "PDB" appears twice in the L6 lane on
the end-to-end chart — once as the board, once as the checkpoint — which is
exactly how that would have happened, so the checkpoint is labelled "PDB CK".

Overlap and off-slide are checked here too, because the layouts are inch
coordinates typed by hand and a slide is a fixed size.
"""

import unittest

try:
    from tools import build_ramp_deck as ramp
    from tools import build_weekly_deck as deck
except ImportError:                                   # python-pptx not installed
    ramp = deck = None

SLIDE_W, SLIDE_H = 13.333, 7.5


def rects(lanes, geom):
    """(key, lane title, x, y, w, h) for every box, keyed as draw_flow keys it."""
    row0, pitch, box_h = geom
    out = []
    for lane in lanes:
        for box in lane["boxes"]:
            key = SUFFIX_FOR[id(lanes)].get((lane["title"], box["label"]),
                                            box["label"])
            out.append((key, lane["title"], box["x"],
                        row0 + pitch * box["row"], box["w"], box_h))
    return out


SUFFIX_FOR = {}


def layouts():
    """The two charts, as (name, lanes, wires, suffix, geom)."""
    return [
        ("ramp", deck.LANES, deck.WIRES, deck.SUFFIX, deck.GEOM),
        ("end-to-end", ramp.E2E_LANES, ramp.E2E_WIRES, ramp.E2E_SUFFIX,
         ramp.E2E_GEOM),
    ]


@unittest.skipIf(ramp is None, "python-pptx not installed")
class LayoutTest(unittest.TestCase):

    def boxes(self, lanes, suffix, geom):
        SUFFIX_FOR[id(lanes)] = suffix
        return rects(lanes, geom)

    def test_every_box_key_is_unique(self):
        """Two boxes with one key silently collapse into one."""
        for name, lanes, _, suffix, geom in layouts():
            keys = [b[0] for b in self.boxes(lanes, suffix, geom)]
            dupes = sorted({k for k in keys if keys.count(k) > 1})
            self.assertEqual([], dupes,
                             "{}: duplicate box keys {} — the later box wins "
                             "and every wire aimed at the earlier one moves"
                             .format(name, dupes))

    def test_every_wire_endpoint_exists(self):
        """A misspelt endpoint drops the wire without a word."""
        for name, lanes, wires, suffix, geom in layouts():
            keys = {b[0] for b in self.boxes(lanes, suffix, geom)}
            for wire in wires:
                for end in wire[:2]:
                    self.assertIn(end, keys,
                                  "{}: wire endpoint {!r} names no box, so "
                                  "the wire is skipped and the chart is one "
                                  "arrow short".format(name, end))

    def test_no_box_is_orphaned(self):
        """A box with no wire either way is drawn floating."""
        for name, lanes, wires, suffix, geom in layouts():
            wired = {end for wire in wires for end in wire[:2]}
            for key, _, _, _, _, _ in self.boxes(lanes, suffix, geom):
                self.assertIn(key, wired,
                              "{}: {} has no wire in or out".format(name, key))

    def test_boxes_fit_on_the_slide(self):
        for name, lanes, _, suffix, geom in layouts():
            for key, _, x, y, w, h in self.boxes(lanes, suffix, geom):
                self.assertGreaterEqual(x, 0, "{}: {}".format(name, key))
                self.assertGreaterEqual(y, 0, "{}: {}".format(name, key))
                self.assertLessEqual(x + w, SLIDE_W,
                                     "{}: {} runs off the right edge"
                                     .format(name, key))
                # Room left under the last row for the footnote.
                self.assertLessEqual(y + h, SLIDE_H - 1.0,
                                     "{}: {} runs into the footnote"
                                     .format(name, key))

    def test_no_two_boxes_overlap(self):
        for name, lanes, _, suffix, geom in layouts():
            boxes = self.boxes(lanes, suffix, geom)
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    ak, _, ax, ay, aw, ah = boxes[i]
                    bk, _, bx, by, bw, bh = boxes[j]
                    over_x = min(ax + aw, bx + bw) - max(ax, bx)
                    over_y = min(ay + ah, by + bh) - max(ay, by)
                    self.assertFalse(
                        over_x > 0.01 and over_y > 0.01,
                        "{}: {} and {} overlap by {:.2f}x{:.2f}in"
                        .format(name, ak, bk, over_x, over_y))

    def test_lane_dividers_fall_between_columns(self):
        """A divider drawn through a box reads as a strike-through."""
        for name, lanes, _, suffix, geom in layouts():
            boxes = self.boxes(lanes, suffix, geom)
            for lane in lanes:
                x = lane["divider"]
                if x is None:
                    continue
                for key, _, bx, _, bw, _ in boxes:
                    self.assertFalse(
                        bx < x < bx + bw,
                        "{}: the divider at {}in crosses {}"
                        .format(name, x, key))

    def test_end_to_end_draws_every_station_the_weekly_chart_does(self):
        """The detailed chart may add stations. It may never lose one."""
        def stations(lanes):
            found = set()
            for lane in lanes:
                for box in lane["boxes"]:
                    found.update(box.get("stations",
                                         [box["station"]] if box.get("station")
                                         else []))
            return found

        missing = stations(deck.LANES) - stations(ramp.E2E_LANES)
        self.assertEqual(set(), missing,
                         "the end-to-end chart drops {} — it is the chart "
                         "people read to see what is measured".format(missing))

    def test_end_to_end_adds_the_stations_it_is_for(self):
        """It exists to draw TIM and the split of Flash from BFT."""
        labels = {box["label"] for lane in ramp.E2E_LANES
                  for box in lane["boxes"]}
        for wanted in ("TIM", "Flash", "BFT", "CK", "PDB CK",
                       "2U Component", "2U System"):
            self.assertIn(wanted, labels)


if __name__ == "__main__":
    unittest.main()
