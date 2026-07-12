"""Regression test for CODE_REVIEW_2026-07-12.md #7.

compare.py used to bind the rebindable `config` global at import time
(`from .config import config`). load_custom_config() rebinds config.py's
module-level `config`, but a name imported with `from ... import config`
keeps pointing at the object captured at import time. So if `compare` was
imported before a custom config loaded (test collection, library use, a
second --config run in one process), its comparison silently used the
default tag/exclusive rules instead of the user's config.

The fix reads `config` fresh per call, so the functions always see the
current global.
"""

from __future__ import annotations


def test_compare_functions_see_config_loaded_after_import(tmp_path, monkeypatch) -> None:
    """A custom config loaded after `compare` is imported must reach its funcs."""
    import aw_export_timewarrior.compare as compare
    import aw_export_timewarrior.config as config_module

    custom = tmp_path / "custom.toml"
    custom.write_text('[tags]\nfoo = ["bar"]\n')

    original_config = config_module.config
    try:
        config_module.load_custom_config(str(custom), validate=False)

        captured: list = []
        real_extractor = compare.TagExtractor

        def spy_extractor(config, event_fetcher=None):
            captured.append(config)
            return real_extractor(config=config, event_fetcher=event_fetcher)

        monkeypatch.setattr(compare, "TagExtractor", spy_extractor)

        # Both entry points build a TagExtractor from the module `config`.
        compare.compare_intervals([], [])
        compare.generate_fix_commands(
            {"missing": [], "extra": [], "different_tags": [], "previously_synced": []}
        )

        assert captured, "compare did not build a TagExtractor"
        for cfg in captured:
            assert "foo" in cfg.get("tags", {}), (
                "compare used a stale config: the custom [tags] rule loaded after "
                "import was not seen (config global was pinned at import time)"
            )
    finally:
        config_module.config = original_config
