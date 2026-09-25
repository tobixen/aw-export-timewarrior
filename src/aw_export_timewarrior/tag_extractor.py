"""Tag extraction from ActivityWatch events.

This module isolates all tag matching and extraction logic into a single component,
making it easy to test and maintain. Part of the Exporter refactoring plan.
"""

import logging
import os.path
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Browser app names as reported by the window watcher (lowercased).
# Includes flatpak app-ids (e.g. org.chromium.Chromium → org.chromium.chromium).
BROWSER_APPS: tuple[str, ...] = ("chromium", "chrome", "firefox", "org.chromium.chromium")


def normalize_browser_app(app: str) -> str:
    """Map a browser app name to its aw-watcher-web-<name> bucket suffix."""
    return "chrome" if app in ("chromium", "org.chromium.chromium") else app


def _skip_browser_newtab(sub_event: dict) -> bool:
    return sub_event["data"].get("url") in ("chrome://newtab/", "about:newtab")


# `activity-watch-mode` (the emacs watcher) pulses on a timer instead of
# emitting on buffer switch, so its event can start well after the window
# event it belongs to: a sample of 182 window events naming an editor buffer
# had 46 with no emacs event within EVENT_MATCHING_BUFFER_SECONDS, the
# nearest one 39s-82s away. vi/vim update on every keystroke and don't need
# the wider lookahead.
EMACS_LOOKAHEAD_BUFFER_SECONDS = 90.0

# activity-watch-mode pulses on activity, so it reports nothing at all while a
# buffer is merely being read -- gaps of tens of minutes are normal.  How far
# get_corresponding_event may reach for a bracketing emacs event whose file
# matches the buffer named in the window title.  Measured over three weeks of
# this author's data: of 94 emacs window events with no sub-event inside the
# widened window, 51 have a bracketing match within 10 minutes and 63 within
# 30; going further buys 6 more events and starts spanning whole work sessions.
EMACS_CANDIDATE_REACH = timedelta(minutes=30)

# The emacs frame title is "<buffer name> - GNU Emacs at <host>", where the
# buffer name may carry a uniquify suffix in angle brackets ("foo.md<tingbok>",
# "foo.md<2>") when several buffers share a basename.
_EMACS_TITLE_SUFFIX_RE = re.compile(r"\s+-\s+GNU Emacs\b.*$")
_UNIQUIFY_SUFFIX_RE = re.compile(r"<[^<>]*>$")


# Sub-event fields carrying the git branch: aw-watcher-tmux uses `git_branch`,
# aw-watcher-emacs `branch` (and writes "unknown" outside a git repository).
BRANCH_FIELDS = ("git_branch", "branch")
BRANCH_SUBTYPES = ("tmux", "editor")


def branch_tags(sub_event: dict) -> set[str]:
    """`branch:<name>` for the sub-event's git branch, if it has a real one.

    Left to the `[tags.*]` retag rules to map onto a project or issue.
    """
    for field in BRANCH_FIELDS:
        branch = sub_event["data"].get(field)
        if branch and branch != "unknown":
            return {f"branch:{branch}"}
    return set()


def emacs_buffer_name(title: str) -> str | None:
    """Extract the buffer name from an emacs window title.

    Returns None for titles with no file behind them (internal buffers like
    `*scratch*`, or an empty title).
    """
    name = _UNIQUIFY_SUFFIX_RE.sub("", _EMACS_TITLE_SUFFIX_RE.sub("", title).strip()).strip()
    if not name or name.startswith("*"):
        return None
    return name


def _emacs_candidate_filter(window_event: dict) -> Callable[[dict], bool] | None:
    """Build the guard for speculative emacs sub-event matches.

    Every search but the exact-overlap one adopts sub-events that do not
    overlap the window event, so something has to tie the two together.
    The window title names the buffer, and the sub-event
    names the file: requiring the basenames to agree rejects the same-named
    file from another project (`tmp-push-review-gate.md` exists in a dozen
    repos here), which would otherwise produce a confidently wrong project tag.
    """
    buffer_name = emacs_buffer_name(window_event["data"].get("title", ""))
    if buffer_name is None:
        return None

    def matches(sub_event: dict) -> bool:
        return os.path.basename(sub_event["data"].get("file") or "") == buffer_name

    return matches


