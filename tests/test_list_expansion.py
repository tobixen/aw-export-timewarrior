"""Tests for general list expansion feature (lists section and @ref syntax)."""

import pytest

from aw_export_timewarrior.config import (
    AppGroupExpansionError,
    ListExpansionError,
    expand_list_references,
)
from aw_export_timewarrior.config_validation import validate_config


class TestListsSection:
    """Tests for [lists] section expansion."""

    def test_ref_in_tags_source_tags(self) -> None:
        config = {
            "lists": {"customers": ["acme", "emca"]},
            "tags": {
                "customer": {
                    "source_tags": ["@customers"],
                    "add": ["4RL"],
                }
            },
        }
        result = expand_list_references(config)
        assert result["tags"]["customer"]["source_tags"] == ["acme", "emca"]

    def test_ref_in_tags_add(self) -> None:
        config = {
            "lists": {"work_tags": ["4RL", "not-afk"]},
            "tags": {
                "work": {
                    "source_tags": ["work"],
                    "add": ["@work_tags"],
                }
            },
        }
        result = expand_list_references(config)
        assert result["tags"]["work"]["add"] == ["4RL", "not-afk"]

    def test_ref_in_tags_prepend(self) -> None:
        config = {
            "lists": {"prio": ["urgent"]},
            "tags": {
                "work": {
                    "source_tags": ["work"],
                    "prepend": ["@prio"],
                }
            },
        }
        result = expand_list_references(config)
        assert result["tags"]["work"]["prepend"] == ["urgent"]

    def test_ref_in_tags_remove(self) -> None:
        config = {
            "lists": {"junk": ["tmp", "scratch"]},
            "tags": {
                "cleanup": {
                    "source_tags": ["old"],
                    "remove": ["@junk"],
                }
            },
        }
        result = expand_list_references(config)
        assert result["tags"]["cleanup"]["remove"] == ["tmp", "scratch"]

    def test_ref_in_tags_replace(self) -> None:
        config = {
            "lists": {"aliases": ["alias1", "alias2"]},
            "tags": {
                "r": {
                    "source_tags": ["old"],
                    "replace": ["@aliases"],
                }
            },
        }
        result = expand_list_references(config)
        assert result["tags"]["r"]["replace"] == ["alias1", "alias2"]

    def test_ref_in_exclusive_tags(self) -> None:
        config = {
            "lists": {"customers": ["acme", "emca", "foocorp"]},
            "exclusive": {
                "customer": {"tags": ["@customers"]},
            },
        }
        result = expand_list_references(config)
        assert result["exclusive"]["customer"]["tags"] == ["acme", "emca", "foocorp"]

    def test_ref_in_rules_browser_tags(self) -> None:
        config = {
            "lists": {"work_tags": ["4RL", "not-afk"]},
            "rules": {
                "browser": {
                    "work_sites": {
                        "url_regexp": "^https://acme.com/",
                        "tags": ["@work_tags", "acme"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["browser"]["work_sites"]["tags"] == ["4RL", "not-afk", "acme"]

    def test_ref_in_rules_app_tags(self) -> None:
        config = {
            "lists": {"work_tags": ["4RL", "not-afk"]},
            "rules": {
                "app": {
                    "work_app": {
                        "app_names": ["WorkApp"],
                        "tags": ["@work_tags"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["app"]["work_app"]["tags"] == ["4RL", "not-afk"]

    def test_ref_in_rules_app_app_names(self) -> None:
        config = {
            "lists": {"terminals": ["foot", "xterm"]},
            "rules": {
                "app": {
                    "term_rule": {
                        "app_names": ["@terminals"],
                        "tags": ["terminal"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["app"]["term_rule"]["app_names"] == ["foot", "xterm"]

    def test_ref_in_rules_editor_tags(self) -> None:
        config = {
            "lists": {"oss_tags": ["4OSS", "oss-contrib"]},
            "rules": {
                "editor": {
                    "oss": {
                        "path_regexp": "/oss-project",
                        "tags": ["@oss_tags"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["editor"]["oss"]["tags"] == ["4OSS", "oss-contrib"]

    def test_ref_in_rules_tmux_tags(self) -> None:
        config = {
            "lists": {"work_tags": ["4RL"]},
            "rules": {
                "tmux": {
                    "work_tmux": {
                        "path": "/work",
                        "tags": ["@work_tags", "tmux"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["tmux"]["work_tmux"]["tags"] == ["4RL", "tmux"]

    def test_mixed_literals_and_refs(self) -> None:
        config = {
            "lists": {"customers": ["acme", "emca"]},
            "exclusive": {
                "customer": {"tags": ["literal-first", "@customers", "literal-last"]},
            },
        }
        result = expand_list_references(config)
        assert result["exclusive"]["customer"]["tags"] == [
            "literal-first",
            "acme",
            "emca",
            "literal-last",
        ]

    def test_multiple_refs_in_same_list(self) -> None:
        config = {
            "lists": {
                "customers": ["acme", "emca"],
                "internal": ["monitoring"],
            },
            "exclusive": {
                "secondary": {"tags": ["@customers", "@internal", "oss-contrib"]},
            },
        }
        result = expand_list_references(config)
        assert result["exclusive"]["secondary"]["tags"] == [
            "acme",
            "emca",
            "monitoring",
            "oss-contrib",
        ]

    def test_nested_list_refs(self) -> None:
        config = {
            "lists": {
                "customers": ["acme", "emca"],
                "all_projects": ["@customers", "oss-contrib"],
            },
            "exclusive": {
                "projects": {"tags": ["@all_projects"]},
            },
        }
        result = expand_list_references(config)
        assert result["exclusive"]["projects"]["tags"] == ["acme", "emca", "oss-contrib"]

    def test_unknown_ref_raises_error(self) -> None:
        config = {
            "lists": {"customers": ["acme"]},
            "exclusive": {
                "bad": {"tags": ["@nonexistent"]},
            },
        }
        with pytest.raises(ListExpansionError):
            expand_list_references(config)

    def test_circular_ref_raises_error(self) -> None:
        config = {
            "lists": {
                "a": ["@b"],
                "b": ["@a"],
            },
            "exclusive": {"x": {"tags": ["@a"]}},
        }
        with pytest.raises(ListExpansionError):
            expand_list_references(config)

    def test_does_not_mutate_original(self) -> None:
        config = {
            "lists": {"customers": ["acme"]},
            "exclusive": {"customer": {"tags": ["@customers"]}},
        }
        original = config["exclusive"]["customer"]["tags"].copy()
        expand_list_references(config)
        assert config["exclusive"]["customer"]["tags"] == original

    def test_app_groups_also_available_as_refs_in_tags(self) -> None:
        """app_groups entries should be usable as @refs in tags and exclusive, not just app_names."""
        config = {
            "app_groups": {"terminals": ["foot", "xterm"]},
            "tags": {
                "terminal_tag": {
                    "source_tags": ["terminal"],
                    "add": ["@terminals"],
                }
            },
        }
        result = expand_list_references(config)
        assert result["tags"]["terminal_tag"]["add"] == ["foot", "xterm"]

    def test_lists_and_app_groups_merged(self) -> None:
        """Both [lists] and [app_groups] refs should be resolvable together."""
        config = {
            "app_groups": {"terminals": ["foot"]},
            "lists": {"customers": ["acme"]},
            "exclusive": {
                "mixed": {"tags": ["@terminals", "@customers"]},
            },
        }
        result = expand_list_references(config)
        assert result["exclusive"]["mixed"]["tags"] == ["foot", "acme"]

    def test_no_lists_returns_unchanged(self) -> None:
        config = {
            "exclusive": {"x": {"tags": ["acme", "emca"]}},
        }
        result = expand_list_references(config)
        assert result["exclusive"]["x"]["tags"] == ["acme", "emca"]


class TestListsValidation:
    """Tests for [lists] section in config validation."""

    def test_lists_is_known_top_level_key(self) -> None:
        config = {"lists": {"customers": ["acme", "emca"]}}
        errors, warnings = validate_config(config)
        assert not any("lists" in w.lower() and "unknown" in w.lower() for w in warnings)

    def test_lists_must_be_dict(self) -> None:
        config = {"lists": ["not", "a", "dict"]}
        errors, warnings = validate_config(config)
        assert any("lists" in e for e in errors)

    def test_lists_entries_must_be_lists(self) -> None:
        config = {"lists": {"customers": "not-a-list"}}
        errors, warnings = validate_config(config)
        assert any("lists" in e for e in errors)

    def test_lists_entries_must_be_strings(self) -> None:
        config = {"lists": {"customers": [123, "acme"]}}
        errors, warnings = validate_config(config)
        assert any("lists" in e for e in errors)

    def test_empty_list_warns(self) -> None:
        config = {"lists": {"empty": []}}
        errors, warnings = validate_config(config)
        assert any("lists" in w and "empty" in w.lower() for w in warnings)

    def test_valid_lists_no_errors(self) -> None:
        config = {"lists": {"customers": ["acme", "emca"], "internal": ["monitoring"]}}
        errors, warnings = validate_config(config)
        assert len(errors) == 0

    def test_app_groups_error_is_also_list_expansion_error(self) -> None:
        """AppGroupExpansionError should be an alias/subclass of ListExpansionError."""
        assert AppGroupExpansionError is ListExpansionError or issubclass(
            AppGroupExpansionError, ListExpansionError
        )
