#!/bin/bash
# One full update: collect from EOS, ingest new test items, rebuild the
# bundles, publish to GitHub Pages.
#
# THE ONLY UPDATE PATH. Three things run it and none of them reimplement it:
#   * the hourly launchd agent (deploy/launchd/)
#   * `make update`
#   * the Update button on the locally served dashboard, via factory.control
# Kept as a wrapper rather than calling python from the plist so that logging,
# locking and the environment are handled in one visible place.
#
# Output goes to stdout as it happens *and* to data/logs/refresh.log. The button
# reads the stream to drive its progress list; launchd has no stdout and reads
# the log. `::step` markers on stdout name the stage; they are kept out of the
# log, which wants prose.
#
# Exit codes: 0 = fetched (whether or not anything changed), 2 = fetch failed,
# 3 = publish failed. "Nothing changed" is a healthy outcome, not an error — the
# dashboard shows it as `last fetch` advancing while `last update` stays put.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

LOG_DIR="$REPO/data/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/refresh.log"
LOCK="$LOG_DIR/.refresh.lock"
OUT="$(mktemp)"

DAYS="${FACTORY_REFRESH_DAYS:-30}"

log()  { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }

# Announced to the caller only. `factory.cli` emits the collect/items/build
# markers itself; publish has no python process to emit it, so it happens here.
step() { [ "${FACTORY_PROGRESS:-0}" = "1" ] && printf '::step %s\n' "$*"; return 0; }

# A slow collection must not overlap the next hour's tick — or a button press.
#
# FACTORY_LOCK_HELD=1 says the caller already holds it. The weekly snapshot
# does: it takes the lock, then calls this script, and without this it would
# collide with itself — this script would find the lock taken, log SKIP, exit 0,
# and the snapshot would archive a week nobody collected.
. "$REPO/tools/lock.sh"

if [ "${FACTORY_LOCK_HELD:-0}" = "1" ]; then
    trap 'rm -f "$OUT"' EXIT
elif ! factory_lock_take "$LOCK" "hourly_refresh"; then
    log "SKIP another refresh is already running ($LOCK)"
    echo "SKIP another refresh is already running ($LOCK)"
    rm -f "$OUT"
    exit 0
else
    trap 'factory_lock_free "$LOCK"; rm -f "$OUT"' EXIT
fi

# launchd gives an almost-empty environment; load the key the same way the CLI
# would from an interactive shell.
[ -f "$REPO/.env" ] && set -a && . "$REPO/.env" && set +a

PY="${PYTHON:-python3}"
export PYTHONPATH="$REPO/src"
export PYTHONUNBUFFERED=1          # or the stream arrives in one lump at the end

REFRESH_ARGS=(--days "$DAYS")
# The releases page is compiled from the item store, so a "full update" that
# skipped it would leave that page a tick behind. Ingest is incremental: with no
# new runs it costs one indexed lookup each and no API calls.
if [ "${FACTORY_REFRESH_ITEMS:-1}" = "1" ]; then
    REFRESH_ARGS+=(--with-items)
fi

log "START refresh days=$DAYS ${REFRESH_ARGS[*]}"

"$PY" -m factory.cli refresh "${REFRESH_ARGS[@]}" 2>&1 | tee "$OUT"
CODES=("${PIPESTATUS[@]}")

grep -v '^::step ' "$OUT" | sed 's/^/    /' >> "$LOG"

# A failed fetch is not a reason to skip publishing. The refresh rebuilds the
# controller-sourced pages anyway (see cmd_refresh), and the header on every
# page carries the failed fetch — so publishing shows a live pipeline with one
# dead source, where skipping it shows yesterday's site with no explanation.
FETCH_FAILED=0
if [ "${CODES[0]}" -ne 0 ]; then
    log "FAIL $(tail -3 "$OUT" | tr '\n' ' ')"
    FETCH_FAILED=1
fi

if [ "$FETCH_FAILED" -eq 0 ]; then
    log "OK $(grep -E '^(Fetch|Update|Items)' "$OUT" | tr '\n' ' ')"
fi

# Publish every successful tick, not only when the data changed: the page's
# "last fetch" panel is itself information — it is how a reader knows the
# pipeline is alive rather than silently dead.
if [ "${FACTORY_PUBLISH:-1}" = "1" ]; then
    step "publish Publishing to GitHub Pages"
    if pub="$(bash "$REPO/tools/publish.sh" 2>&1)"; then
        log "PUBLISH $pub"
        printf '%s\n' "$pub"
    else
        log "PUBLISH FAILED $(printf '%s' "$pub" | tail -2 | tr '\n' ' ')"
        printf '%s\n' "$pub" >&2
        echo "publish failed — the local dashboard is current, the Pages site is not" >&2
        exit 3
    fi
fi

# The fetch failure is still the tick's outcome, reported after the publish so
# the site is current before the non-zero exit goes to the scheduler.
if [ "$FETCH_FAILED" -eq 1 ]; then
    exit 2
fi

# Trim the log so an hourly job cannot fill the disk over months.
if [ "$(wc -l < "$LOG")" -gt 5000 ]; then
    tail -2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

exit 0
