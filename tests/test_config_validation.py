"""Tests for configuration validation."""

from aw_export_timewarrior.config_validation import validate_config


class TestConfigValidator:
    """Tests for ConfigValidator class."""

    def test_empty_config_is_valid(self) -> None:
        """Empty config should be valid (uses defaults)."""
        errors, warnings = validate_config({})
        assert len(errors) == 0

    def test_unknown_top_level_key_warns(self) -> None:
        """Unknown top-level keys should produce warnings."""
        config = {"unknown_key": "value"}
        errors, warnings = validate_config(config)
        assert len(errors) == 0
        assert any("unknown_key" in w.lower() for w in warnings)

    def test_enable_afk_gap_workaround_must_be_bool(self) -> None:
        """enable_afk_gap_workaround must be a boolean."""
        config = {"enable_afk_gap_workaround": "yes"}
        errors, warnings = validate_config(config)
        assert any("enable_afk_gap_workaround" in e and "boolean" in e for e in errors)

    def test_terminal_apps_must_be_list(self) -> None:
        """terminal_apps must be a list."""
        config = {"terminal_apps": "foot"}
        errors, warnings = validate_config(config)
        assert any("terminal_apps" in e and "list" in e for e in errors)

    def test_terminal_apps_must_be_list_of_strings(self) -> None:
        """terminal_apps must be a list of strings."""
        config = {"terminal_apps": ["foot", 123, "xterm"]}
        errors, warnings = validate_config(config)
        assert any("terminal_apps" in e and "strings" in e for e in errors)


class TestTuningValidation:
    """Tests for tuning parameter validation."""

    def test_valid_tuning_params(self) -> None:
        """Valid tuning parameters should pass."""
        config = {
            "tuning": {
                "sleep_interval": 30.0,
                "ignore_interval": 3,
                "stickyness_factor": 0.5,
            }
        }
        errors, warnings = validate_config(config)
        assert len(errors) == 0

    def test_unknown_tuning_param_warns(self) -> None:
        """Unknown tuning parameters should produce warnings."""
        config = {"tuning": {"unknown_param": 42}}
        errors, warnings = validate_config(config)
        assert any("unknown_param" in w.lower() for w in warnings)

    def test_tuning_param_wrong_type(self) -> None:
        """Tuning parameters with wrong type should error."""
        config = {"tuning": {"sleep_interval": "thirty"}}
        errors, warnings = validate_config(config)
        assert any("sleep_interval" in e for e in errors)

    def test_tuning_param_negative_value(self) -> None:
        """Negative tuning parameters should error."""
        config = {"tuning": {"sleep_interval": -10}}
        errors, warnings = validate_config(config)
        assert any("sleep_interval" in e and ">=" in e for e in errors)

    def test_stickyness_factor_must_be_0_to_1(self) -> None:
        """stickyness_factor must be between 0 and 1."""
        config = {"tuning": {"stickyness_factor": 1.5}}
        errors, warnings = validate_config(config)
        assert any("stickyness_factor" in e and "<=" in e for e in errors)


class TestTagRulesValidation:
    """Tests for tag transformation rules validation."""

    def test_valid_tag_rule(self) -> None:
        """Valid tag rule should pass."""
        config = {
            "tags": {
                "work": {
                    "source_tags": ["coding", "programming"],
                    "add": ["4work"],
                }
            }
        }
        errors, warnings = validate_config(config)
        assert len(errors) == 0

    def test_tag_rule_missing_source_tags_warns(self) -> None:
        """Tag rule without source_tags should warn."""
        config = {"tags": {"work": {"add": ["4work"]}}}
        errors, warnings = validate_config(config)
        assert any("source_tags" in w for w in warnings)

    def test_tag_rule_empty_source_tags_warns(self) -> None:
        """Tag rule with empty source_tags should warn."""
        config = {"tags": {"work": {"source_tags": [], "add": ["4work"]}}}
        errors, warnings = validate_config(config)
        assert any("source_tags" in w and "empty" in w for w in warnings)

    def test_tag_rule_source_tags_must_be_list(self) -> None:
        """source_tags must be a list."""
        config = {"tags": {"work": {"source_tags": "coding", "add": ["4work"]}}}
        errors, warnings = validate_config(config)
        assert any("source_tags" in e and "list" in e for e in errors)

    def test_tag_rule_no_action_warns(self) -> None:
        """Tag rule without add/remove/replace should warn."""
        config = {"tags": {"work": {"source_tags": ["coding"]}}}
        errors, warnings = validate_config(config)
        assert any("no action" in w.lower() for w in warnings)

    def test_tag_rule_unknown_field_warns(self) -> None:
        """Unknown field in tag rule should warn."""
        config = {
            "tags": {
                "work": {
                    "source_tags": ["coding"],
                    "add": ["4work"],
                    "unknown_field": "value",
                }
            }
        }
        errors, warnings = validate_config(config)
        assert any("unknown_field" in w for w in warnings)


