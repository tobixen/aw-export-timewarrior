"""Tests for app_groups expansion feature."""

import pytest

from aw_export_timewarrior.config import (
    AppGroupExpansionError,
    _expand_all_groups,
    expand_app_groups,
)


class TestExpandAppGroups:
    """Tests for the expand_app_groups function."""

    def test_no_app_groups_returns_config_unchanged(self) -> None:
        """Config without app_groups should be returned unchanged."""
        config = {
            "rules": {
                "app": {
                    "test": {
                        "app_names": ["foot", "xterm"],
                        "tags": ["terminal"],
                    }
                }
            }
        }
        result = expand_app_groups(config)
        assert result["rules"]["app"]["test"]["app_names"] == ["foot", "xterm"]

    def test_basic_expansion(self) -> None:
        """Basic @group reference should expand to the group's apps."""
        config = {
            "app_groups": {
                "terminals": ["foot", "xterm", "terminology"],
            },
            "rules": {
                "app": {
                    "test": {
                        "app_names": ["@terminals"],
                        "tags": ["terminal"],
                    }
                }
            },
        }
        result = expand_app_groups(config)
        assert result["rules"]["app"]["test"]["app_names"] == ["foot", "xterm", "terminology"]

    def test_mixed_expansion(self) -> None:
        """Mix of @group references and literal app names should expand correctly."""
        config = {
            "app_groups": {
                "terminals": ["foot", "xterm"],
            },
            "rules": {
                "app": {
                    "test": {
                        "app_names": ["@terminals", "Signal", "DeltaChat"],
                        "tags": ["mixed"],
                    }
                }
            },
        }
        result = expand_app_groups(config)
        assert result["rules"]["app"]["test"]["app_names"] == [
            "foot",
            "xterm",
            "Signal",
            "DeltaChat",
        ]

    def test_nested_group_expansion(self) -> None:
        """Groups referencing other groups should expand recursively."""
        config = {
            "app_groups": {
                "wayland_terms": ["foot", "alacritty"],
                "x11_terms": ["xterm", "urxvt"],
                "all_terms": ["@wayland_terms", "@x11_terms"],
            },
            "rules": {
                "app": {
                    "test": {
                        "app_names": ["@all_terms"],
                        "tags": ["terminal"],
                    }
                }
            },
        }
        result = expand_app_groups(config)
        assert result["rules"]["app"]["test"]["app_names"] == [
            "foot",
            "alacritty",
            "xterm",
            "urxvt",
        ]

    def test_unknown_group_reference_raises_error(self) -> None:
        """Reference to unknown group should raise AppGroupExpansionError."""
        config = {
            "app_groups": {
                "terminals": ["foot", "xterm"],
            },
            "rules": {
                "app": {
                    "test": {
                        "app_names": ["@unknown_group"],
                        "tags": ["test"],
                    }
                }
            },
        }
        with pytest.raises(AppGroupExpansionError, match="unknown group"):
            expand_app_groups(config)

    def test_circular_reference_raises_error(self) -> None:
        """Circular group references should raise AppGroupExpansionError."""
        config = {
            "app_groups": {
                "group_a": ["@group_b", "app1"],
                "group_b": ["@group_a", "app2"],
            },
            "rules": {"app": {}},
        }
        with pytest.raises(AppGroupExpansionError, match="[Cc]ircular"):
            expand_app_groups(config)

    def test_self_reference_raises_error(self) -> None:
        """Self-referencing group should raise AppGroupExpansionError."""
        config = {
            "app_groups": {
                "recursive": ["@recursive", "app1"],
            },
            "rules": {"app": {}},
        }
        with pytest.raises(AppGroupExpansionError, match="[Cc]ircular"):
            expand_app_groups(config)

    def test_does_not_mutate_original_config(self) -> None:
        """expand_app_groups should not mutate the original config."""
        config = {
            "app_groups": {
                "terminals": ["foot", "xterm"],
            },
            "rules": {
                "app": {
                    "test": {
                        "app_names": ["@terminals"],
                        "tags": ["terminal"],
                    }
                }
            },
        }
        original_app_names = config["rules"]["app"]["test"]["app_names"].copy()
        expand_app_groups(config)
        assert config["rules"]["app"]["test"]["app_names"] == original_app_names

    def test_multiple_rules_expansion(self) -> None:
        """Multiple rules should all have their app_names expanded."""
        config = {
            "app_groups": {
                "terminals": ["foot", "xterm"],
            },
            "rules": {
                "app": {
                    "rule1": {
                        "app_names": ["@terminals"],
                        "title_regexp": "pattern1",
                        "tags": ["tag1"],
                    },
                    "rule2": {
                        "app_names": ["@terminals"],
                        "title_regexp": "pattern2",
                        "tags": ["tag2"],
                    },
                }
            },
        }
        result = expand_app_groups(config)
        assert result["rules"]["app"]["rule1"]["app_names"] == ["foot", "xterm"]
        assert result["rules"]["app"]["rule2"]["app_names"] == ["foot", "xterm"]

    def test_rules_without_app_names_ignored(self) -> None:
        """Rules without app_names field should be skipped without error."""
        config = {
            "app_groups": {
                "terminals": ["foot", "xterm"],
            },
            "rules": {
                "app": {
                    "malformed": {
                        "tags": ["test"],
                        # missing app_names
                    }
                }
            },
        }
        # Should not raise
        result = expand_app_groups(config)
        assert "app_names" not in result["rules"]["app"]["malformed"]


class TestExpandAllGroups:
    """Tests for the _expand_all_groups helper function."""

    def test_simple_groups(self) -> None:
        """Simple groups without references should expand to themselves."""
        app_groups = {
            "terminals": ["foot", "xterm"],
            "browsers": ["chromium", "firefox"],
        }
        result = _expand_all_groups(app_groups)
        assert result == {
            "terminals": ["foot", "xterm"],
            "browsers": ["chromium", "firefox"],
        }

    def test_nested_groups(self) -> None:
        """Nested group references should be fully expanded."""
        app_groups = {
            "base": ["app1"],
            "level1": ["@base", "app2"],
            "level2": ["@level1", "app3"],
        }
        result = _expand_all_groups(app_groups)
        assert result["base"] == ["app1"]
        assert result["level1"] == ["app1", "app2"]
        assert result["level2"] == ["app1", "app2", "app3"]

    def test_diamond_dependency(self) -> None:
        """Diamond-shaped dependencies should work correctly."""
        app_groups = {
            "base": ["app1"],
            "left": ["@base", "left_app"],
            "right": ["@base", "right_app"],
            "combined": ["@left", "@right"],
        }
        result = _expand_all_groups(app_groups)
        # Note: app1 will appear twice since it's in both left and right
        assert result["combined"] == ["app1", "left_app", "app1", "right_app"]
