"""Tag extraction from ActivityWatch events.

This module isolates all tag matching and extraction logic into a single component,
making it easy to test and maintain. Part of the Exporter refactoring plan.
"""

import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class TagExtractor:
    """Extracts tags from events using configured rules.

    Responsible for:
    - Matching app/title against configured patterns
    - Extracting browser URL-based tags
    - Extracting editor file/project-based tags
    - Handling AFK status
    - Applying retagging rules
    - Checking exclusive tag groups
    """

    def __init__(
        self,
        config: dict,
        event_fetcher: Any,  # EventFetcher type
        terminal_apps: set[str] | None = None,
        log_callback: Callable | None = None,
    ) -> None:
        """Initialize tag extractor.

        Args:
            config: Configuration dictionary with tag rules, or a callable that returns the config
            event_fetcher: EventFetcher for getting sub-events
            terminal_apps: Set of terminal app names (lowercase)
            log_callback: Optional callback for logging (signature: log(msg, event=None, **kwargs))
        """
        # Support both dict and callable (for dynamic config access in tests)
        self._config_getter = config if callable(config) else (lambda: config)
        self.event_fetcher = event_fetcher
        self.terminal_apps = terminal_apps or set()
        self.log_callback = log_callback or (lambda msg, **kwargs: logger.info(msg))

    @property
    def config(self) -> dict:
        """Get the current config (supports both static dict and dynamic callable)."""
        return self._config_getter()

    def get_tags(self, event: dict) -> set[str] | None | bool:
        """Determine tags for an event.

        Tries each extraction method in order until one succeeds.

        Args:
            event: The event to extract tags from

        Returns:
            set[str]: Tags if matched
            None: Event should be ignored (too short, etc.)
            False: No matching rules found
        """
        # Try each extraction method in order
        for method in [
            self.get_afk_tags,
            self.get_tmux_tags,
            self.get_app_tags,
            self.get_browser_tags,
            self.get_editor_tags,
        ]:
            result = method(event)
            if result is not None and result is not False:
                return result

        return False  # No rules matched

    def get_afk_tags(self, event: dict) -> set[str] | bool:
        """Extract AFK status tags from AFK events.

        Args:
            event: The AFK event

        Returns:
            Set containing 'afk' or 'not-afk', or False if not an AFK event
        """
        if "status" in event["data"]:
            return {event["data"]["status"]}
        else:
            return False

    def get_tmux_tags(self, window_event: dict) -> set[str] | list | bool:
        """Extract tags from tmux events when in a terminal window.

        Args:
            window_event: The window event

        Returns:
            Set of tags, empty list if no match, or False if wrong app type
        """
        # Check if this is a terminal window
        # Common terminal apps that might run tmux
        terminal_apps = self.terminal_apps or {
            "foot",
            "kitty",
            "alacritty",
            "terminator",
            "gnome-terminal",
            "konsole",
            "xterm",
            "urxvt",
            "st",
        }

        app = window_event["data"].get("app", "").lower()
        if app not in terminal_apps:
            return False

        # Get tmux bucket - there's only one tmux bucket (not per-app like browser/editor)
        tmux_bucket = self.event_fetcher.get_tmux_bucket()
        if not tmux_bucket:
            return False

        # Get corresponding tmux event (handles picking the longest if multiple)
        tmux_event = self.event_fetcher.get_corresponding_event(
            window_event, tmux_bucket, ignorable=True
        )

        if not tmux_event:
            return []  # Terminal window but no tmux activity

        # Extract tmux data
        session_name = tmux_event["data"].get("session_name", "")
        window_name = tmux_event["data"].get("window_name", "")
        pane_title = tmux_event["data"].get("pane_title", "")
        pane_command = tmux_event["data"].get("pane_current_command", "")
        pane_path = tmux_event["data"].get("pane_current_path", "")

        # Check against configured tmux rules
        for rule_name in self.config.get("rules", {}).get("tmux", {}):
            rule = self.config["rules"]["tmux"][rule_name]

            # Check if session matches (if specified)
            if "session" in rule and not re.search(rule["session"], session_name):
                continue

            # Check if window matches (if specified)
            if "window" in rule and not re.search(rule["window"], window_name):
                continue

            # Check if command matches (if specified)
            command_match = None
            if "command" in rule:
                command_match = re.search(rule["command"], pane_command)
                if not command_match:
                    continue

            # Check if path matches (if specified)
            path_match = None
            if "path" in rule:
                path_match = re.search(rule["path"], pane_path)
                if not path_match:
                    continue

            # Build tags with variable substitution
            substitutions = {
                "$session": session_name,
                "$window": window_name,
                "$title": pane_title,
                "$command": pane_command,
                "$path": pane_path,
            }

            # Add capture groups from command or path matches
            # Prioritize command match over path match for capture groups
            active_match = command_match or path_match
            substitutions.update(self._extract_capture_groups(active_match))

            return self._build_tags(rule["timew_tags"], substitutions)

        # No rules matched - use default tag extraction
        # Create a simple tag from the command name
        if pane_command:
            return {f"tmux:{pane_command}"}

        return []  # Terminal with tmux but no matching rules

    def get_app_tags(self, event: dict) -> set[str] | bool:
        """Extract tags from app/title matching.

        Args:
            event: The window event

        Returns:
            Set of tags, or False if no rules matched
        """
        for rule_name in self.config.get("rules", {}).get("app", {}):
            rule = self.config["rules"]["app"][rule_name]

            # Check if app matches
            if event["data"].get("app") not in rule.get("app_names", []):
                continue

            # Try to match title regexp if present
            title_match = None
            if "title_regexp" in rule:
                title_match = re.search(rule["title_regexp"], event["data"].get("title", ""))
                if not title_match:
                    continue  # Required regexp didn't match

            # Build tags with variable substitution
            substitutions = {
                "$app": event["data"].get("app"),
                "$1": title_match.group(1) if title_match and title_match.groups() else None,
            }

            return self._build_tags(rule["timew_tags"], substitutions)

        return False

    def get_browser_tags(self, window_event: dict) -> set[str] | list | bool:
        """Extract tags from browser URL matching.

        Args:
            window_event: The window event

        Returns:
            Set of tags, empty list if no match, or False if wrong app type
        """
        return self._get_subevent_tags(
            window_event=window_event,
            subtype="browser",
            apps=("chromium", "chrome", "firefox"),
            bucket_pattern="aw-watcher-web-{app}",
            app_normalizer=lambda app: "chrome" if app == "chromium" else app,
            matchers=[
                ("url_regexp", self._match_url_regexp),
            ],
            skip_if=lambda sub_event: sub_event["data"].get("url")
            in ("chrome://newtab/", "about:newtab"),
        )

    def get_editor_tags(self, window_event: dict) -> set[str] | list | bool:
        """Extract tags from editor file/project matching.

        Args:
            window_event: The window event

        Returns:
            Set of tags, empty list if no match, or False if wrong app type
        """
        return self._get_subevent_tags(
            window_event=window_event,
            subtype="editor",
            apps=("emacs", "vi", "vim"),
            bucket_pattern="aw-watcher-{app}",
            matchers=[
                ("projects", self._match_project),
                ("path_regexp", self._match_path_regexp),
            ],
        )

    def _get_subevent_tags(
        self,
        window_event: dict,
        subtype: str,
        apps: tuple,
        bucket_pattern: str,
        app_normalizer: Callable | None = None,
        matchers: list | None = None,
        skip_if: Callable | None = None,
    ) -> set[str] | list | bool:
        """Generic method to extract tags from events that require sub-events.

        Args:
            window_event: The main window event
            subtype: Type of rule ('browser', 'editor')
            apps: Tuple of app names to match
            bucket_pattern: Pattern for bucket ID (e.g., 'aw-watcher-{app}')
            app_normalizer: Optional function to normalize app name (e.g., chromium -> chrome)
            matchers: List of (rule_key, matcher_function) tuples to try in order
            skip_if: Optional function that returns True if we should skip this sub_event

        Returns:
            Set of tags, empty list if no match, or False if wrong app type
        """
        # Check if this is the right app type
        if window_event["data"].get("app", "").lower() not in apps:
            return False

        app = window_event["data"]["app"].lower()

        # Normalize app name if needed
        app_normalized = app_normalizer(app) if app_normalizer else app

        # Get the bucket ID
        bucket_id = self.event_fetcher.bucket_short[bucket_pattern.format(app=app_normalized)]["id"]

        # Determine if we should ignore certain events (e.g., emacs buffers)
        ignorable = self._is_ignorable_event(app, window_event)

        # Get the corresponding sub-event
        sub_event = self.event_fetcher.get_corresponding_event(
            window_event, bucket_id, ignorable=ignorable
        )

        if not sub_event:
            return []

        # Check if we should skip this sub-event
        if skip_if and skip_if(sub_event):
            return []

        # Try each matcher in order
        for rule_key, matcher_func in matchers or []:
            for rule_name in self.config.get("rules", {}).get(subtype, {}):
                rule = self.config["rules"][subtype][rule_name]

                # Skip rules that don't have this key
                if rule_key not in rule:
                    continue

                # Try to match
                tags = matcher_func(rule, sub_event, rule_key)
                if tags:
                    return tags

        # No rules matched
        self.log_callback(
            f"Unhandled {subtype} event",
            event=window_event,
            extra={"sub_event": sub_event, "event_type": subtype, "log_event": "unhandled"},
            level=logging.WARNING,
        )
        return []

    def _is_ignorable_event(self, app: str, window_event: dict) -> bool:
        """Check if an event should be ignored (e.g., emacs internal buffers).

        Args:
            app: Application name (lowercase)
            window_event: The window event

        Returns:
            True if event should be ignored
        """
        if app == "emacs":
            return bool(re.match(r"^( )?\*.*\*", window_event["data"]["title"]))
        return False

    def _match_project(self, rule: dict, sub_event: dict, rule_key: str) -> set[str] | None:
        """Match editor events by project name.

        Args:
            rule: The rule dict
            sub_event: The editor sub-event
            rule_key: The rule key ('projects')

        Returns:
            Set of tags if matched, None otherwise
        """
        for project in rule.get("projects", []):
            if project == sub_event["data"].get("project"):
                return self._build_tags(rule["timew_tags"])
        return None

    def _match_path_regexp(self, rule: dict, sub_event: dict, rule_key: str) -> set[str] | None:
        """Match editor events by file path regexp.

        Args:
            rule: The rule dict
            sub_event: The editor sub-event
            rule_key: The rule key ('path_regexp')

        Returns:
            Set of tags if matched, None otherwise
        """
        return self._match_regexp(
            rule=rule, text=sub_event["data"].get("file", ""), rule_key=rule_key
        )

    def _match_url_regexp(self, rule: dict, sub_event: dict, rule_key: str) -> set[str] | None:
        """Match browser events by URL regexp.

        Args:
            rule: The rule dict
            sub_event: The browser sub-event
            rule_key: The rule key ('url_regexp')

        Returns:
            Set of tags if matched, None otherwise
        """
        return self._match_regexp(
            rule=rule, text=sub_event["data"].get("url", ""), rule_key=rule_key
        )

    def _extract_capture_groups(self, match: re.Match | None) -> dict[str, str]:
        """Extract capture groups from a regex match into substitution dict.

        Args:
            match: The regex match object

        Returns:
            Dict with $1, $2, $3, etc. keys for each capture group
        """
        if not match or not match.groups():
            return {}

        return {f"${i}": group for i, group in enumerate(match.groups(), start=1)}

    def _match_regexp(self, rule: dict, text: str, rule_key: str) -> set[str] | None:
        """Generic regexp matcher with group substitution.

        Args:
            rule: The rule dict containing the regexp and timew_tags
            text: The text to match against
            rule_key: The key in the rule containing the regexp pattern

        Returns:
            Set of tags with substitutions applied, or None if no match
        """
        if rule_key not in rule:
            return None

        match = re.search(rule[rule_key], text)
        if not match:
            return None

        # Build substitutions from match groups
        substitutions = self._extract_capture_groups(match)

        return self._build_tags(rule["timew_tags"], substitutions)

    def _build_tags(self, tag_templates: list, substitutions: dict | None = None) -> set[str]:
        """Build a set of tags from templates with variable substitution.

        Args:
            tag_templates: List of tag templates (e.g., ['4work', 'github', '$1'])
            substitutions: Dict of {variable: value} for substitution (e.g., {'$1': 'python-caldav'})

        Returns:
            Set of tags with 'not-afk' added
        """
        substitutions = substitutions or {}
        tags = set()

        for tag in tag_templates:
            # Skip tags with variables that have no value
            if "$" in tag:
                # Try to substitute all variables
                new_tag = tag
                has_missing_var = False

                for var, value in substitutions.items():
                    if var in tag:
                        if value is None:
                            has_missing_var = True
                            break
                        new_tag = new_tag.replace(var, value)

                # Skip if we couldn't substitute all variables
                if has_missing_var or "$" in new_tag:
                    continue

                tags.add(new_tag)
            else:
                tags.add(tag)

        # Always add 'not-afk' tag to activity-based tags
        tags.add("not-afk")

        return tags

    def apply_retag_rules(self, source_tags: set[str]) -> set[str]:
        """Apply retagging rules to expand tags.

        This allows defining rules that add additional tags based on existing tags.
        For example, adding project-wide tags based on specific tags.

        Args:
            source_tags: Original set of tags

        Returns:
            Expanded set of tags after applying retag rules

        Raises:
            AssertionError: If tags violate exclusive group rules
        """
        assert not self.check_exclusive_groups(source_tags), "Tags violate exclusive group rules"

        new_tags = source_tags.copy()

        for tag_section in self.config.get("tags", {}):
            retags = self.config["tags"][tag_section]
            intersection = source_tags.intersection(set(retags["source_tags"]))

            if intersection:
                new_tags_ = set()
                for tag in retags.get("add", []):
                    if "$source_tag" in tag:
                        for source_tag in intersection:
                            new_tags_.add(tag.replace("$source_tag", source_tag))
                    else:
                        new_tags_.add(tag)

                new_tags_ = new_tags.union(new_tags_)

                if self.check_exclusive_groups(new_tags_):
                    logger.warning(
                        f"Excluding expanding tag rule {tag_section} due to exclusivity conflicts"
                    )
                else:
                    new_tags = new_tags_

        # Recursively apply rules if tags changed
        if new_tags != source_tags:
            # TODO: add recursion-safety here to prevent infinite loops
            return self.apply_retag_rules(new_tags)

        return new_tags

    def check_exclusive_groups(self, tags: set[str]) -> bool:
        """Check if tags violate exclusive group rules.

        Exclusive groups ensure that only one tag from each exclusive group
        can be present in the tag set.

        Args:
            tags: Set of tags to check

        Returns:
            True if tags violate exclusivity (conflict detected)
            False if tags are valid (no conflicts)
        """
        for gid in self.config.get("exclusive", {}):
            group = set(self.config["exclusive"][gid]["tags"])
            if len(group.intersection(tags)) > 1:
                return True
        return False
