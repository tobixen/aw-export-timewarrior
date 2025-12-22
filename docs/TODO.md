# TODO - aw-export-timewarrior

## High Priority

### Recursion safety in tag rules
Add recursion depth limit to `apply_retag_rules()` to prevent infinite loops with circular tag rules.

### Return type annotations
Add missing return type annotations throughout codebase per coding standards.

### Empty tags assertion
Fix or document the confusing assertion on empty tags in `_should_export_accumulator()`.

## Medium Priority

### Further main.py reduction
Continue extracting modules from main.py:
- Event processing pipeline

### Configuration validation
Add validation for configuration values (currently no validation of loaded TOML).

### Error handling consistency
Improve error handling:
- Add logging for caught exceptions
- Use specific exception types
- Document expected vs. exceptional failure cases

## Low Priority

### Performance optimizations
- Event caching in `get_corresponding_event`
- Batch processing for historical sync

### Documentation
- Architecture diagrams
- Performance tuning guide

## Future Directions

### More watchers

#### tmux watcher
Support added for [aw-watcher-tmux](https://github.com/akohlbecker/aw-watcher-tmux):
- Automatic detection of tmux bucket
- Tag extraction with configurable rules (`rules.tmux.*`)
- Variable substitution: `$session`, `$window`, `$command`, `$path`, `$1`, `$2`, etc.
- Default tag `tmux:$command` when no rules match
- Documentation in README.md

#### terminal watcher
Not yet investigated.

### Project split
Consider splitting into three projects:
- `aw-export-tags` - Core functionality without Timewarrior dependency
- `aw-export-timewarrior` - Timewarrior integration
- `timewarrior-check-tags` - Standalone tag management for Timewarrior

All three should share the same config file format.

See **[PROJECT_SPLIT_PLAN.md](PROJECT_SPLIT_PLAN.md)** for detailed implementation plan.

---

*See also: `docs/CODE_REVIEW.md` for detailed code review and improvement suggestions.*
