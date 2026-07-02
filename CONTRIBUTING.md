# Contributing to Arena Unified Bridge

Thanks for helping improve Arena Unified Bridge.

This project is a local automation bridge. Changes can affect command execution,
file access, browser control, desktop automation, and browser-extension behavior,
so small, well-tested patches are strongly preferred.

## Development setup

```bash
git clone https://github.com/IvanSkainet/arena-agent.git arena-bridge
cd arena-bridge
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
```

Run the bridge locally:

```bash
python unified_bridge.py serve
# default: http://127.0.0.1:8765
# credential file: token.txt
```

## Tests

Full test suite:

```bash
pytest
```

Targeted checks for browser-extension work:

```bash
pytest -q tests/test_chat_extension_assets.py tests/test_chat_extension_adapter_flow.py tests/test_chat_extension_sidepanel_flow.py tests/test_extension_bridge.py tests/test_project_modularity.py
node --check chat_extension/background.js
node --check chat_extension/content.js
node --check chat_extension/parser.js
node --check chat_extension/adapters.js
node --check chat_extension/insert_strategies.js
node --check chat_extension/insert_history.js
node --check chat_extension/adapter_sites.js
node --check chat_extension/popup.js
node --check chat_extension/settings.js
node --check chat_extension/sidepanel.js
```

Python syntax smoke:

```bash
python -m py_compile arena/constants.py unified_bridge.py _arena_helper.py
```

If `ruff` is available:

```bash
ruff check .
```

## Browser extension workflow

1. Edit files in `chat_extension/`.
2. Keep content script order in `chat_extension/manifest.json` intentional.
3. Run the targeted extension tests and `node --check` commands above.
4. Reload the unpacked extension in Chromium/Chrome.
5. Refresh active chat tabs so MV3 content scripts are not stale.

When changing insertion behavior, smoke-test at least:

- ChatGPT;
- Claude;
- Gemini Web;
- Google AI Studio.

Use sidepanel Scan Page diagnostics to verify adapter, composer type, and active
manifest/content/insert script versions.

## Versioning

Bridge version lives in:

- `arena/constants.py`;
- `pyproject.toml`;
- README/CHANGELOG when relevant.

Extension version lives in:

- `chat_extension/manifest.json`;
- `chat_extension/README.md`;
- tests that assert the manifest/readme version.

If content-script diagnostics change, also update:

- `ARENA_CONTENT_SCRIPT_VERSION` in `chat_extension/content.js`;
- `arenaInsertScriptVersion()` in `chat_extension/insert_strategies.js`.

## Release packaging

See [RELEASE.md](RELEASE.md). Release ZIPs should be built from tracked files and
must not include runtime state, credentials, logs, databases, or keys.

## Security-sensitive areas

Be especially careful with changes touching:

- authentication and Bearer-credential handling;
- `/v1/exec` and command safety patterns;
- file upload/download/edit path checks;
- desktop automation pause/resume/revoke controls;
- extension auto-execution policy;
- release packaging exclusions.

Report security issues privately instead of opening a public issue.

## Pull requests

- Keep each PR focused on one concern.
- Include tests or explain why tests are not practical.
- Update docs when behavior changes.
- Prefer clear, direct commit messages.
- Do not commit local credentials, runtime logs, generated databases, or release ZIPs.
