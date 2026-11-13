# Contributing to Agent Shadi

Thank you for considering a contribution. Changes that improve reliability, maintainability, accessibility, testing, data quality, or source compatibility are welcome.

## Before opening an issue

- Search existing issues and discussions for the same problem.
- Include the application version, operating system, Python version, and steps to reproduce.
- Remove source content, personal information, credentials, cookies, tokens, private URLs, and browser-profile data from logs or screenshots.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pytest
python -m pytest -q
```

## Contribution guidelines

- Keep changes focused and explain the problem they solve.
- Add or update regression tests for behaviour changes.
- Preserve source provenance and distinguish current-run captures from historical data.
- Do not introduce automatic channel discovery or channel switching; collection remains one manually selected page per run unless a future design is explicitly reviewed.
- Never log or transmit browser credentials, cookies, local storage values, or raw source content unless a user-facing feature explicitly requires it and obtains informed consent.
- Do not claim full date coverage without verifiable boundary evidence.
- Update `CHANGELOG.md` and relevant documentation for user-visible changes.
- Avoid committing `data/`, `config.json`, browser profiles, exports, logs, `.env` files, virtual environments, or local databases.

## License for contributions

Before submitting a pull request, make sure you have the right to contribute the code and documentation. Unless a separate written agreement says otherwise, contributions accepted into this project are intended to be distributed under the project's PolyForm Noncommercial License 1.0.0. The maintainer may ask for additional written confirmation before accepting a contribution.

## Pull requests

A pull request should include:

1. A concise problem statement and implementation summary.
2. Tests added or updated, plus the command and result.
3. Any user-visible behaviour or migration implications.
4. Screenshots or short recordings for visual changes, with sensitive information removed.
