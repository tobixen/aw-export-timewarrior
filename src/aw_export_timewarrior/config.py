from pathlib import Path

import toml
from aw_core.config import load_config_toml

default_config = """
# Enable workaround for aw-watcher-window-wayland issue #41
# (https://github.com/ActivityWatch/aw-watcher-window-wayland/issues/41)
# When enabled, gaps between AFK events are filled with synthetic AFK events
# Set to false if the upstream issue is fixed or if this causes problems
enable_afk_gap_workaround = true

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

[tags.housework]
source_tags = [ "housework", "dishwash" ]
prepend = [ "4chores", "afk" ]

[tags.tea]
source_tags = [ "tea" ]
prepend = [ "4break", "afk", "tea" ]

[tags.entertainment]
source_tags = [ "entertainment" ]
prepend = [ "4break" ]

[rules.browser.entertainment]
url_regexp = "^https://(?:www\\\\.)?(theguardian).com/"
timew_tags = [ "entertainment", "$1" ]

[rules.app.comms]
app_names = ["Signal", "DeltaChat"]
timew_tags = [ "4me", "personal communication", "$app" ]

[rules.editor.acme]
project_regexp = "acme"
timew_tags = [ "4work", "acme" ]

## Even if we're multitasking and working for both customer acme and customer
## emca at once, we probably should bill only one of them
[exclusive.customer]
tags = [ "acme", "emca" ]

## Even if we're multitasking and doing both dishwash, talk on the telephone, work (it's compiling!) and drinking tea at the same time, we probably should attribute the time to only one of the activities
[exclusive.main_category]
tags = [ "4break", "4chores", "4work", "4me" ]
""".strip()

config = load_config_toml("aw-export-timewarrior", default_config)

def load_custom_config(config_path):
    """Load config from a custom file path."""
    global config
    if config_path:
        config_path = Path(config_path)
        if config_path.exists():
            config = toml.load(config_path)
        else:
            raise FileNotFoundError(f"Config file not found: {config_path}")
