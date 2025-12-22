from aw_export_timewarrior.tag_extractor import TagExtractor


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
