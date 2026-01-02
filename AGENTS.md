# Repository Guidelines

## Project Structure & Module Organization

- Python package code lives in `telecode/`.
- Project metadata is in `pyproject.toml`, with dependencies also listed in `requirements.txt`.
- Generated metadata is in `telecode.egg-info/` (do not edit by hand).
- Tests live in `tests/`.
- `README.md` contains user-facing setup and usage details.
- Runtime config is stored in `.telecode` (global: `~/.telecode`, local: `./.telecode`).
- Temporary image files are stored in `./.telecode_tmp/`.

## Build, Test, and Development Commands

- Create a venv and install dependencies:
  - `python3 -m venv .venv`
  - `source .venv/bin/activate`
  - `pip install -r requirements.txt`
- Install the package in editable mode:
  - `pip install -e .`
- Run the server:
  - `telecode`
  - `telecode -v` for verbose logging
- Run tests:
  - `pytest -q`

## Coding Style & Naming Conventions

- Use 4-space indentation for Python and apply it consistently.
- Prefer lower_snake_case for Python files.
- If you adopt a formatter or linter (e.g., ruff), add the command and required config files here.

## Testing Guidelines

- Test runner: `pytest`.
- Tests live in `tests/` and follow `test_*.py` naming.
- Run the full suite with `pytest -q`.

## Commit & Pull Request Guidelines

- Commit message conventions are not established in this repository yet.
- If you adopt a convention (e.g., Conventional Commits), document it here.
- For pull requests, include:
  - A brief description of the change
  - Linked issues (if any)
  - Screenshots for UI changes

## Agent-Specific Instructions

- Keep this file aligned with the actual repo structure and tooling as it evolves.
- Avoid adding commands or paths that are not present in the repository.
