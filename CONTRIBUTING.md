# Contributing to aw-export-timewarrior

Contributions are mostly welcome (but do inform about it if you've used AI or other tools). If the length of this text scares you, then I'd rather want you to skip reading and just produce a pull-request in GitHub. If you find it too difficult to write test code, etc, then you may skip it and hope the maintainer will fix it.

## What to include

Every submission should ideally include:

- **Test code** covering the new behaviour or bug fix
- **Documentation** updates where relevant
- **A changelog entry** in `CHANGELOG.md` under `[Unreleased]`

## Commit messages

Please follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) and write messages in the imperative mood:

- `fix: correct time-range handling for AFK transitions`
- `feat: add new tag extraction rule`
- `docs: update README`

Rather than:

- `This commit fixes the time-range handling`
- `Added new tag extraction`

Note: older commits in this repository predate this convention and do not follow it.

## Development setup

```sh
make dev          # install in editable mode with dev dependencies
pre-commit install
pre-commit install --hook-type pre-push
pre-commit install --hook-type commit-msg
pre-commit install --hook-type prepare-commit-msg
pre-commit install --hook-type post-commit
```

Run tests with:

```sh
make test
```