# Shared sub-event fetch parameters for subtypes with per-app buckets
# (browser, editor). Consumed by both tag extraction (get_browser_tags /
# get_editor_tags) and get_specialized_context, so the two paths can't drift
# out of sync (tmux has a single shared bucket and is handled separately via
# _fetch_tmux_sub_event).
SUBEVENT_SPECS: dict[str, dict[str, Any]] = {
    "browser": {
        "apps": BROWSER_APPS,
        "bucket_pattern": "aw-watcher-web-{app}",
        "app_normalizer": normalize_browser_app,
        "skip_if": _skip_browser_newtab,
    },
    "editor": {
        "apps": ("emacs", "vi", "vim"),
        "bucket_pattern": "aw-watcher-{app}",
        "lookahead_buffer_seconds": {"emacs": EMACS_LOOKAHEAD_BUFFER_SECONDS},
        "candidate_filters": {"emacs": _emacs_candidate_filter},
        "candidate_reach": {"emacs": EMACS_CANDIDATE_REACH},
    },
}


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
        # Deferred "Unhandled <subtype> event" warning for a sub-event that
        # matched no rule but falls through to the remaining extractors (tmux).
        # get_tags() emits it only if nothing else matches either.
        self._pending_unhandled: tuple[str, dict, dict | None] | None = None

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
        self._pending_unhandled = None

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
                if not result:
                    # An empty result is "sub-event found, no rule matched" --
                    # no better answer than the tmux event that fell through,
                    # so that warning is still due.
                    self._emit_pending_unhandled()
                return result

        # Nothing matched at all -- now the sub-event that fell through (see
        # get_tmux_tags) really was unhandled, so report it.
        self._emit_pending_unhandled()
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
            Set of tags if matched, or False if no tmux rule matched -- either
            because tmux isn't applicable (not a terminal, no tmux, or the
            terminal isn't running tmux) or because no `[rules.tmux.*]` matched.

        Unlike browser and editor, an unmatched tmux sub-event does *not* end
        the search: _fetch_tmux_sub_event() treats tmux as applicable for any
        window whose title merely contains the session or window name, so
        returning the empty list here used to skip every `[rules.app.*]` rule
        for those windows -- exactly where the title is the most informative
        thing available.  The "Unhandled tmux event" warning is deferred to
        get_tags(), which emits it only if the app rules come up empty too.
        """
        tmux_event = self._fetch_tmux_sub_event(window_event)
        if tmux_event is None:
            return False  # not applicable, fall through to app rules

        # Use shared subevent tags logic with tmux matcher
        return self._get_subevent_tags(
            window_event=window_event,
            subtype="tmux",
            matchers=[("tags", self._match_tmux_rule)],
            sub_event=tmux_event,
            fall_through_on_no_match=True,
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

        # Check if the pane title matches (if specified).  This is where Claude
        # Code puts the session topic, which is often the only place the subject
        # of the work appears at all.
        title_match = None
        if "pane_title" in rule:
            title_match = re.search(rule["pane_title"], pane_title)
            if not title_match:
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

        # Add capture groups from the pane_title, command and path matches, in
        # the order the matchers are declared above.
        group_lists = [
            match.groups() if match else () for match in (title_match, command_match, path_match)
        ]
        position = 1
        for groups in group_lists:
            for group in groups:
                substitutions[f"${position}"] = group
                position += 1

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
            matchers=[
                ("url_regexp", self._match_url_regexp),
            ],
            **SUBEVENT_SPECS["browser"],
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
            matchers=[
                ("projects", self._match_project),
                ("path_regexp", self._match_path_regexp),
            ],
            **SUBEVENT_SPECS["editor"],
        )

    def _fetch_sub_event(
        self,
        window_event: dict,
        apps: tuple,
        bucket_pattern: str,
        app_normalizer: Callable | None = None,
        skip_if: Callable | None = None,
        lookahead_buffer_seconds: dict[str, float] | None = None,
        candidate_filters: dict[str, Callable] | None = None,
        candidate_reach: dict[str, timedelta] | None = None,
    ) -> tuple[dict | None, str]:
        """Fetch sub-event for a window event (browser, editor, etc).

        Args:
            window_event: The main window event
            apps: Tuple of app names to match
            bucket_pattern: Pattern for bucket ID (e.g., 'aw-watcher-{app}')
            app_normalizer: Optional function to normalize app name
            skip_if: Optional function that returns True if we should skip this sub_event
            lookahead_buffer_seconds: Optional per-app override of the sub-event
                lookahead buffer (see get_corresponding_event), keyed by the raw
                (non-normalized) app name
            candidate_filters: Optional per-app factory building a predicate that
                validates a speculatively matched sub-event against the window
                event, keyed by the raw app name
            candidate_reach: Optional per-app reach for the bracketing sub-event
                search (see get_corresponding_event), keyed by the raw app name

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

        # A per-app predicate validating speculative matches (see
        # get_corresponding_event); None means "don't guess".
        filter_factory = (candidate_filters or {}).get(app)
        candidate_filter = filter_factory(window_event) if filter_factory else None

        # Get the corresponding sub-event
        sub_event = self.event_fetcher.get_corresponding_event(
            window_event,
            bucket_id,
            ignorable=ignorable,
            retry=self.default_retry,
            lookahead_buffer_seconds=(lookahead_buffer_seconds or {}).get(app),
            candidate_filter=candidate_filter,
            candidate_reach=(candidate_reach or {}).get(app),
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
        fall_through_on_no_match: bool = False,
        lookahead_buffer_seconds: dict[str, float] | None = None,
        candidate_filters: dict[str, Callable] | None = None,
        candidate_reach: dict[str, timedelta] | None = None,
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
            fall_through_on_no_match: Return False instead of [] when no rule
                matched, so get_tags() keeps trying the remaining extractors,
                and defer the "Unhandled" warning to get_tags()
            lookahead_buffer_seconds: Optional per-app lookahead buffer override,
                forwarded to _fetch_sub_event (not needed if sub_event provided)
            candidate_filters: Optional per-app validator factories, forwarded to
                _fetch_sub_event (not needed if sub_event provided)
            candidate_reach: Optional per-app bracketing-search reach, forwarded
                to _fetch_sub_event (not needed if sub_event provided)

        Returns:
            Set of tags, empty list if no match, or False if wrong app type
            (or, with fall_through_on_no_match, if no rule matched)
        """
        # If sub_event not provided, fetch it
        if sub_event is None:
            # Check if this is the right app type
            if apps and window_event["data"].get("app", "").lower() not in apps:
                return False

            sub_event, _ = self._fetch_sub_event(
                window_event,
                apps or (),
                bucket_pattern or "",
                app_normalizer,
                skip_if,
                lookahead_buffer_seconds,
                candidate_filters,
                candidate_reach,
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
                    if subtype in BRANCH_SUBTYPES:
                        tags |= branch_tags(sub_event)
                    return tags

        # No rules matched
        if fall_through_on_no_match:
            # Let get_tags() try the remaining extractors; it warns if they all
            # come up empty.
            self._pending_unhandled = (subtype, window_event, sub_event)
            return False

        self._emit_unhandled(subtype, window_event, sub_event)
        return []

    def _emit_unhandled(self, subtype: str, window_event: dict, sub_event: dict | None) -> None:
        """Warn that a sub-event was found but no rule of its type matched."""
        self.log_callback(
            f"Unhandled {subtype} event",
            event=window_event,
            extra={"sub_event": sub_event, "event_type": subtype, "log_event": "unhandled"},
            level=logging.WARNING,
        )

    def _emit_pending_unhandled(self) -> None:
        """Emit a warning deferred by fall_through_on_no_match, if any."""
        if self._pending_unhandled is not None:
            self._emit_unhandled(*self._pending_unhandled)
            self._pending_unhandled = None

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

        Shared by get_tmux_tags() (tag extraction) and get_specialized_context()
        (report/context display), so both stay consistent.

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

        tmux_event = self.event_fetcher.get_corresponding_event(
            window_event,
            tmux_bucket,
            ignorable=True,
            fallback_to_recent=True,
            retry=self.default_retry,
        )

        if not tmux_event:
            return None

        # Verify the window title indicates this terminal is actually running tmux.
        # This prevents non-tmux terminals from incorrectly picking up tmux events
        # from other terminal windows that are running tmux.
        window_title = window_event["data"].get("title", "").lower()
        tmux_session = tmux_event["data"].get("session_name", "").lower()
        tmux_window = tmux_event["data"].get("window_name", "").lower()

        title_indicates_tmux = (
            "tmux" in window_title
            or (tmux_session and tmux_session in window_title)
            or (tmux_window and tmux_window in window_title)
        )

        if not title_indicates_tmux:
            return None

        return tmux_event

    def get_specialized_context(self, window_event: dict) -> dict[str, str | None]:
        """Get specialized context data for a window event (URL, path, tmux info).

        Uses the same code paths as the tag extraction methods to ensure consistency.

        Args:
            window_event: The window event

        Returns:
            Dict with keys: type (browser/editor/terminal/None), data (the context string)
        """
        result: dict[str, str | None] = {"type": None, "data": None}

        # Try browser - same spec as get_browser_tags()
        sub_event, _ = self._fetch_sub_event(window_event, **SUBEVENT_SPECS["browser"])
        if sub_event:
            url = sub_event["data"].get("url", "")
            if url:
                result["type"] = "browser"
                result["data"] = url
            return result

        # Try editor - same spec as get_editor_tags()
        sub_event, _ = self._fetch_sub_event(window_event, **SUBEVENT_SPECS["editor"])
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
