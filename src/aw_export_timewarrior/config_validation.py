"""Configuration validation for aw-export-timewarrior.

Validates the loaded TOML configuration and warns about potential issues.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when configuration has critical errors."""

    pass


class ConfigValidator:
    """Validates configuration dictionaries."""

    # Known top-level keys
    KNOWN_TOP_LEVEL = {
        "enable_afk_gap_workaround",
        "enable_lid_events",
        "terminal_apps",
        "tuning",
        "tags",
        "rules",
        "exclusive",
    }

    # Known tuning parameters with their types and optional ranges
    TUNING_PARAMS = {
        "aw_warn_threshold": {"type": (int, float), "min": 0},
        "sleep_interval": {"type": (int, float), "min": 0},
        "ignore_interval": {"type": (int, float), "min": 0},
        "min_recording_interval": {"type": (int, float), "min": 0},
        "max_mixed_interval": {"type": (int, float), "min": 0},
        "grace_time": {"type": (int, float), "min": 0},
        "min_tag_recording_interval": {"type": (int, float), "min": 0},
        "stickyness_factor": {"type": (int, float), "min": 0, "max": 1},
        "min_lid_duration": {"type": (int, float), "min": 0},
    }

    # Known rule types and their expected fields
    RULE_TYPES = {
        "browser": {"required": ["url_regexp"], "optional": ["tags", "timew_tags"]},
        "app": {
            "required": ["app_names"],
            "optional": ["title_regexp", "tags", "timew_tags"],
        },
        "editor": {
            "required": [],  # One of path_regexp, project_regexp, or projects
            "optional": [
                "path_regexp",
                "project_regexp",
                "projects",
                "file_regexp",
                "tags",
                "timew_tags",
            ],
        },
        "tmux": {
            "required": [],  # command or path
            "optional": ["command", "path", "tags", "timew_tags"],
        },
    }

    # Known tag rule fields
    TAG_RULE_FIELDS = {"source_tags", "add", "prepend", "remove", "replace"}

    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def validate(self, config: dict[str, Any]) -> tuple[list[str], list[str]]:
        """Validate the configuration.

        Args:
            config: The configuration dictionary to validate

        Returns:
            Tuple of (errors, warnings) lists
        """
        self.errors = []
        self.warnings = []

        self._validate_top_level(config)
        self._validate_tuning(config.get("tuning", {}))
        self._validate_tags(config.get("tags", {}))
        self._validate_rules(config.get("rules", {}))
        self._validate_exclusive(config.get("exclusive", {}))

        return self.errors, self.warnings

    def _validate_top_level(self, config: dict) -> None:
        """Validate top-level configuration keys."""
        for key in config:
            if key not in self.KNOWN_TOP_LEVEL:
                self.warnings.append(f"Unknown top-level config key: '{key}'")

        # Validate specific top-level fields
        if "enable_afk_gap_workaround" in config and not isinstance(
            config["enable_afk_gap_workaround"], bool
        ):
            self.errors.append("'enable_afk_gap_workaround' must be a boolean")

        if "enable_lid_events" in config and not isinstance(config["enable_lid_events"], bool):
            self.errors.append("'enable_lid_events' must be a boolean")

        if "terminal_apps" in config:
            if not isinstance(config["terminal_apps"], list):
                self.errors.append("'terminal_apps' must be a list")
            elif not all(isinstance(app, str) for app in config["terminal_apps"]):
                self.errors.append("'terminal_apps' must be a list of strings")

    def _validate_tuning(self, tuning: dict) -> None:
        """Validate tuning parameters."""
        for key, value in tuning.items():
            if key not in self.TUNING_PARAMS:
                self.warnings.append(f"Unknown tuning parameter: '{key}'")
                continue

            spec = self.TUNING_PARAMS[key]

            # Type check
            if not isinstance(value, spec["type"]):
                expected = (
                    " or ".join(t.__name__ for t in spec["type"])
                    if isinstance(spec["type"], tuple)
                    else spec["type"].__name__
                )
                self.errors.append(f"tuning.{key} must be {expected}, got {type(value).__name__}")
                continue

            # Range check
            if "min" in spec and value < spec["min"]:
                self.errors.append(f"tuning.{key} must be >= {spec['min']}, got {value}")
            if "max" in spec and value > spec["max"]:
                self.errors.append(f"tuning.{key} must be <= {spec['max']}, got {value}")

    def _validate_tags(self, tags: dict) -> None:
        """Validate tag transformation rules."""
        if not isinstance(tags, dict):
            self.errors.append("'tags' section must be a dictionary")
            return

        for tag_name, tag_rule in tags.items():
            if not isinstance(tag_rule, dict):
                self.errors.append(f"tags.{tag_name} must be a dictionary")
                continue

            # Check for unknown fields
            for field in tag_rule:
                if field not in self.TAG_RULE_FIELDS:
                    self.warnings.append(f"Unknown field in tags.{tag_name}: '{field}'")

            # Validate source_tags
            if "source_tags" not in tag_rule:
                self.warnings.append(
                    f"tags.{tag_name} has no 'source_tags' - rule will never match"
                )
            elif not isinstance(tag_rule["source_tags"], list):
                self.errors.append(f"tags.{tag_name}.source_tags must be a list")
            elif len(tag_rule["source_tags"]) == 0:
                self.warnings.append(
                    f"tags.{tag_name}.source_tags is empty - rule will never match"
                )

            # Validate add/prepend/remove/replace
            for field in ["add", "prepend", "remove", "replace"]:
                if field in tag_rule:
                    if not isinstance(tag_rule[field], list):
                        self.errors.append(f"tags.{tag_name}.{field} must be a list")
                    elif len(tag_rule[field]) == 0:
                        self.warnings.append(f"tags.{tag_name}.{field} is empty")

            # Check that at least one action is specified
            has_action = any(f in tag_rule for f in ["add", "prepend", "remove", "replace"])
            if not has_action:
                self.warnings.append(f"tags.{tag_name} has no action (add/remove/replace)")

    def _validate_rules(self, rules: dict) -> None:
        """Validate matching rules."""
        if not isinstance(rules, dict):
            self.errors.append("'rules' section must be a dictionary")
            return

        for rule_type, type_rules in rules.items():
            if rule_type not in self.RULE_TYPES:
                self.warnings.append(f"Unknown rule type: 'rules.{rule_type}'")
                continue

            if not isinstance(type_rules, dict):
                self.errors.append(f"rules.{rule_type} must be a dictionary")
                continue

            for rule_name, rule in type_rules.items():
                self._validate_single_rule(rule_type, rule_name, rule)

    def _validate_single_rule(self, rule_type: str, rule_name: str, rule: dict) -> None:
        """Validate a single matching rule."""
        prefix = f"rules.{rule_type}.{rule_name}"

        if not isinstance(rule, dict):
            self.errors.append(f"{prefix} must be a dictionary")
            return

        # Check for tags field (required for all rules)
        if "tags" not in rule and "timew_tags" not in rule:
            self.errors.append(f"{prefix} is missing 'tags' field")

        # Validate tags is a list
        tags_field = rule.get("tags", rule.get("timew_tags"))
        if tags_field is not None:
            if not isinstance(tags_field, list):
                self.errors.append(f"{prefix}.tags must be a list")
            elif len(tags_field) == 0:
                self.warnings.append(f"{prefix}.tags is empty")

        # Type-specific validation
        if rule_type == "browser":
            self._validate_browser_rule(prefix, rule)
        elif rule_type == "app":
            self._validate_app_rule(prefix, rule)
        elif rule_type == "editor":
            self._validate_editor_rule(prefix, rule)
        elif rule_type == "tmux":
            self._validate_tmux_rule(prefix, rule)

    def _validate_browser_rule(self, prefix: str, rule: dict) -> None:
        """Validate a browser rule."""
        if "url_regexp" not in rule:
            self.errors.append(f"{prefix} is missing 'url_regexp'")
        else:
            self._validate_regexp(prefix, "url_regexp", rule["url_regexp"])

    def _validate_app_rule(self, prefix: str, rule: dict) -> None:
        """Validate an app rule."""
        if "app_names" not in rule:
            self.errors.append(f"{prefix} is missing 'app_names'")
        elif not isinstance(rule["app_names"], list):
            self.errors.append(f"{prefix}.app_names must be a list")
        elif len(rule["app_names"]) == 0:
            self.warnings.append(f"{prefix}.app_names is empty")

        if "title_regexp" in rule:
            self._validate_regexp(prefix, "title_regexp", rule["title_regexp"])

    def _validate_editor_rule(self, prefix: str, rule: dict) -> None:
        """Validate an editor rule."""
        has_matcher = any(
            k in rule for k in ["path_regexp", "project_regexp", "projects", "file_regexp"]
        )
        if not has_matcher:
            self.errors.append(
                f"{prefix} needs one of: path_regexp, project_regexp, projects, file_regexp"
            )

        for field in ["path_regexp", "project_regexp", "file_regexp"]:
            if field in rule:
                self._validate_regexp(prefix, field, rule[field])

        if "projects" in rule and not isinstance(rule["projects"], list):
            self.errors.append(f"{prefix}.projects must be a list")

    def _validate_tmux_rule(self, prefix: str, rule: dict) -> None:
        """Validate a tmux rule."""
        if "command" not in rule and "path" not in rule:
            self.warnings.append(f"{prefix} has no 'command' or 'path' matcher")

        if "command" in rule:
            self._validate_regexp(prefix, "command", rule["command"])
        if "path" in rule:
            self._validate_regexp(prefix, "path", rule["path"])

    def _validate_regexp(self, prefix: str, field: str, pattern: str) -> None:
        """Validate a regular expression."""
        if not isinstance(pattern, str):
            self.errors.append(f"{prefix}.{field} must be a string")
            return

        try:
            re.compile(pattern)
        except re.error as e:
            self.errors.append(f"{prefix}.{field} has invalid regex: {e}")

        # Warn about common regex mistakes
        if pattern.endswith("|"):
            self.warnings.append(f"{prefix}.{field} ends with '|' which matches empty string")

    def _validate_exclusive(self, exclusive: dict) -> None:
        """Validate exclusive tag groups."""
        if not isinstance(exclusive, dict):
            self.errors.append("'exclusive' section must be a dictionary")
            return

        for group_name, group in exclusive.items():
            prefix = f"exclusive.{group_name}"

            if not isinstance(group, dict):
                self.errors.append(f"{prefix} must be a dictionary")
                continue

            if "tags" not in group:
                self.errors.append(f"{prefix} is missing 'tags' field")
            elif not isinstance(group["tags"], list):
                self.errors.append(f"{prefix}.tags must be a list")
            elif len(group["tags"]) < 2:
                self.warnings.append(
                    f"{prefix}.tags has fewer than 2 tags - exclusive group has no effect"
                )


def validate_config(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Validate configuration and return errors and warnings.

    Args:
        config: The configuration dictionary to validate

    Returns:
        Tuple of (errors, warnings) lists
    """
    validator = ConfigValidator()
    return validator.validate(config)


def log_validation_results(errors: list[str], warnings: list[str]) -> None:
    """Log validation results.

    Args:
        errors: List of error messages
        warnings: List of warning messages
    """
    for warning in warnings:
        logger.warning(f"Config warning: {warning}")
    for error in errors:
        logger.error(f"Config error: {error}")


def validate_and_warn(config: dict[str, Any]) -> bool:
    """Validate configuration and log warnings/errors.

    Args:
        config: The configuration dictionary to validate

    Returns:
        True if configuration is valid (no errors), False otherwise
    """
    errors, warnings = validate_config(config)
    log_validation_results(errors, warnings)
    return len(errors) == 0