class TestMatchingRulesValidation:
    """Tests for matching rules validation."""

    def test_valid_browser_rule(self) -> None:
        """Valid browser rule should pass."""
        config = {
            "rules": {
                "browser": {
                    "github": {
                        "url_regexp": "github\\.com",
                        "tags": ["coding", "github"],
                    }
                }
            }
        }
        errors, warnings = validate_config(config)
        assert len(errors) == 0

    def test_browser_rule_missing_url_regexp(self) -> None:
        """Browser rule without url_regexp should error."""
        config = {"rules": {"browser": {"github": {"tags": ["github"]}}}}
        errors, warnings = validate_config(config)
        assert any("url_regexp" in e for e in errors)

    def test_browser_rule_invalid_regexp(self) -> None:
        """Browser rule with invalid regexp should error."""
        config = {
            "rules": {
                "browser": {
                    "bad": {
                        "url_regexp": "[invalid(regex",
                        "tags": ["test"],
                    }
                }
            }
        }
        errors, warnings = validate_config(config)
        assert any("invalid regex" in e.lower() for e in errors)

    def test_browser_rule_trailing_pipe_warns(self) -> None:
        """Browser rule with trailing pipe in regexp should warn."""
        config = {
            "rules": {
                "browser": {
                    "bad": {
                        "url_regexp": "github|gitlab|",
                        "tags": ["coding"],
                    }
                }
            }
        }
        errors, warnings = validate_config(config)
        assert any("ends with '|'" in w for w in warnings)

    def test_valid_app_rule(self) -> None:
        """Valid app rule should pass."""
        config = {
            "rules": {
                "app": {
                    "signal": {
                        "app_names": ["Signal", "signal-desktop"],
                        "tags": ["communication"],
                    }
                }
            }
        }
        errors, warnings = validate_config(config)
        assert len(errors) == 0

    def test_app_rule_missing_app_names(self) -> None:
        """App rule without app_names should error."""
        config = {"rules": {"app": {"signal": {"tags": ["communication"]}}}}
        errors, warnings = validate_config(config)
        assert any("app_names" in e for e in errors)

    def test_app_rule_with_title_regexp(self) -> None:
        """App rule with title_regexp should validate the regexp."""
        config = {
            "rules": {
                "app": {
                    "term": {
                        "app_names": ["foot"],
                        "title_regexp": "[invalid",
                        "tags": ["terminal"],
                    }
                }
            }
        }
        errors, warnings = validate_config(config)
        assert any("title_regexp" in e and "invalid regex" in e.lower() for e in errors)

    def test_valid_editor_rule(self) -> None:
        """Valid editor rule should pass."""
        config = {
            "rules": {
                "editor": {
                    "python": {
                        "path_regexp": "\\.py$",
                        "tags": ["coding", "python"],
                    }
                }
            }
        }
        errors, warnings = validate_config(config)
        assert len(errors) == 0

    def test_editor_rule_no_matcher(self) -> None:
        """Editor rule without any matcher should error."""
        config = {"rules": {"editor": {"test": {"tags": ["test"]}}}}
        errors, warnings = validate_config(config)
        assert any("needs one of" in e for e in errors)

    def test_valid_tmux_rule(self) -> None:
        """Valid tmux rule should pass."""
        config = {
            "rules": {
                "tmux": {
                    "claude": {
                        "command": "claude",
                        "tags": ["ai", "claude"],
                    }
                }
            }
        }
        errors, warnings = validate_config(config)
        assert len(errors) == 0

    def test_rule_missing_tags(self) -> None:
        """Rule without tags field should error."""
        config = {"rules": {"browser": {"test": {"url_regexp": "test"}}}}
        errors, warnings = validate_config(config)
        assert any("tags" in e.lower() for e in errors)

    def test_unknown_rule_type_warns(self) -> None:
        """Unknown rule type should warn."""
        config = {"rules": {"unknown_type": {"test": {"tags": ["test"]}}}}
        errors, warnings = validate_config(config)
        assert any("unknown_type" in w for w in warnings)


class TestExclusiveValidation:
    """Tests for exclusive group validation."""

    def test_valid_exclusive_group(self) -> None:
        """Valid exclusive group should pass."""
        config = {"exclusive": {"category": {"tags": ["4work", "4break", "4chores"]}}}
        errors, warnings = validate_config(config)
        assert len(errors) == 0

    def test_exclusive_group_missing_tags(self) -> None:
        """Exclusive group without tags should error."""
        config = {"exclusive": {"category": {}}}
        errors, warnings = validate_config(config)
        assert any("tags" in e for e in errors)

    def test_exclusive_group_tags_must_be_list(self) -> None:
        """Exclusive group tags must be a list."""
        config = {"exclusive": {"category": {"tags": "4work"}}}
        errors, warnings = validate_config(config)
        assert any("tags" in e and "list" in e for e in errors)

    def test_exclusive_group_fewer_than_2_tags_warns(self) -> None:
        """Exclusive group with fewer than 2 tags should warn."""
        config = {"exclusive": {"category": {"tags": ["4work"]}}}
        errors, warnings = validate_config(config)
        assert any("fewer than 2" in w for w in warnings)


class TestLegacyFieldSupport:
    """Tests for legacy field names (timew_tags, prepend)."""

    def test_timew_tags_is_accepted(self) -> None:
        """timew_tags should be accepted as alternative to tags."""
        config = {
            "rules": {
                "browser": {
                    "github": {
                        "url_regexp": "github\\.com",
                        "timew_tags": ["coding"],
                    }
                }
            }
        }
        errors, warnings = validate_config(config)
        assert len(errors) == 0

    def test_prepend_is_accepted(self) -> None:
        """prepend should be accepted as alternative to add."""
        config = {
            "tags": {
                "work": {
                    "source_tags": ["coding"],
                    "prepend": ["4work"],
                }
            }
        }
        errors, warnings = validate_config(config)
        assert len(errors) == 0
