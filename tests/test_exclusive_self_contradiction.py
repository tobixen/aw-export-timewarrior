"""`validate` detects exclusive groups that defeat a `[tags.*]` rule.

An exclusive group containing two tags that one `[tags.*]` rule deliberately
produces from a single source tag is silently self-defeating: the `add` is
suppressed (apply_retag_rules logs "Excluding expanding tag rule ...") and the
intended umbrella tag never appears.  This bit `exclusive.secondary` holding
both `safemate` and `safemate-stage` while `[tags.safemate]` added the former
from the latter.  See TODO.md, "Warn about self-contradictory exclusive
groups".
"""

from aw_export_timewarrior.config_validation import ConfigValidator


def _warnings(config: dict) -> list[str]:
    errors, warnings = ConfigValidator().validate(config)
    assert errors == []
    return warnings


def test_add_producing_two_group_members_is_warned() -> None:
    config = {
        "tags": {
            "safemate": {"source_tags": ["safemate-stage", "safemate-prod"], "add": ["safemate"]},
        },
        "exclusive": {
            "secondary": {"tags": ["safemate", "safemate-stage", "caldav"]},
        },
    }
    warnings = _warnings(config)

    contradictions = [w for w in warnings if "exclusive.secondary" in w and "tags.safemate" in w]
    assert len(contradictions) == 1
    assert "safemate-stage" in contradictions[0]
    # The other source tag isn't in the group, so it must not be blamed
    assert "safemate-prod" not in contradictions[0]


def test_replace_is_not_warned_about() -> None:
    """`replace` drops the source tag, so the combination never arises."""
    config = {
        "tags": {
            "safemate": {"source_tags": ["safemate-stage"], "replace": ["safemate"]},
        },
        "exclusive": {"secondary": {"tags": ["safemate", "safemate-stage"]}},
    }

    assert not [w for w in _warnings(config) if "exclusive" in w]


def test_removing_the_source_tag_is_not_warned_about() -> None:
    config = {
        "tags": {
            "safemate": {
                "source_tags": ["safemate-stage"],
                "add": ["safemate"],
                "remove": ["safemate-stage"],
            },
        },
        "exclusive": {"secondary": {"tags": ["safemate", "safemate-stage"]}},
    }

    assert not [w for w in _warnings(config) if "exclusive" in w]


def test_replace_producing_two_group_members_is_warned() -> None:
    """A `replace` can mint a forbidden pair too -- and there it raises."""
    config = {
        "tags": {
            "split": {"source_tags": ["dishes"], "replace": ["4CHORES", "4BREAK"]},
        },
        "exclusive": {"category": {"tags": ["4CHORES", "4BREAK", "4WORK"]}},
    }

    contradictions = [w for w in _warnings(config) if "exclusive.category" in w]
    assert len(contradictions) == 1
    # apply_retag_rules checks exclusivity only on the `add` step, so a pair
    # minted by `replace` reaches the recursive call and raises instead
    assert "silently suppressed" not in contradictions[0]
    assert "cannot take effect" in contradictions[0]


def test_two_group_members_in_one_add_is_warned() -> None:
    """The conflict need not involve the source tag at all."""
    config = {
        "tags": {
            "chores": {"source_tags": ["dishes"], "add": ["4CHORES", "4BREAK"]},
        },
        "exclusive": {"category": {"tags": ["4CHORES", "4BREAK", "4WORK"]}},
    }

    contradictions = [w for w in _warnings(config) if "exclusive.category" in w]
    assert len(contradictions) == 1
    assert "4BREAK" in contradictions[0] and "4CHORES" in contradictions[0]


def test_source_tag_substitution_is_expanded() -> None:
    """`$source_tag` in an add list mints a tag per source tag."""
    config = {
        "tags": {
            "secondary": {"source_tags": ["caldav"], "add": ["4$source_tag"]},
        },
        "exclusive": {"category": {"tags": ["4caldav", "caldav"]}},
    }

    contradictions = [w for w in _warnings(config) if "exclusive.category" in w]
    assert len(contradictions) == 1
    assert "4caldav" in contradictions[0]


def test_unrelated_config_is_not_warned_about() -> None:
    config = {
        "tags": {
            "coding-is-work": {"source_tags": ["coding"], "add": ["4WORK"]},
        },
        "exclusive": {"category": {"tags": ["4WORK", "4BREAK"]}},
    }

    assert not [w for w in _warnings(config) if "exclusive" in w]


def test_prepend_is_treated_like_add() -> None:
    """`prepend` is the legacy spelling of `add`."""
    config = {
        "tags": {
            "safemate": {"source_tags": ["safemate-stage"], "prepend": ["safemate"]},
        },
        "exclusive": {"secondary": {"tags": ["safemate", "safemate-stage"]}},
    }

    assert [w for w in _warnings(config) if "exclusive.secondary" in w]
