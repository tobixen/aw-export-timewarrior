import copy
import logging
import re
import tomllib
from pathlib import Path
from typing import Any

from aw_core.config import load_config_toml

from .config_validation import validate_and_warn

logger = logging.getLogger(__name__)

_LIST_FIELDS_IN_TAG_RULES = ["source_tags", "add", "prepend", "remove", "replace"]
_REGEXP_FIELDS_IN_RULES = frozenset(
    [
        "url_regexp",
        "title_regexp",
        "path_regexp",
        "project_regexp",
        "file_regexp",
        "command",
        "path",
    ]
)


class ListExpansionError(Exception):
    """Raised when list/group reference expansion fails."""

    pass


# Backward-compat alias
AppGroupExpansionError = ListExpansionError


def expand_list_references(config: dict[str, Any]) -> dict[str, Any]:
    """Expand @name references in list and regexp fields throughout the config.

    Resolves names from both [lists] and [app_groups] sections.
    In list fields (tags.*.{source_tags,add,prepend,remove,replace},
    rules.*.*.{tags,timew_tags}, rules.app.*.app_names, exclusive.*.tags),
    @name is replaced by the list items inline.
    In regexp fields (url_regexp, title_regexp, path_regexp, etc.),
    @name is replaced by a pipe-joined alternation of the list items.
    """
    all_lists: dict[str, list[str]] = {
        **config.get("app_groups", {}),
        **config.get("lists", {}),
    }
    if not all_lists:
        return config

    expanded_lists = _expand_all_groups(all_lists)
    config = copy.deepcopy(config)

    def expand(lst: list) -> list:
        result = []
        for item in lst:
            if isinstance(item, str) and item.startswith("@"):
                ref = item[1:]
                if ref not in expanded_lists:
                    raise ListExpansionError(f"References unknown group/list '@{ref}'")
                result.extend(expanded_lists[ref])
            else:
                result.append(item)
        return result

    def expand_regexp(pattern: str) -> str:
        def replace(m: re.Match) -> str:
            ref = m.group(1)
            if ref not in expanded_lists:
                raise ListExpansionError(f"References unknown group/list '@{ref}'")
            return "|".join(expanded_lists[ref])

        return re.sub(r"@([A-Za-z_]\w*)", replace, pattern)

    for tag_rule in config.get("tags", {}).values():
        if not isinstance(tag_rule, dict):
            continue
        for field in _LIST_FIELDS_IN_TAG_RULES:
            if field in tag_rule and isinstance(tag_rule[field], list):
                tag_rule[field] = expand(tag_rule[field])

    for rule_type, type_rules in config.get("rules", {}).items():
        if not isinstance(type_rules, dict):
            continue
        for rule in type_rules.values():
            if not isinstance(rule, dict):
                continue
            for field in ["tags", "timew_tags"]:
                if field in rule and isinstance(rule[field], list):
                    rule[field] = expand(rule[field])
            if rule_type == "app" and "app_names" in rule and isinstance(rule["app_names"], list):
                rule["app_names"] = expand(rule["app_names"])
            for field in _REGEXP_FIELDS_IN_RULES:
                if field in rule and isinstance(rule[field], str):
                    rule[field] = expand_regexp(rule[field])

    for group in config.get("exclusive", {}).values():
        if isinstance(group, dict) and "tags" in group and isinstance(group["tags"], list):
            group["tags"] = expand(group["tags"])

    return config


def expand_app_groups(config: dict[str, Any]) -> dict[str, Any]:
    """Expand @groupname references throughout config. Backward-compat wrapper."""
    return expand_list_references(config)


def _expand_all_groups(all_lists: dict[str, list[str]]) -> dict[str, list[str]]:
    """Expand all lists, resolving nested @references.

    Raises:
        ListExpansionError: If circular reference detected or unknown group
    """
    expanded: dict[str, list[str]] = {}
    expanding: set[str] = set()

    def expand_group(name: str) -> list[str]:
        if name in expanded:
            return expanded[name]

        if name in expanding:
            raise ListExpansionError(f"Circular reference in lists involving '{name}'")

        if name not in all_lists:
            raise ListExpansionError(f"Unknown list/group: '{name}'")

        expanding.add(name)

        result = []
        for item in all_lists[name]:
            if isinstance(item, str) and item.startswith("@"):
                result.extend(expand_group(item[1:]))
            else:
                result.append(item)

        expanding.remove(name)
        expanded[name] = result
        return result

    for group_name in all_lists:
        expand_group(group_name)

    return expanded


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

# Expand list references and validate on module load
config = expand_list_references(config)
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
                loaded_config = tomllib.load(f)
            config = expand_list_references(loaded_config)
            if validate:
                validate_and_warn(config)
        else:
            raise FileNotFoundError(f"Config file not found: {config_path}")
