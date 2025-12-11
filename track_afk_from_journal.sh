#!/bin/bash
#
# Track AFK periods from systemd-logind journal
#
# This script reads systemd-logind journal entries to find:
# 1. "Lid closed." / "Lid opened." pairs
# 2. "Suspending..." / "Operation 'suspend' finished." pairs
#
# And records them as afk periods in timewarrior using:
# timew track <start> <end> afk lid-closed
# timew track <start> <end> afk suspend
#

## Stupid Human comment: this was made by AI.  If I had known it would be this complex, I'd asked for a python script rather than a bash script.

set -euo pipefail

# Default to last 24 hours
SINCE="${1:-24 hours ago}"

# Temporary files for processing
LID_EVENTS=$(mktemp)
SUSPEND_EVENTS=$(mktemp)

cleanup() {
    rm -f "$LID_EVENTS" "$SUSPEND_EVENTS"
}
trap cleanup EXIT

echo "Fetching systemd-logind events since '$SINCE'..."

# Extract all relevant events with timestamps in a single pass
# Format: timestamp|event_type (lid-closed, lid-opened, suspend-start, suspend-end)
ALL_EVENTS=$(mktemp)
sudo journalctl --since "$SINCE" -u systemd-logind --no-pager -o short-iso | \
    grep -E "(Lid (closed|opened)\.|Suspending\.\.\.|Operation 'suspend' finished\.)" | \
    sed -E 's/^([^ ]+) [^ ]+ systemd-logind\[[0-9]+\]: Lid closed\./\1|lid-closed/' | \
    sed -E 's/^([^ ]+) [^ ]+ systemd-logind\[[0-9]+\]: Lid opened\./\1|lid-opened/' | \
    sed -E 's/^([^ ]+) [^ ]+ systemd-logind\[[0-9]+\]: Suspending\.\.\./\1|suspend-start/' | \
    sed -E 's/^([^ ]+) [^ ]+ systemd-logind\[[0-9]+\]: Operation .suspend. finished\./\1|suspend-end/' | \
    sort > "$ALL_EVENTS"

echo ""
echo "Processing AFK events..."

# Process events in chronological order
lid_close_time=""
suspend_time=""

while IFS='|' read -r timestamp event_type; do
    case "$event_type" in
        lid-closed)
            # Only track if not already suspended
            if [[ -z "$suspend_time" ]]; then
                lid_close_time="$timestamp"
            fi
            ;;
        lid-opened)
            # Close any open lid-closed period (if not overridden by suspend)
            if [[ -n "$lid_close_time" ]] && [[ -z "$suspend_time" ]]; then
                close_tw=$(echo "$lid_close_time" | sed 's/\([0-9-]\+\)T\([0-9:]\+\).*/\1T\2/')
                open_tw=$(echo "$timestamp" | sed 's/\([0-9-]\+\)T\([0-9:]\+\).*/\1T\2/')
                echo "  Lid closed: $close_tw -> $open_tw"
                timew track "$close_tw" - "$open_tw" afk lid-closed :adjust
                lid_close_time=""
            fi
            ;;
        suspend-start)
            # Suspend overrides lid-closed if active
            if [[ -n "$lid_close_time" ]]; then
                echo "  Note: Suspend started, overriding lid-closed from $lid_close_time"
                lid_close_time=""
            fi
            suspend_time="$timestamp"
            ;;
        suspend-end)
            # Close suspend period
            if [[ -n "$suspend_time" ]]; then
                suspend_tw=$(echo "$suspend_time" | sed 's/\([0-9-]\+\)T\([0-9:]\+\).*/\1T\2/')
                resume_tw=$(echo "$timestamp" | sed 's/\([0-9-]\+\)T\([0-9:]\+\).*/\1T\2/')
                echo "  Suspended: $suspend_tw -> $resume_tw"
                timew track "$suspend_tw" - "$resume_tw" afk suspend :adjust
                suspend_time=""
            fi
            # Clear any lid_close_time that might have been set during suspend
            lid_close_time=""
            ;;
    esac
done < "$ALL_EVENTS"

# Warn about unclosed periods
if [[ -n "$lid_close_time" ]]; then
    echo "  Warning: Lid closed at $lid_close_time but never opened (still closed?)"
fi
if [[ -n "$suspend_time" ]]; then
    echo "  Warning: System suspended at $suspend_time but never resumed (still suspended?)"
fi

rm -f "$ALL_EVENTS"

echo ""
echo "Done! AFK periods have been tracked in timewarrior."
echo "Use 'timew summary afk' to see the tracked AFK time."
