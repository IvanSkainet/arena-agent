# Contributing to Arena Unified Bridge

Thanks for your interest in improving Arena Unified Bridge! This document covers
how to set up a development environment, run the tests, and submit changes.

## Development setup

```bash
git clone https://github.com/IvanSkainet/arena-agent.git arena-bridge
cd arena-bridge

# Install runtime + dev dependencies
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"   # pytest + ruff
```

## Running the bridge locally

```bash
python unified_bridge.py serve
# Bridge listens on http://127.0.0.1:8765 — token is in token.txt
```

## Running tests

```bash
pytest
```

## Linting

```bash
ruff check .
```

The lint rule set is intentionally conservative right now (`E`, `F`, `W`, `I`)
because the codebase is large and organically grown. As modules get cleaned up
and split out of `unified_bridge.py`, we tighten the rules.

## Branching & commits

This is currently a solo-maintained project. The `master` branch is the
development branch; tagged releases are the production-ready artifacts. If you
open a pull request, please:

- Keep changes focused and reviewable (one concern per PR).
- Run `pytest` and `ruff check .` before submitting.
- Stress-test with the load script before sending PRs that touch request
  handling (`stress-test-v3.sh`).

## Security

This project runs commands on the host on behalf of AI agents. Be especially
careful with changes that touch:

- Authentication (`token.txt`, Bearer handling)
- The `/v1/exec` safety patterns
- The control-lease (pause/resume/revoke) logic

If you find a security issue, please report it privately rather than opening a
public issue.
