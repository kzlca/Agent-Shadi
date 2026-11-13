# Development and publishing notes

The complete Agent Shadi v1.8.37 source tree is now present in this repository on the `main` branch.

## Clone and run

```bash
git clone https://github.com/kzlca/Agent-Shadi.git
cd Agent-Shadi
chmod +x run.sh
./run.sh
```

Windows users can double-click `run_windows.bat`. macOS users can run `./run_macos.command`. Once the service starts, open http://127.0.0.1:8765.

## Contribute changes

Before committing, inspect the staged file list:

```bash
git status --short
git diff --cached --stat
python -m pytest -q
```

Never publish local `data/`, `config.json`, browser profiles, exports, logs, `.env` files, or local SQLite databases.

## Licensing

The current source distribution uses the PolyForm Noncommercial License 1.0.0. It is source-available, not OSI-approved open source. Commercial use requires separate written permission. See [LICENSE](LICENSE) and [COMMERCIAL-LICENSING.md](COMMERCIAL-LICENSING.md).

The repository history contains an earlier MIT-licensed publication of the v1.8.37 source. Changing the current license does not retroactively cancel rights already granted to recipients of that earlier copy. See the README for the licensing context.
