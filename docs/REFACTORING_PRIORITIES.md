# aw-export-timewarrior: Refactoring Priorities & Improvements

Based on comprehensive codebase analysis performed on 2025-12-10.

## Priority List: Refactorings & Improvements

### 🔴 **CRITICAL (Fix Immediately)**

1. **Fix missing `validate_config()` function**
   - Location: `src/aw_export_timewarrior/config.py`
   - Issue: The `validate` subcommand is broken - imports non-existent function
   - Impact: Feature doesn't work at all
   - Effort: Low (1-2 hours)

2. **Remove disabled breakpoints in production**
   - Location: `src/aw_export_timewarrior/main.py:15` - Remove `breakpoint = lambda: None`
   - Issue: 11 `breakpoint()` calls throughout code
   - Action: Replace with proper error handling using `enable_pdb` flag
   - Impact: Debugging statements in production code
   - Effort: Low (2-3 hours)

3. **Fix unsafe counter/state management**
   - Location: `src/aw_export_timewarrior/main.py` - Counters reset in multiple places
   - Issue: `tags_accumulated_time`, `total_time_known_events`, etc. modified without clear ownership
   - Action: Create explicit `StateManager` class with clear ownership
   - Impact: Hard-to-track bugs, race conditions
   - Effort: Medium (1-2 days)

### 🟠 **HIGH PRIORITY (Schedule Soon)**

4. **Introduce Ruff for linting and formatting**
   - Action:
     - Add ruff to dev dependencies in `pyproject.toml`
     - Configure in `pyproject.toml` with ruff rules
     - Run `ruff check` and `ruff format`
   - Impact: Consistent code style, catch common errors
   - Effort: Low (2-4 hours)

5. **Break up God Class: Exporter (1475 lines)**
   - Location: `src/aw_export_timewarrior/main.py:207-1475`
   - Issue: Single class with 60+ attributes handling everything
   - Action: Extract into:
     - `EventFetcher`: Fetch data from ActivityWatch
     - `TagExtractor`: Extract tags from events using rules
     - `StateManager`: Manage last_tick, counters, afk state
     - `TimewManager`: All TimeWarrior interactions
     - `Exporter`: Orchestrator coordinating the above
   - Impact: Maintainability, testability, comprehension
   - Effort: High (2-3 weeks)

6. **Move hard-coded constants to config**
   - Location: `src/aw_export_timewarrior/main.py:178-192`
   - Issue: Configuration loaded from environment variables instead of config file
   - Action: Move to `config.toml` with `[tuning]` section
   - Constants: `AW_WARN_THRESHOLD`, `SLEEP_INTERVAL`, `IGNORE_INTERVAL`, etc.
   - Impact: User configurability, cleaner code
   - Effort: Low (4-6 hours)

7. **Fix confusing return types**
   - Location: `find_tags_from_event()` in `main.py:1060-1071`
   - Issue: Returns `None` OR `False` OR `Set[str]` (three different types!)
   - Action: Use enum/dataclass for clear semantics:
     ```python
     @dataclass
     class TagResult:
         result: EventMatchResult  # IGNORED, NO_MATCH, MATCHED
         tags: Set[str] = field(default_factory=set)
         reason: str = ""
     ```
   - Impact: Clarity, fewer bugs in calling code
   - Effort: Medium (1 day)

8. **Add comprehensive type annotations**
   - Location: Throughout codebase
   - Issue: Missing return types on many functions
   - Requirement: Per user's `~/.claude/CLAUDE.md`: "add return type annotations even to test functions"
   - Impact: Type safety, better IDE support, catch bugs early
   - Effort: Medium (2-3 days)

### 🟡 **MEDIUM PRIORITY (Plan & Execute)**

9. **Reduce code duplication in tag matching**
   - Location: `_match_project()`, `_match_path_regexp()`, `_match_url_regexp()` in `main.py`
   - Issue: Similar methods with duplicated logic
   - Action: Consolidate using strategy pattern
   - Impact: DRY principle, easier to extend with new matchers
   - Effort: Medium (1-2 days)

