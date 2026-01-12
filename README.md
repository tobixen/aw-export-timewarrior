# Better Categorizer and Timewarrior Companion

**Problem:** ActivityWatch collects great data, but it's hard to get useful insights from it.

**Solution:** Rule-based categorization that transforms raw ActivityWatch events into meaningful tags with multiple output options.

Currently this script exports data from ActivityWatch into TimeWarrior, but I'm planning to let this be a general categorization/tagging tool with possibility to store things in different backends, possibly including to work as a watcher and reexport data back into ActivityWatch.

## What it does

- **Categorizes** ActivityWatch events using configurable rules (browser URLs, editor files, app names, tmux sessions)
- **Exports** categorized activity to TimeWarrior for time tracking
- Report and analyze commands to aid the user into tweaking the rules and configuration and reexporting the data.

## Installation

### From PyPI

```bash
pip install aw-export-timewarrior
```

### From Source

```bash
git clone https://github.com/tobixen/aw-export-timewarrior
cd aw-export-timewarrior
make install
```

### Running as a Systemd Service

For continuous sync mode, you can run as a systemd user service:

```bash
make enable-service    # Install and start the service
```

Or manually:

```bash
cp misc/aw-export-timewarrior.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now aw-export-timewarrior
```

Check status and logs:

```bash
systemctl --user status aw-export-timewarrior
journalctl --user -u aw-export-timewarrior -f
```

Let me know if you try it or start using it.  Following the SemVer standard, I'm free to break backward compatibility in the 0.x-series - and if I believe I'm the only user, I will most likely do that without any notice.

### Requirements

- Python - It's currently only tested for 3.13.  If you want to use it with older python, let me know.
- [ActivityWatch](https://activitywatch.net/) with aw-watcher-window running
- [TimeWarrior](https://timewarrior.net/) installed

### Optional Watchers

For richer tag extraction, install additional watchers:

- [aw-watcher-web](https://github.com/ActivityWatch/aw-watcher-web) - Extract tags from browser URLs
- [aw-watcher-vim](https://github.com/ActivityWatch/aw-watcher-vim) - Extract tags from Vim file paths
- [activity-watch-mode](https://github.com/pauldub/activity-watch-mode) - Extract tags from Emacs file paths
- [aw-watcher-tmux](https://github.com/akohlbecker/aw-watcher-tmux) - Extract tags from tmux sessions
- [aw-watcher-afk-prompt](https://github.com/tobixen/aw-watcher-afk-prompt) - Prompt for activity description after AFK periods (legacy name: aw-watcher-ask-away)
- [aw-watcher-afk-lid](https://github.com/tobixen/aw-watcher-afk-lid) - Track AFK based on laptop lid state

Support for other watchers may be considered, reach out by email or add an issue or pull request for it.

## Quick Start

```bash
# Continuous sync mode
aw-export-timewarrior sync

# Compare ActivityWatch data with TimeWarrior (dry-run)
aw-export-timewarrior diff --day yesterday

# Apply suggested changes
aw-export-timewarrior diff --day yesterday --apply

# Gain insight into events and rules
aw-export-timewarrior report --from '2 hours ago' --show-rule
aw-export-timewarrior analyze --day yesterday --limit 30
```

## Configuration

Configuration is stored in `~/.config/activitywatch/aw-export-timewarrior/aw-export-timewarrior.toml`.

### Rule Types

- **Browser rules** (`rules.browser.*`): Match URLs with `url_regexp`
- **Editor rules** (`rules.editor.*`): Match by `project` name or `path_regexp`
- **App rules** (`rules.app.*`): Match by `app_names` and `title_regexp`
- **Tmux rules** (`rules.tmux.*`): Match by `session`, `window`, `command`, `path`
- **Tag rules** (`tags.*`): Transform tags with `add`, `remove`, `replace` operations
- **Exclusive rules** (`exclusive.*`): Prevent conflicting tags from combining

### Example Configuration

```toml
[rules.browser.github]
url_regexp = "github\\.com"
tags = ["coding", "github"]

[rules.editor.myproject]
path_regexp = "/home/user/projects/myproject"
tags = ["myproject", "coding"]

[rules.app.slack]
app_names = ["slack", "Slack"]
tags = ["communication", "slack"]

[tags.coding-is-work]
source_tags = ["coding"]
add = ["4WORK"]

[exclusive.afk]
tags = ["afk", "not-afk"]
```

## Commands

| Command | Description |
|---------|-------------|
| `sync` | Continuous sync from ActivityWatch to TimeWarrior |
| `diff` | Compare and generate correction commands |
| `report` | Show activity report with tags |
| `analyze` | Analyze events without exporting |
| `timeline` | Show side-by-side ActivityWatch vs TimeWarrior |
| `validate` | Validate configuration file |

Use `--help` with any command for detailed options.

## Development

```bash
make install-dev      # Install with dev dependencies
make test             # Run tests
make lint             # Run ruff check
make format           # Run ruff format
make clean            # Remove build artifacts
make help             # Show all available targets
```

## Documentation

- [Tracking Algorithm](docs/TRACKING_ALGORITHM.md) - How events are processed and exported
- [Testing Guide](docs/TESTING.md) - Running and writing tests
- [TODO / Changelog](docs/TODO.md) - Completed features and planned work

## Background

This tool bridges ActivityWatch (automatic activity tracking) and TimeWarrior (manual time tracking). See the blog posts for rationale:

- [General thoughts on time tracking](https://www.redpill-linpro.com/techblog/2025/05/13/time-tracking-thoughts.html)
- [Comparison of different software](https://www.redpill-linpro.com/techblog/2025/05/22/time-tracking-software.html)
- [Early experiences on combinging AW and TW](https://www.redpill-linpro.com/techblog/2025/08/21/time-tracking-in-practice.html)

## License

MIT
