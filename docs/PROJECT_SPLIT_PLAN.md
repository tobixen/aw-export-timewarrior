# Project Restructuring Plan: aw-tagger

## Vision

**Problem:** ActivityWatch collects great data, but it's hard to get useful insights from it.

**Solution:** Rule-based categorization that transforms raw ActivityWatch events into meaningful tags with multiple output options.

## New Name: `aw-tagger`

Rename from `aw-export-timewarrior` to `aw-tagger` to reflect the core value proposition.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    aw-tagger                        │
│  (Rule-based categorization for ActivityWatch)     │
├─────────────────────────────────────────────────────┤
│  Input: ActivityWatch events                        │
│  ├── Window events (app, title)                    │
│  ├── AFK events                                    │
│  ├── Browser events (URL)                          │
│  ├── Editor events (file, project)                 │
│  └── Optional: tmux, lid, ask-away                 │
│                                                     │
│  Core Engine:                                       │
│  ├── Tag extraction rules                          │
│  ├── Retag/expansion rules                         │
│  ├── Exclusive group validation                    │
│  └── TOML config format                            │
│                                                     │
│  Outputs:                                           │
│  ├── aw-watcher-tags bucket (meta watcher)         │
│  ├── Timewarrior (optional)                        │
│  ├── Statistics/reports                            │
│  └── JSON/CSV export                               │
└─────────────────────────────────────────────────────┘
```

## CLI Commands

Comments:

* I think we should go for a symmetric design where timew is one "backend" while aw is another "backend".  So while `aw-tagger timew sync` (or `ad-tagger sync timew`?) takes data from activitywatch and stores tags into timew, `aw-tagger aw sync` could take data from aw and store tags into an aw bucket.  Except, "aw" is not a good name for this, as it's aw both on the input side and output side.  Better suggestions?
* We will need an `aw-tagger aw diff` also.

```bash
# Core commands (always available)
aw-tagger sync              # Tag events and write to aw-watcher-tags bucket
aw-tagger analyze           # Show what tags would be extracted
aw-tagger report            # Activity statistics
aw-tagger export            # Export tagged events (JSON/CSV)
aw-tagger validate          # Validate config

# Timewarrior commands (when timewarrior installed)
aw-tagger timew sync        # Sync to Timewarrior
aw-tagger timew diff        # Compare AW vs Timewarrior
aw-tagger timew retag       # Apply retag rules to current interval
```

## Meta Watcher Output

Create an `aw-watcher-tags` bucket with tagged events:

```python
# Event structure
{
    "timestamp": "2025-12-22T10:00:00Z",
    "duration": 300,
    "data": {
        "tags": ["coding", "python", "4work"],
        "category": "4work",  # Primary exclusive group match
        "source": {
            "app": "Emacs",
            "title": "main.py - aw-tagger"
        }
    }
}
```

**Benefits:**
- Tags visible in ActivityWatch web UI timeline
- Works with existing AW visualizations and queries
- Other tools can consume the tagged bucket
- Could integrate with aw-webui's category system

## Installation

```bash
# Core functionality
pip install aw-tagger

# With Timewarrior support
pip install aw-tagger[timewarrior]
```

## Module Restructuring

### Current → New Structure

```
src/aw_export_timewarrior/     →    src/aw_tagger/
├── __init__.py                     ├── __init__.py
├── cli.py                          ├── cli.py
├── config.py                       ├── config.py
├── main.py                         ├── tagger.py (renamed from main.py)
├── tag_extractor.py                ├── tag_extractor.py
├── state.py                        ├── state.py
├── aw_client.py                    ├── aw_client.py
├── utils.py                        ├── utils.py
├── output.py                       ├── output.py
├── report.py                       ├── report.py
├── export.py                       ├── export.py
│                                   │
│                                   ├── outputs/
│                                   │   ├── __init__.py
│                                   │   ├── aw_bucket.py (NEW - meta watcher)
│                                   │   └── timewarrior.py (from timew_tracker.py)
│                                   │
├── timew_tracker.py                │   (moved to outputs/)
├── time_tracker.py                 ├── time_tracker.py (base class)
├── compare.py                      ├── timew/
├── retag.py                        │   ├── compare.py
                                    │   └── retag.py
```

## Config File

Keep same location and format, but rename default:
- Old: `~/.config/activitywatch/aw-export-timewarrior/aw-export-timewarrior.toml`
- New: `~/.config/activitywatch/aw-tagger/config.toml`
- Support old location for backward compatibility during transition

```toml
# Output configuration (NEW section)
[output]
# Which outputs to enable
aw_bucket = true          # Write to aw-watcher-tags bucket
timewarrior = true        # Sync to Timewarrior (if installed)

[output.aw_bucket]
bucket_name = "aw-watcher-tags"

[output.timewarrior]
# Timewarrior-specific settings
grace_time = 30

# Existing config sections remain the same
[rules.browser.github]
url_regexp = "github\\.com"
tags = ["coding", "github"]

[tags.work]
source_tags = ["coding"]
add = ["4work"]

[exclusive.category]
tags = ["4work", "4break", "4chores"]
```

## Implementation Phases

### Phase 1: Meta Watcher Output
1. Create `outputs/aw_bucket.py` to write to ActivityWatch bucket
2. Add `aw-tagger sync` command that writes to `aw-watcher-tags`
3. Test with AW web UI

### Phase 2: Restructure Timewarrior as Output
1. Move timew code to `outputs/timewarrior.py` and `timew/` directory
2. Make timewarrior import optional
3. Update CLI to use `aw-tagger timew sync` etc.

### Phase 3: Rename Package
1. Rename `aw_export_timewarrior` → `aw_tagger`
2. Update all imports
3. Update pyproject.toml, README, docs
4. Keep backward compatibility alias during transition

### Phase 4: Publish
1. Publish to PyPI as `aw-tagger`
2. Update documentation for public audience
3. Archive/redirect old package name

## Backward Compatibility

During transition:
- `aw-export-timewarrior` command still works (alias to `aw-tagger timew sync`)
- Old config location still supported
- Old package name installs new package with deprecation warning

## Benefits of This Approach

1. **Clear value proposition:** "Tag your ActivityWatch data"
2. **Useful without Timewarrior:** Meta watcher works standalone
3. **Single package:** Easier to maintain and install
4. **Extensible:** Easy to add more outputs (Toggl, CSV, etc.)
5. **Better discoverability:** Name reflects what it does

---

*Created: 2025-12-22*
*Updated: 2025-12-22 - Changed from 3-project split to single aw-tagger package*
