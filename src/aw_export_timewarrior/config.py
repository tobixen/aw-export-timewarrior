import logging
import tomllib
from pathlib import Path

from aw_core.config import load_config_toml

from .config_validation import validate_and_warn

logger = logging.getLogger(__name__)

default_config = """
# Enable workaround for aw-watcher-window-wayland issue #41
# (https://github.com/ActivityWatch/aw-watcher-window-wayland/issues/41)
# When enabled, gaps between AFK events are filled with synthetic AFK events
# Set to false if the upstream issue is fixed or if this causes problems
enable_afk_gap_workaround = true

# Enable lid event tracking from aw-watcher-lid
# When enabled, lid closure and suspend events will be treated as AFK
# Set to false to ignore lid events even if aw-watcher-lid is running
enable_lid_events = true

# Terminal applications - used to suppress warnings for unknown terminal events
terminal_apps = [
    "alacritty",
    "foot",
    "gnome-terminal",
    "kitty",
    "konsole",
    "terminator",
    "tilix",
    "xfce4-terminal",
    "xterm",
    "rxvt",
    "urxvt",
    "st",
    "wezterm",
    "cool-retro-term",
    "hyper",
    "iterm2",
    "terminal",
]

# Tuning parameters - adjust these to customize behavior
[tuning]
# Warn if ActivityWatch data is older than this many seconds (default: 300 = 5 minutes)
aw_warn_threshold = 300.0

# Sleep interval between polls in real-time sync mode (seconds, default: 30)
sleep_interval = 30.0

# Ignore window visits shorter than this (seconds, default: 3)
# Useful to filter out very brief window switches
ignore_interval = 3.0

# Minimum interval between recording the same activity (seconds, default: 90)
# Prevents creating too many tiny intervals for the same ongoing activity
min_recording_interval = 90.0

# Window events longer than this are treated independently (seconds, default: 240 = 4 minutes)
# Helps segment long activities into discrete intervals
max_mixed_interval = 240.0

# Grace period after timew commands (seconds, default: 10)
# Time to press Ctrl+C if you disagree with a timew command
grace_time = 10.0

# Minimum interval for recording a specific tag (seconds, default: 50)
# Tags observed for less than this duration may not be recorded
min_tag_recording_interval = 50.0

# Stickyness factor for tag retention (0.0 to 1.0, default: 0.1)
# How much time tags should "stick" across activity changes
stickyness_factor = 0.1

# Minimum duration for lid events (seconds, default: 10)
# Lid close/open cycles shorter than this are ignored to filter out accidental bumps
# and brief lid checks (e.g., looking at notifications)
min_lid_duration = 10.0

[tags.housework]
source_tags = [ "housework", "dishwash" ]
add = [ "4chores", "afk" ]

[tags.tea]
source_tags = [ "tea" ]
add = [ "4break", "afk", "tea" ]

[tags.entertainment]
source_tags = [ "entertainment" ]
add = [ "4break" ]

[rules.browser.entertainment]
url_regexp = "^https://(?:www\\\\.)?(theguardian).com/"
tags = [ "entertainment", "$1" ]

[rules.app.comms]
app_names = ["Signal", "DeltaChat"]
tags = [ "4me", "personal communication", "$app" ]

[rules.editor.acme]
project_regexp = "acme"
tags = [ "4work", "acme" ]

## Even if we're multitasking and working for both customer acme and customer
## emca at once, we probably should bill only one of them
[exclusive.customer]
tags = [ "acme", "emca" ]

## Even if we're multitasking and doing both dishwash, talk on the telephone, work (it's compiling!) and drinking tea at the same time, we probably should attribute the time to only one of the activities
[exclusive.main_category]
tags = [ "4break", "4chores", "4work", "4me" ]
""".strip()

config = load_config_toml("aw-export-timewarrior", default_config)

# Validate default config on module load
validate_and_warn(config)


def load_custom_config(config_path, validate: bool = True):
    """Load config from a custom file path.

    Args:
        config_path: Path to the config file
        validate: Whether to validate the config (default True)
    """
    global config
    if config_path:
        config_path = Path(config_path)
        if config_path.exists():
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            if validate:
                validate_and_warn(config)
        else:
            raise FileNotFoundError(f"Config file not found: {config_path}")
