# Visualization decisions

Why the dashboard looks the way it does, so the next change does not undo a
deliberate choice.

## Palette

The categorical slots, status tokens, surfaces and ink are a validated reference
palette, declared once as CSS custom properties at the top of
`dashboard/styles.css` and referenced by role everywhere else. Dark values are a
**selected** set of steps for the dark surface, not an automatic inversion, and
are declared under both `@media (prefers-color-scheme: dark)` and
`:root[data-theme="dark"]` so the in-page toggle wins in both directions.

| Slot | Light | Dark |
|---|---|---|
| series-1 blue | `#2a78d6` | `#3987e5` |
| series-2 orange | `#eb6834` | `#d95926` |
| series-3 aqua | `#1baf7a` | `#199e70` |
| series-4 yellow | `#eda100` | `#c98500` |
| series-5 magenta | `#e87ba4` | `#d55181` |
| series-6 green | `#008300` | `#008300` |
| series-7 violet | `#4a3aa7` | `#9085e9` |

Status tokens are fixed in both modes and never reused as a series color:
good `#0ca30c`, warning `#fab219`, serious `#ec835a`, critical `#d03b3b`.

> **Not independently re-validated here.** The palette's colorblind-separation
> checks ship as a Node script, and this machine has no Node runtime — the values
> above are used exactly as documented, unmodified, which is the condition under
> which their validation holds. If you change a hex, re-run the validator before
> shipping.

## Rules the charts follow

- **One y-axis per plot, always.** Two measures of different scale get two
  charts. This is why the Pareto has no cumulative-% line and why throughput and
  yield are separate cards.
- **Color follows the entity, not its rank.** Station colors are assigned once
  from the whole dataset (`STATION_COLORS` in `app.js`) and reused for every
  slice. Filtering to 12 hours must not repaint the survivors.
- **Hues are never cycled or generated.** Past seven stations the tail folds into
  a neutral "Other (n stations)".
- **Status color where the color *means* status.** The outcome chart uses
  good/serious/critical because its segments literally are pass/error/fail; the
  station chart uses categorical slots because its segments are identities.
- **Marks stay thin.** Columns cap at 24px, lines are 2px, markers are ≥8px with
  a 2px surface ring, gridlines are solid hairlines one step off the surface.
- **White does the separating.** A 2px surface gap sits between stacked segments;
  no borders are drawn around marks.
- **Labels are selective.** Lines are direct-labelled at the endpoint only (with
  a leader line when endpoints converge); the axis, legend and tooltip carry the
  rest. Never a number on every point.
- **Text never wears the data color.** Values and labels use ink tokens; identity
  comes from the colored mark beside them.

## Interaction

- One filter row above everything it scopes. Every stat, chart and table
  re-renders from the same slice, so the numbers always agree.
- Line charts get a snapping crosshair and a tooltip listing **every** series at
  that hour; column and bar charts get a per-mark tooltip with a full-height hit
  target far larger than the mark.
- Tooltips enhance, never gate: **every chart has a table view** with the same
  numbers, and that is also the mitigation for the light-mode palette steps that
  sit below 3:1 contrast on the light surface.
- Keyboard parity without a hundred tab stops: each plot is one focus stop, and
  ←/→/Home/End walk the cursor firing the same readout hover does.

## Data flow

The bundle in `dashboard/data/metrics.js` is **run-level, not pre-aggregated** —
the filter row has to re-slice it, and aggregating in the browser is the only way
every card stays consistent with every other. It is written as JavaScript rather
than JSON so the page also opens straight off disk (`fetch()` of a local `.json`
is blocked by CORS).
