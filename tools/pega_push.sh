#!/bin/bash
# Warm the controller cache here, then hand it to the dashboard host.
#
# WHY THIS EXISTS
# The box cannot read pega3, pega4 or pega5. Not slowly — measured 2026-09-03,
# one 50-run listing delivered 8,452 of 26,400 bytes in 180 seconds, 46 bytes a
# second, because its Tailscale path to those hosts is relayed through a DERP
# node in Hong Kong. The identical request from a laptop on the same tailnet
# takes 0.09 seconds.
#
# So the laptop fetches and the box borrows: `data/raw/pega/` is a cache keyed
# by host and URL, it is portable between machines, and docs/deploy.md has
# always described it as the transport for a host with no route. This is that,
# on a timer, so the controller half of the dashboard stops depending on
# somebody remembering.
#
#   make pega-push                    warm and push, once
#   make schedule-pega-push-install   hourly at :50, so it lands before the
#                                     box's own :05 rebuild
#
# It does NOT rebuild or publish on the box. The hourly job there already does
# both, and one publish path is worth more than ten minutes of freshness.
#
# HONEST LIMITATION: this is a laptop. Asleep, off the VPN, or shut means no
# push, and the box keeps serving the last cache it got — which is precisely
# the fragility the dashboard host was bought to remove. It is a workaround for
# a network fault, not a design. Delete it when infra gives the box a direct
# path; see "The box cannot reach the controllers" in docs/deploy.md.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

[ -f "$REPO/.env" ] && set -a && . "$REPO/.env" && set +a

HOST="${FACTORY_DEPLOY_HOST:-chuck@chuck-dashboard.usw2.i.etched.com}"
DEST="${FACTORY_DEPLOY_PATH:-factory_data_analysis}"
LOG_DIR="$REPO/data/logs"
LOG="$LOG_DIR/pega_push.log"
LOCK="$LOG_DIR/.pega_push.lock"
mkdir -p "$LOG_DIR"

log() { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }

# A slow push must not overlap the next hour's, same rule as the refresh.
. "$REPO/tools/lock.sh"
if ! factory_lock_take "$LOCK" "pega_push"; then
    log "SKIP another push is already running"
    exit 0
fi
trap 'factory_lock_free "$LOCK"' EXIT

# ---------------------------------------------------------------- 1. warm it
# One cheap probe first: no VPN means no controllers, and a push of a cache we
# failed to warm is a push of yesterday's data over yesterday's data. Nothing
# is lost by it, but the log should say what happened.
if ! curl -sS -m 15 -o /dev/null \
        "http://pega4:3000/api/history/data-analysis/suite-runs?per_page=1"; then
    log "SKIP the controllers are not reachable from here — VPN?"
    exit 0
fi

log "START warming the cache"
before="$(find "$REPO/data/raw/pega" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
if ! "${PYTHON:-python3}" -m factory.cli pega-stations >>"$LOG" 2>&1; then
    log "FAIL could not read the controllers; not pushing a half-warmed cache"
    exit 2
fi
after="$(find "$REPO/data/raw/pega" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
log "cache $before -> $after entries"

# ---------------------------------------------------------------- 2. push it
# No --delete: the box has entries this laptop never fetched (pega2 and pega6
# it reads itself), and deleting them would take away the half that works.
# --timeout so a dropped VPN fails instead of hanging until the next tick.
# Retried, because the link to the box is itself intermittent: the same
# transfer took 25s one hour and died on `poll: timeout` the next, while plain
# ssh to the host kept working. --partial keeps what already crossed, so an
# attempt after a failed one resumes rather than restarting 97 MB.
log "pushing to $HOST"
pushed=0
for attempt in 1 2 3; do
    if rsync -a --partial --timeout=120 \
            -e "ssh -o ConnectTimeout=20 -o BatchMode=yes -o ServerAliveInterval=15" \
            "$REPO/data/raw/pega/" "$HOST:$DEST/data/raw/pega/" >>"$LOG" 2>&1; then
        pushed=1
        [ "$attempt" -gt 1 ] && log "succeeded on attempt $attempt"
        break
    fi
    log "attempt $attempt failed"
    [ "$attempt" -lt 3 ] && sleep $((attempt * 30))
done

if [ "$pushed" -ne 1 ]; then
    log "FAIL rsync to $HOST after 3 attempts — network, or the box is down."
    log "     The box keeps serving the cache it already has; nothing is lost"
    log "     but freshness. The next tick at :50 tries again."
    exit 3
fi

log "OK pushed; the box picks it up on its next hourly build at :05"
exit 0
