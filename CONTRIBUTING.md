# Contributing to RoomKit UI

Thank you for your interest in contributing to RoomKit UI, a desktop voice
assistant built on [roomkit](https://github.com/roomkit-live/roomkit).

## Development setup

```bash
uv sync --extra dev        # dev tools and every backend in `all`
uv run python -m roomkit_ui
```

`uv sync` alone installs the core only, with no AI backend.

## Workflow

1. Fork the repository and create a feature branch.
2. Make your change, with tests for the behaviour it adds or fixes.
3. Run the same checks as CI (see below).
4. Submit a pull request.

## Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run bandit -r src/ -c pyproject.toml
QT_QPA_PLATFORM=offscreen uv run pytest
```

## Code style

- Python 3.12+, async/await on the qasync event loop.
- Ruff for formatting and linting (line length 99), mypy for types.
- Keep modules cohesive; a file well past ~300 lines or a function past
  ~40 lines is a prompt to split by responsibility.
- English in code, comments, commits and docs.

`CLAUDE.md` lists the architecture and the project's gotchas — read it
before touching the engine, audio wiring, tools or packaging.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