10. **Simplify `find_next_activity()` method**
    - Location: `main.py:1073-1239` (166 lines)
    - Issue: Deeply nested (5 levels), multiple responsibilities
    - Action: Break into smaller methods:
      - `_fetch_and_filter_events()`
      - `_process_single_event()`
      - `_handle_event_tags()`
    - Impact: Readability, testability
    - Effort: Medium (2-3 days)

11. **Replace magic numbers with named constants**
    - Locations throughout `main.py`:
      - `MIN_RECORDING_INTERVAL-3` (why -3?)
      - `< 0.3` (what does 0.3 represent?)
      - `timedelta(seconds=15)` (why 15 seconds?)
    - Action: Define named constants with explanatory comments
    - Impact: Clarity, easier tuning
    - Effort: Low (1 day)

12. **Complete unit tests**
    - Location: `tests/test_unit.py` - Currently just TODO comment
    - Action: Add tests for:
      - Tag extraction logic
      - State management and counter resets
      - Rule matching algorithms
      - Statistics calculations
    - Impact: Confidence in refactoring, catch regressions
    - Effort: Medium (1 week)

13. **Add edge case tests**
    - Missing tests for:
      - Overlapping intervals
      - Rapid AFK transitions
      - Config validation
      - Malformed data
      - Boundary conditions
    - Impact: Bug prevention, regression safety
    - Effort: Medium (3-4 days)

14. **Improve error handling**
    - Locations: Throughout codebase
    - Issues:
      - Bare `except` clauses catching all exceptions
      - No validation of config file structure
      - Silent failures
    - Action:
      - Use specific exception types
      - Add custom exceptions with clear messages
      - Validate inputs early
    - Impact: Better debugging, clearer errors for users
    - Effort: Medium (1 week)

### 🟢 **LOW PRIORITY (Nice to Have)**

15. **Create abstraction layer for time trackers**
    - Location: TimeWarrior code scattered throughout
    - Issue: Tight coupling to TimeWarrior, hard to support other backends
    - Action: Create `TimeTracker` ABC with `TimeWarriorBackend` implementation
    - Impact: Flexibility, extensibility (could support Toggl, Clockify, etc.)
    - Effort: High (2-3 weeks)

16. **Layer the architecture**
    - Current: Business logic, I/O, state management all mixed
    - Action: Separate into layers:
      - Presentation: `cli.py` (argument parsing only)
      - Application: `commands.py` (sync, diff, export commands)
      - Domain: `exporter.py`, `tag_extractor.py`, `state.py`
      - Infrastructure: `aw_client.py`, `timew_client.py`
    - Impact: Maintainability, testability, clear boundaries
    - Effort: High (3-4 weeks)

17. **Remove global config state**
    - Location: `src/aw_export_timewarrior/config.py`
    - Issue: Global mutable `config` variable
    - Action:
      - Make config immutable after load
      - Pass config as parameter instead of global
      - Use dependency injection
    - Impact: Testability, thread safety
    - Effort: Medium (1-2 weeks)

18. **Update and improve documentation**
    - Location: `README.md`, docstrings throughout
    - Issues:
      - README has outdated TODOs
      - Missing docstrings for many functions
      - No comprehensive examples
    - Action:
      - Update README to reflect current architecture
      - Document all CLI subcommands with examples
      - Add docstrings with params, returns, side effects
    - Impact: User onboarding, easier maintenance
    - Effort: Medium (1 week)

19. **Improve example config**
    - Location: `src/aw_export_timewarrior/config.py:5-38`
    - Issue: Minimal default config with unhelpful placeholder names
    - Action:
      - Provide comprehensive example config
      - Document each section with comments
      - Include common patterns (GitHub, Gmail, Slack, VS Code, etc.)
      - Separate default config from example config
    - Impact: Easier setup for new users
    - Effort: Low (4-6 hours)

20. **Performance optimizations**
    - Issues:
      - Events processed one at a time even for historical data
      - Inefficient retry logic (recursive with sleep)
      - No caching of recently fetched events
    - Action:
      - Batch process events when doing historical sync
      - Use exponential backoff for retries
      - Cache events within time window
    - Impact: Speed, efficiency for large datasets
    - Effort: Medium (1-2 weeks)

