"""Tests for general list expansion feature (lists section and @ref syntax)."""

import re

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


class TestRegexpExpansion:
    """Tests for @ref expansion in regexp string fields."""

    def test_ref_in_title_regexp(self) -> None:
        config = {
            "lists": {"customers": ["acme", "emca"]},
            "rules": {
                "app": {
                    "cust": {
                        "app_names": ["foot"],
                        "title_regexp": "(@customers)",
                        "tags": ["customer"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["app"]["cust"]["title_regexp"] == "((?:acme|emca))"

    def test_ref_in_url_regexp(self) -> None:
        config = {
            "lists": {"customers": ["acme", "emca"]},
            "rules": {
                "browser": {
                    "cust": {
                        "url_regexp": "^https://(@customers)\\.com/",
                        "tags": ["customer"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["browser"]["cust"]["url_regexp"] == "^https://((?:acme|emca))\\.com/"

    def test_ref_in_path_regexp(self) -> None:
        config = {
            "lists": {"customers": ["acme", "emca"]},
            "rules": {
                "editor": {
                    "cust": {
                        "path_regexp": "^/home/user/(@customers)/",
                        "tags": ["customer"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["editor"]["cust"]["path_regexp"] == "^/home/user/((?:acme|emca))/"

    def test_ref_in_project_regexp(self) -> None:
        config = {
            "lists": {"customers": ["acme", "emca"]},
            "rules": {
                "editor": {
                    "cust": {
                        "project_regexp": "@customers",
                        "tags": ["customer"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["editor"]["cust"]["project_regexp"] == "(?:acme|emca)"

    def test_ref_in_tmux_command(self) -> None:
        config = {
            "lists": {"tools": ["vim", "nvim"]},
            "rules": {
                "tmux": {
                    "editors": {
                        "command": "(@tools)",
                        "tags": ["editing"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["tmux"]["editors"]["command"] == "((?:vim|nvim))"

    def test_ref_in_tmux_path(self) -> None:
        config = {
            "lists": {"customers": ["acme", "emca"]},
            "rules": {
                "tmux": {
                    "cust": {
                        "path": "/home/user/(@customers)/",
                        "tags": ["customer"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["tmux"]["cust"]["path"] == "/home/user/((?:acme|emca))/"

    def test_multiple_refs_in_one_regexp(self) -> None:
        config = {
            "lists": {
                "customers": ["acme", "emca"],
                "envs": ["prod", "staging"],
            },
            "rules": {
                "browser": {
                    "cust": {
                        "url_regexp": "^https://(@customers)-(@envs)\\.com/",
                        "tags": ["customer"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert (
            result["rules"]["browser"]["cust"]["url_regexp"]
            == "^https://((?:acme|emca))-((?:prod|staging))\\.com/"
        )

    def test_bare_ref_without_parens(self) -> None:
        config = {
            "lists": {"customers": ["acme", "emca"]},
            "rules": {
                "editor": {
                    "cust": {
                        "path_regexp": "@customers",
                        "tags": ["customer"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["editor"]["cust"]["path_regexp"] == "(?:acme|emca)"

    def test_bare_ref_does_not_break_anchors(self) -> None:
        """A bare @ref next to other atoms must not leak alternation branches.

        Without (?:...) grouping, '^@projects: (.*)' would expand to
        '^foo|bar: (.*)' which matches 'unrelated bar: secret' despite the
        anchor, and matches 'foo: x' without filling group 1.
        """
        config = {
            "lists": {"projects": ["foo", "bar"]},
            "rules": {
                "app": {
                    "proj": {
                        "app_names": ["foot"],
                        "title_regexp": "^@projects: (.*)",
                        "tags": ["$1"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        pattern = result["rules"]["app"]["proj"]["title_regexp"]
        assert re.search(pattern, "unrelated bar: secret") is None
        match = re.search(pattern, "foo: x")
        assert match is not None
        assert match.group(1) == "x"

    def test_explicit_parens_keep_capture_group_numbering(self) -> None:
        """The conventional '(@ref)' usage still captures the matched item in group 1."""
        config = {
            "lists": {"customers": ["acme", "emca"]},
            "rules": {
                "app": {
                    "cust": {
                        "app_names": ["foot"],
                        "title_regexp": "(@customers)",
                        "tags": ["$1"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        match = re.search(result["rules"]["app"]["cust"]["title_regexp"], "working on emca now")
        assert match is not None
        assert match.group(1) == "emca"

    def test_unknown_ref_in_regexp_raises_error(self) -> None:
        config = {
            "lists": {"customers": ["acme"]},
            "rules": {
                "app": {
                    "cust": {
                        "app_names": ["foot"],
                        "title_regexp": "(@nonexistent)",
                        "tags": ["customer"],
                    }
                }
            },
        }
        with pytest.raises(ListExpansionError):
            expand_list_references(config)

    def test_nested_list_ref_in_regexp(self) -> None:
        config = {
            "lists": {
                "customers": ["acme", "emca"],
                "all_projects": ["@customers", "oss"],
            },
            "rules": {
                "editor": {
                    "proj": {
                        "path_regexp": "(@all_projects)",
                        "tags": ["project"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["editor"]["proj"]["path_regexp"] == "((?:acme|emca|oss))"

    def test_list_items_used_as_regexp_fragments(self) -> None:
        """List items are not escaped — they can be regexp fragments themselves."""
        config = {
            "lists": {"patterns": ["foo.*bar", "baz\\d+"]},
            "rules": {
                "editor": {
                    "pat": {
                        "path_regexp": "(@patterns)",
                        "tags": ["match"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["editor"]["pat"]["path_regexp"] == "((?:foo.*bar|baz\\d+))"

    def test_app_groups_usable_in_regexp(self) -> None:
        config = {
            "app_groups": {"customers": ["acme", "emca"]},
            "rules": {
                "app": {
                    "cust": {
                        "app_names": ["foot"],
                        "title_regexp": "(@customers)",
                        "tags": ["customer"],
                    }
                }
            },
        }
        result = expand_list_references(config)
        assert result["rules"]["app"]["cust"]["title_regexp"] == "((?:acme|emca))"
