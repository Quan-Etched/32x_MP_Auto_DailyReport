# ---------------------------------------------------------------------- lock
# A directory as a mutex, with the owner written inside it.
#
# `mkdir` alone was the whole mechanism, and it has one failure that matters:
# a process killed with SIGKILL — an OOM, a reboot mid-run, `systemctl kill` —
# never runs its trap, so the directory survives with nobody behind it. Every
# later run then finds the lock taken and skips, and the pipeline stops dead
# while looking healthy: the timer fires, the log says SKIP, the site quietly
# stops moving.
#
# So the lock records who holds it and when they took it, and a caller that
# finds it checks whether that process is still alive before believing it.
#
#   factory_lock_take  <lock-dir> <label>   -> 0 taken, 1 held by someone alive
#   factory_lock_free  <lock-dir>
#
# Callers source this; it defines functions and does nothing on its own.

#: A run older than this is presumed dead even if its PID is still around —
#: the PID may have been reused. Longer than the hourly job's own 50-minute
#: timeout, so a slow-but-living collect is never broken into.
FACTORY_LOCK_STALE_SEC="${FACTORY_LOCK_STALE_SEC:-4200}"

factory_lock_take() {
    local dir="$1" label="${2:-unknown}" owner age now

    if mkdir "$dir" 2>/dev/null; then
        printf '%s\n%s\n%s\n' "$$" "$(date +%s)" "$label" > "$dir/owner"
        return 0
    fi

    # Held. By something alive, or by a ghost?
    owner="$(head -1 "$dir/owner" 2>/dev/null)"
    now="$(date +%s)"
    age=$(( now - $(sed -n 2p "$dir/owner" 2>/dev/null || echo "$now") ))

    if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null \
       && [ "$age" -lt "$FACTORY_LOCK_STALE_SEC" ]; then
        return 1
    fi

    # Nobody home. Say so loudly — a broken lock is either a crash worth
    # knowing about or a bug in this file, and both need to reach a human.
    echo "factory_lock: breaking a stale lock (pid=${owner:-none}, age=${age}s," \
         "held by $(sed -n 3p "$dir/owner" 2>/dev/null || echo unknown))" >&2
    rm -rf "$dir"
    if mkdir "$dir" 2>/dev/null; then
        printf '%s\n%s\n%s\n' "$$" "$(date +%s)" "$label" > "$dir/owner"
        return 0
    fi
    # Lost a race to break it; whoever won is alive by definition.
    return 1
}

factory_lock_free() {
    rm -rf "$1" 2>/dev/null
}