### 🔧 **QUICK WINS (Do First for Momentum)**

21. **Remove backup files**
    - Files: `cli_old.py`, `cli.py.backup`, `retag.py~`
    - Action: Delete and add to `.gitignore`
    - Impact: Cleaner repository
    - Effort: Trivial (5 minutes)

22. **Complete terminal app list**
    - Location: `main.py:1235` - List has `...` ellipsis
    - Action:
      - Add common terminals: alacritty, kitty, gnome-terminal, konsole, terminator, etc.
      - Move to config file as `terminal_apps` list
    - Impact: Fewer false warnings
    - Effort: Low (30 minutes)

23. **Add comprehensive .gitignore**
    - Action: Exclude:
      - `__pycache__/`, `*.pyc`, `*.pyo`
      - `*.egg-info/`
      - `.pytest_cache/`
      - Backup files (`*~`, `*.backup`)
      - IDE files (`.vscode/`, `.idea/`)
    - Impact: Cleaner `git status`
    - Effort: Trivial (10 minutes)

24. **Fix ActivityWatch bug workaround**
    - Location: `main.py:1097-1113`
    - Action:
      - Check if https://github.com/ActivityWatch/aw-watcher-window-wayland/issues/41 is fixed
      - If fixed: remove workaround
      - If not: move to separate well-documented function, add flag to disable
    - Impact: Code clarity
    - Effort: Low (1 hour)

---

## Recommended Execution Order

### **Phase 1: Foundation + Ruff (Week 1-2)**
- ✅ Fix critical issues (#1-3)
- ✅ Introduce Ruff (#4)
- ✅ Quick wins (#21-24)
- ✅ Add type annotations (#8)
- **Goal:** Clean foundation, consistent style, critical bugs fixed

### **Phase 2: Major Refactoring (Week 3-5)**
- Break up Exporter class (#5)
- Move constants to config (#6)
- Fix return types (#7)
- **Goal:** More maintainable architecture

### **Phase 3: Testing & Quality (Week 6-7)**
- Complete unit tests (#12)
- Add edge case tests (#13)
- Improve error handling (#14)
- **Goal:** Confidence in code, regression safety

### **Phase 4: Polish & Optimization (Week 8+)**
- Documentation updates (#18-19)
- Performance work (#20)
- Architecture improvements (#15-17)
- **Goal:** Production-ready, user-friendly

---

## Ruff Configuration

When introducing Ruff (#4), add to `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "N",   # pep8-naming
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "SIM", # flake8-simplify
]
ignore = [
    "E501", # line too long (handled by formatter)
]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["E501"]  # Allow longer lines in tests
```

Usage:
```bash
# Check for issues
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

---

## Technical Debt Summary

**32 TODO comments** found in codebase. Most critical:

| Location | Issue | Priority |
|----------|-------|----------|
| main.py:204-205 | Counter reset strategy | Critical |
| main.py:598 | Statistics handling refactor | High |
| main.py:959 | `self.afk` state management | Critical |
| main.py:1098 | Wayland workaround | Medium |
| main.py:1213 | "This looks like a bug" | High |
| main.py:1360 | Move TimeWarrior code to separate module | Medium |

---

## Success Metrics

After completing refactoring:

- ✅ All tests pass (currently 97 passing)
- ✅ Test coverage > 80%
- ✅ No `breakpoint()` calls in production
- ✅ Ruff passes with 0 errors
- ✅ All functions have type annotations
- ✅ Main class < 500 lines
- ✅ No functions > 50 lines
- ✅ Max cyclomatic complexity < 10
- ✅ No global mutable state
- ✅ README is up-to-date

---

## Notes

- This analysis was performed by AI-assisted code review on 2025-12-10
- Priority levels reflect both impact and urgency
- Effort estimates are approximate and may vary
- Some items depend on others (e.g., #5 should come before #15)
- User has requested return type annotations per `~/.claude/CLAUDE.md`

---

## Contributing

When working on these items:

1. Create a GitHub issue for tracking
2. Create a feature branch
3. Make incremental changes with tests
4. Run full test suite before committing
5. Update this document as items are completed
6. Mark completed items with ✅

---

*Last updated: 2025-12-10*
