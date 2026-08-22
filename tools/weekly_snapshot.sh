#!/bin/bash
# The week, packed out: collect, rebuild, deck, archive, publish.
#
# WHY THIS IS A SEPARATE JOB FROM THE HOURLY ONE
# The weekly *pages* need no schedule of their own — `make build` writes the
# weekly bundle on every hourly tick, so week.html is never more than an hour
# old. What needs a fixed time is the **snapshot**: the deck, and the copy of
# the week under weekly/<ISO week>/ that a later week gets compared against.
# Those must happen once, at a known moment, not 168 times a week.
#
# It runs Sunday night, so the week it captures has finished and Monday's
# meeting reads a whole week. In UTC that moment is Monday morning: the ISO
# week has rolled over, "the current week" is a fresh empty one, and the
# archive step therefore takes the most recent *completed* week. Pass
# FACTORY_ARCHIVE_CURRENT=1 to snapshot the week in progress instead.
#
# Exit codes: 0 = archived, 2 = collect failed, 3 = publish failed,
# 4 = could not get the lock (the hourly job never let go).

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

LOG_DIR="$REPO/data/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/weekly.log"
# Deliberately the *same* lock the hourly refresh takes: both write
# dashboard/data and both publish, and two of them at once would publish a
# half-built site.
LOCK="$LOG_DIR/.refresh.lock"

log() { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }

# Wait for the hourly job rather than skipping. A skipped hourly tick costs an
# hour of staleness; a skipped weekly snapshot costs the week — there is no
# second chance at it, because the controllers age their detail out.
. "$REPO/tools/lock.sh"

WAITED=0
until factory_lock_take "$LOCK" "weekly_snapshot"; do
    if [ "$WAITED" -ge 1200 ]; then
        log "FAIL could not take $LOCK after 20 minutes"
        exit 4
    fi
    [ "$WAITED" -eq 0 ] && log "WAIT another refresh holds the lock"
    sleep 30
    WAITED=$((WAITED + 30))
done
trap 'factory_lock_free "$LOCK"' EXIT

[ -f "$REPO/.env" ] && set -a && . "$REPO/.env" && set +a

PY="${PYTHON:-python3}"
export PYTHONPATH="$REPO/src"
export PYTHONUNBUFFERED=1

ARCHIVE_ARGS=""
[ "${FACTORY_ARCHIVE_CURRENT:-0}" = "1" ] && ARCHIVE_ARGS="--current"

log "START weekly snapshot${ARCHIVE_ARGS:+ (}${ARCHIVE_ARGS}${ARCHIVE_ARGS:+)}"

# A fresh collect first, so the snapshot is the week as it actually ended and
# not as the last hourly tick happened to leave it. FACTORY_PUBLISH=0: this
# script publishes once at the end, after the deck and the archive exist.
# FACTORY_LOCK_HELD=1: we already hold the shared lock. Without it the refresh
# would find the lock taken, log SKIP and exit 0, and this script would archive
# a week that was never collected.
if ! FACTORY_PUBLISH=0 FACTORY_LOCK_HELD=1 \
        FACTORY_REFRESH_DAYS="${FACTORY_REFRESH_DAYS:-30}" \
        bash "$REPO/tools/hourly_refresh.sh" >>"$LOG" 2>&1; then
    code=$?
    # 2 is a failed EOS fetch. The weekly numbers come from the controllers,
    # not from EOS, so that is not a reason to skip the snapshot — the refresh
    # rebuilds the controller-sourced pages anyway.
    if [ "$code" -ne 2 ]; then
        log "FAIL refresh exited $code"
        exit 2
    fi
    log "WARN EOS fetch failed; continuing on controller data"
fi

for step in weekly weekly-deck ramp-deck archive; do
    log "STEP $step"
    case "$step" in
        weekly)      "$PY" -m factory.cli weekly       >>"$LOG" 2>&1 ;;
        weekly-deck) "$PY" tools/build_weekly_deck.py  >>"$LOG" 2>&1 ;;
        # Into dashboard/data/, so the publish at the end of this script ships
        # it and the all-hands download is the week that just closed.
        ramp-deck)   "$PY" tools/build_ramp_deck.py    >>"$LOG" 2>&1 ;;
        archive)     "$PY" -m factory.cli archive $ARCHIVE_ARGS >>"$LOG" 2>&1 ;;
    esac
    if [ $? -ne 0 ]; then
        log "FAIL $step"
        exit 2
    fi
done

WEEK="$(ls -1d "$REPO"/weekly/*/ 2>/dev/null | sort | tail -1)"
log "ARCHIVED ${WEEK:-nothing}"

if [ "${FACTORY_PUBLISH:-1}" = "1" ]; then
    if pub="$(bash "$REPO/tools/publish.sh" 2>&1)"; then
        log "PUBLISH $pub"
    else
        log "PUBLISH FAILED $(printf '%s' "$pub" | tail -2 | tr '\n' ' ')"
        exit 3
    fi
fi

# The archive is committed on purpose — the point is to still have it in three
# months — but committing from a timer is a decision nobody made. Say what is
# waiting instead.
if command -v git >/dev/null && [ -d "$REPO/.git" ]; then
    pending="$(git -C "$REPO" status --porcelain weekly decks 2>/dev/null | wc -l | tr -d ' ')"
    [ "$pending" != "0" ] && log "TODO $pending files under weekly/ and decks/ are not committed"
fi

if [ "$(wc -l < "$LOG")" -gt 4000 ]; then
    tail -1500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

log "OK weekly snapshot complete"
exit 0
