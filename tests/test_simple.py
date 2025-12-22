from aw_export_timewarrior.main import parse_message_tags
from aw_export_timewarrior.tag_extractor import TagExtractor


def test_parse_message_tags_simple():
    """Test basic space-separated tags."""
    assert parse_message_tags("food 4FAMILY") == {"food", "4FAMILY"}
    assert parse_message_tags("single") == {"single"}
    assert parse_message_tags("  spaces  around  ") == {"spaces", "around"}


def test_parse_message_tags_preserves_case():
    """Test that original casing is preserved."""
    assert parse_message_tags("4BREAK") == {"4BREAK"}
    assert parse_message_tags("MixedCase UPPER lower") == {"MixedCase", "UPPER", "lower"}


def test_parse_message_tags_quoted_strings():
    """Test that quoted strings are treated as single tags."""
    assert parse_message_tags('"my project" coding') == {"my project", "coding"}
    assert parse_message_tags("4BREAK 'long tag'") == {"4BREAK", "long tag"}
    assert parse_message_tags('"multi word tag"') == {"multi word tag"}


def test_parse_message_tags_empty():
    """Test empty and whitespace-only messages."""
    assert parse_message_tags("") == set()
    assert parse_message_tags("   ") == set()


def test_parse_message_tags_unmatched_quotes():
    """Test fallback behavior for unmatched quotes."""
    # Unmatched quotes fall back to simple split
    result = parse_message_tags('unmatched "quote')
    assert "unmatched" in result
    assert '"quote' in result


def test_exclusive_overlapping():
    config = {
        "exclusive": {
            "fruit": {"tags": ["pears", "apples", "cherries"]},
            "flavor": {"tags": ["sweet", "sour", "salty"]},
        }
    }
    extractor = TagExtractor(config=config, event_fetcher=None)

    assert not extractor.check_exclusive_groups({"sweet", "cherries", "berry", "round"})
    assert extractor.check_exclusive_groups({"sweet", "sour", "cherries", "berry", "round"})
    assert extractor.check_exclusive_groups({"sweet", "cherries", "pears", "round"})
