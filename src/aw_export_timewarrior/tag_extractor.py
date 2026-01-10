"""Tag extraction from ActivityWatch events.

This module isolates all tag matching and extraction logic into a single component,
making it easy to test and maintain. Part of the Exporter refactoring plan.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExclusiveGroupViolation:
    """Details about an exclusive group violation."""

    group_name: str
    group_tags: set[str]
    conflicting_tags: set[str]

    def __str__(self) -> str:
        return (
            f"Group '{self.group_name}': "
            f"tags {sorted(self.conflicting_tags)} conflict "
            f"(exclusive group allows only one of {sorted(self.group_tags)})"
        )


class ExclusiveGroupError(Exception):
    """Exception raised when tags violate exclusive group rules."""

    def __init__(self, source_tags: set[str], violations: list[ExclusiveGroupViolation]):
        self.source_tags = source_tags
        self.violations = violations
        violation_details = "; ".join(str(v) for v in violations)
        super().__init__(
            f"Tags {sorted(source_tags)} violate exclusive group rules: {violation_details}"
        )


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
        default_retry: int = 6,
    ) -> None:
        """Initialize tag extractor.

        Args:
            config: Configuration dictionary with tag rules, or a callable that returns the config
            event_fetcher: EventFetcher for getting sub-events
            terminal_apps: Set of terminal app names (lowercase)
            log_callback: Optional callback for logging (signature: log(msg, event=None, **kwargs))
            default_retry: Default retry count for get_corresponding_event calls.
                Set to 0 for report/dry-run mode to avoid sleeping on recent events.
        """
        # Support both dict and callable (for dynamic config access in tests)
        self._config_getter = config if callable(config) else (lambda: config)
        self.event_fetcher = event_fetcher
        self.terminal_apps = terminal_apps or set()
        self.default_retry = default_retry
        self.log_callback = log_callback or (lambda msg, **kwargs: logger.info(msg))
        # Track the last matched rule (set by extraction methods)
        self._last_matched_rule: str | None = None

    @property
    def config(self) -> dict:
        """Get the current config (supports both static dict and dynamic callable)."""
        return self._config_getter()

    @property
    def last_matched_rule(self) -> str | None:
        """Get the rule that matched during the last get_tags() call.

        Returns rule in format "type:name" (e.g., "app:terminal", "browser:github").
        Returns None if no rule matched or get_tags() hasn't been called.
        """
        return self._last_matched_rule

    def get_tags(self, event: dict) -> set[str] | None | bool:
        """Determine tags for an event.

        Tries each extraction method in order until one succeeds.
        After calling, access self.last_matched_rule to see which rule matched.

        Args:
            event: The event to extract tags from

        Returns:
            set[str]: Tags if matched
            None: Event should be ignored (too short, etc.)
            False: No matching rules found
        """
        # Reset matched rule tracking
        self._last_matched_rule = None

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
            self._last_matched_rule = "afk:status"
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
        # Use fallback_to_recent since tmux state persists between recorded events
        tmux_event = self.event_fetcher.get_corresponding_event(
            window_event,
            tmux_bucket,
            ignorable=True,
            fallback_to_recent=True,
            retry=self.default_retry,
        )

        if not tmux_event:
            return []  # Terminal window but no tmux activity

        # Use shared subevent tags logic with tmux matcher
        return self._get_subevent_tags(
            window_event=window_event,
            subtype="tmux",
            matchers=[("tags", self._match_tmux_rule)],
            sub_event=tmux_event,
        )

    def _match_tmux_rule(self, rule: dict, sub_event: dict, rule_key: str) -> set[str] | None:
        """Match a tmux rule against a tmux sub-event.

        Args:
            rule: The tmux rule configuration
            sub_event: The tmux event data
            rule_key: Unused (for API compatibility with other matchers)

        Returns:
            Set of tags if matched, None otherwise
        """
        # Extract tmux data
        session_name = sub_event["data"].get("session_name", "")
        window_name = sub_event["data"].get("window_name", "")
        pane_title = sub_event["data"].get("pane_title", "")
        pane_command = sub_event["data"].get("pane_current_command", "")
        pane_path = sub_event["data"].get("pane_current_path", "")

        # Check if session matches (if specified)
        if "session" in rule and not re.search(rule["session"], session_name):
            return None

        # Check if window matches (if specified)
        if "window" in rule and not re.search(rule["window"], window_name):
            return None

        # Check if command matches (if specified)
        command_match = None
        if "command" in rule:
            command_match = re.search(rule["command"], pane_command)
            if not command_match:
                return None

        # Check if path matches (if specified)
        path_match = None
        if "path" in rule:
            path_match = re.search(rule["path"], pane_path)
            if not path_match:
                return None

        # Build tags with variable substitution
        substitutions = {
            "$session": session_name,
            "$window": window_name,
            "$title": pane_title,
            "$command": pane_command,
            "$path": pane_path,
        }

        # Add capture groups from both command and path matches
        cmd_groups = command_match.groups() if command_match else ()
        path_groups = path_match.groups() if path_match else ()

        for i, group in enumerate(cmd_groups, start=1):
            substitutions[f"${i}"] = group
        for i, group in enumerate(path_groups, start=len(cmd_groups) + 1):
            substitutions[f"${i}"] = group

        return self._build_tags(self._get_rule_tags(rule), substitutions)

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

            self._last_matched_rule = f"app:{rule_name}"
            return self._build_tags(self._get_rule_tags(rule), substitutions)

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

    def _fetch_sub_event(
        self,
        window_event: dict,
        apps: tuple,
        bucket_pattern: str,
        app_normalizer: Callable | None = None,
        skip_if: Callable | None = None,
    ) -> tuple[dict | None, str]:
        """Fetch sub-event for a window event (browser, editor, etc).

        Args:
            window_event: The main window event
            apps: Tuple of app names to match
            bucket_pattern: Pattern for bucket ID (e.g., 'aw-watcher-{app}')
            app_normalizer: Optional function to normalize app name
            skip_if: Optional function that returns True if we should skip this sub_event

        Returns:
            Tuple of (sub_event or None, event_type string)
        """
        app = window_event["data"].get("app", "").lower()
        if app not in apps:
            return None, ""

        # Normalize app name if needed
        app_normalized = app_normalizer(app) if app_normalizer else app

        # Get the bucket ID
        bucket_key = bucket_pattern.format(app=app_normalized)
        if bucket_key not in self.event_fetcher.bucket_short:
            return None, ""
        bucket_id = self.event_fetcher.bucket_short[bucket_key]["id"]

        # Determine if we should ignore certain events (e.g., emacs buffers)
        ignorable = self._is_ignorable_event(app, window_event)

        # Get the corresponding sub-event
        sub_event = self.event_fetcher.get_corresponding_event(
            window_event, bucket_id, ignorable=ignorable, retry=self.default_retry
        )

        if not sub_event:
            return None, ""

        # Check if we should skip this sub-event
        if skip_if and skip_if(sub_event):
            return None, ""

        return sub_event, app

    def _get_subevent_tags(
        self,
        window_event: dict,
        subtype: str,
        apps: tuple | None = None,
        bucket_pattern: str | None = None,
        app_normalizer: Callable | None = None,
        matchers: list | None = None,
        skip_if: Callable | None = None,
        sub_event: dict | None = None,
    ) -> set[str] | list | bool:
        """Generic method to extract tags from events that require sub-events.

        Args:
            window_event: The main window event
            subtype: Type of rule ('browser', 'editor', 'tmux')
            apps: Tuple of app names to match (not needed if sub_event provided)
            bucket_pattern: Pattern for bucket ID (not needed if sub_event provided)
            app_normalizer: Optional function to normalize app name
            matchers: List of (rule_key, matcher_function) tuples to try in order
            skip_if: Optional function that returns True if we should skip this sub_event
            sub_event: Pre-fetched sub-event (if provided, skips fetch logic)

        Returns:
            Set of tags, empty list if no match, or False if wrong app type
        """
        # If sub_event not provided, fetch it
        if sub_event is None:
            # Check if this is the right app type
            if apps and window_event["data"].get("app", "").lower() not in apps:
                return False

            sub_event, _ = self._fetch_sub_event(
                window_event, apps or (), bucket_pattern or "", app_normalizer, skip_if
            )

            if not sub_event:
                return []

        # Try each matcher in order
        for rule_key, matcher_func in matchers or []:
            for rule_name in self.config.get("rules", {}).get(subtype, {}):
                rule = self.config["rules"][subtype][rule_name]

                # Skip rules that don't have this key
                # Support both 'tags' (preferred) and 'timew_tags' (legacy)
                if rule_key == "tags":
                    if "tags" not in rule and "timew_tags" not in rule:
                        continue
                elif rule_key not in rule:
                    continue

                # Try to match
                tags = matcher_func(rule, sub_event, rule_key)
                if tags:
                    self._last_matched_rule = f"{subtype}:{rule_name}"
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
                return self._build_tags(self._get_rule_tags(rule))
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
            rule: The rule dict containing the regexp and tags
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

        return self._build_tags(self._get_rule_tags(rule), substitutions)

    def _get_rule_tags(self, rule: dict) -> list:
        """Get tags from a rule, supporting both 'tags' and legacy 'timew_tags' keys.

        Args:
            rule: The rule configuration dict

        Returns:
            List of tag templates from the rule
        """
        # Support both 'tags' (preferred) and 'timew_tags' (legacy)
        return rule.get("tags", rule.get("timew_tags", []))

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

    def _fetch_tmux_sub_event(self, window_event: dict) -> dict | None:
        """Fetch tmux sub-event for a terminal window.

        Uses the same logic as get_tmux_tags() for fetching.

        Args:
            window_event: The window event

        Returns:
            The tmux sub-event, or None if not found/not applicable
        """
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
            return None

        tmux_bucket = self.event_fetcher.get_tmux_bucket()
        if not tmux_bucket:
            return None

        return self.event_fetcher.get_corresponding_event(
            window_event,
            tmux_bucket,
            ignorable=True,
            fallback_to_recent=True,
            retry=self.default_retry,
        )

    def get_specialized_context(self, window_event: dict) -> dict[str, str | None]:
        """Get specialized context data for a window event (URL, path, tmux info).

        Uses the same code paths as the tag extraction methods to ensure consistency.

        Args:
            window_event: The window event

        Returns:
            Dict with keys: type (browser/editor/terminal/None), data (the context string)
        """
        result: dict[str, str | None] = {"type": None, "data": None}

        # Try browser - same parameters as get_browser_tags()
        sub_event, _ = self._fetch_sub_event(
            window_event,
            apps=("chromium", "chrome", "firefox"),
            bucket_pattern="aw-watcher-web-{app}",
            app_normalizer=lambda app: "chrome" if app == "chromium" else app,
            skip_if=lambda e: e["data"].get("url") in ("chrome://newtab/", "about:newtab"),
        )
        if sub_event:
            url = sub_event["data"].get("url", "")
            if url:
                result["type"] = "browser"
                result["data"] = url
            return result

        # Try editor - same parameters as get_editor_tags()
        sub_event, _ = self._fetch_sub_event(
            window_event,
            apps=("emacs", "vi", "vim"),
            bucket_pattern="aw-watcher-{app}",
        )
        if sub_event:
            file_path = sub_event["data"].get("file", "")
            project = sub_event["data"].get("project", "")
            if file_path:
                result["type"] = "editor"
                result["data"] = file_path
            elif project:
                result["type"] = "editor"
                result["data"] = f"project:{project}"
            return result

        # Try tmux - same logic as get_tmux_tags()
        sub_event = self._fetch_tmux_sub_event(window_event)
        if sub_event:
            cmd = sub_event["data"].get("pane_current_command", "")
            path = sub_event["data"].get("pane_current_path", "")
            pane_title = sub_event["data"].get("pane_title", "")
            if cmd or path:
                parts = []
                if cmd:
                    parts.append(f"cmd:{cmd}")
                if path:
                    # Shorten home directory
                    if path.startswith("/home/"):
                        path = "~/" + "/".join(path.split("/")[3:])
                    parts.append(f"path:{path}")
                if pane_title and pane_title not in (cmd, path):
                    parts.append(f"title:{pane_title}")
                result["type"] = "terminal"
                result["data"] = " | ".join(parts)

        return result

    def apply_retag_rules(self, source_tags: set[str]) -> set[str]:
        """Apply retagging rules to transform tags.

        This allows defining rules that modify tags based on existing tags.
        Supports three operations (applied in order):
        1. remove: Remove specific tags when source_tags match
        2. replace: Replace matching source_tags with new tags
        3. add: Add additional tags (original behavior)

        Args:
            source_tags: Original set of tags

        Returns:
            Transformed set of tags after applying retag rules

        Raises:
            ExclusiveGroupError: If tags violate exclusive group rules
        """
        violations = self.get_exclusive_violations(source_tags)
        if violations:
            raise ExclusiveGroupError(source_tags, violations)

        new_tags = source_tags.copy()

        for tag_section in self.config.get("tags", {}):
            retags = self.config["tags"][tag_section]
            source_tag_set = set(retags.get("source_tags", []))
            intersection = new_tags.intersection(source_tag_set)

            if not intersection:
                continue

            # Step 1: Remove tags if 'remove' is specified
            if "remove" in retags:
                tags_to_remove = set()
                for tag in retags["remove"]:
                    if "$source_tag" in tag:
                        for source_tag in intersection:
                            tags_to_remove.add(tag.replace("$source_tag", source_tag))
                    else:
                        tags_to_remove.add(tag)
                new_tags = new_tags - tags_to_remove

            # Step 2: Replace if 'replace' is specified
            # This removes the matching source_tags and adds replacement tags
            if "replace" in retags:
                # Remove the matched source tags
                new_tags = new_tags - intersection
                # Add replacement tags
                for tag in retags["replace"]:
                    if "$source_tag" in tag:
                        for source_tag in intersection:
                            new_tags.add(tag.replace("$source_tag", source_tag))
                    else:
                        new_tags.add(tag)

            # Step 3: Add tags if 'add' or 'prepend' (legacy) is specified
            # Support both 'add' (preferred) and 'prepend' (legacy)
            add_tags = retags.get("add", retags.get("prepend"))
            if add_tags:
                tags_to_add = set()
                for tag in add_tags:
                    if "$source_tag" in tag:
                        for source_tag in intersection:
                            tags_to_add.add(tag.replace("$source_tag", source_tag))
                    else:
                        tags_to_add.add(tag)

                candidate_tags = new_tags.union(tags_to_add)

                if self.check_exclusive_groups(candidate_tags):
                    logger.warning(
                        f"Excluding expanding tag rule {tag_section} due to exclusivity conflicts"
                    )
                else:
                    new_tags = candidate_tags

        # Recursively apply rules if tags changed
        if new_tags != source_tags:
            # TODO: add recursion-safety here to prevent infinite loops
            return self.apply_retag_rules(new_tags)

        return new_tags

    def get_exclusive_violations(self, tags: set[str]) -> list[ExclusiveGroupViolation]:
        """Get detailed information about exclusive group violations.

        Args:
            tags: Set of tags to check

        Returns:
            List of ExclusiveGroupViolation objects describing each conflict
        """
        violations = []
        for gid in self.config.get("exclusive", {}):
            group = set(self.config["exclusive"][gid]["tags"])
            conflicting = group.intersection(tags)
            if len(conflicting) > 1:
                violations.append(
                    ExclusiveGroupViolation(
                        group_name=gid,
                        group_tags=group,
                        conflicting_tags=conflicting,
                    )
                )
        return violations

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
        return len(self.get_exclusive_violations(tags)) > 0
