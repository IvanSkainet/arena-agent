# CodSpeed benchmarks

Performance benchmarks for the hot, CPU-bound paths of the bridge. They are
measured continuously by [CodSpeed](https://codspeed.io) in
`.github/workflows/codspeed.yml`.

## Why the files are named `bench_*.py`

`[tool.pytest.ini_options]` sets `python_files = ["test_*.py"]` and
`testpaths = ["tests"]`, so a benchmark named `test_*.py` here would be
collected by every cell of the ordinary test matrix -- where
`pytest-codspeed` is not installed and the `benchmark` fixture does not
exist. The `bench_` prefix keeps them out of the default run without
needing an ignore list that a future file would have to be added to.

The benchmark job collects them explicitly:

```bash
pytest tests/benchmarks --codspeed \
  -o python_files='bench_*.py' \
  -o addopts=''
```

`-o addopts=''` drops the repository-wide `--cov` flags: coverage tracing
would be measured along with the code under test and would swamp the
signal.

## Running them locally

```bash
python -m pip install pytest-codspeed
codspeed run --mode simulation -- \
  pytest tests/benchmarks --codspeed -o python_files='bench_*.py' -o addopts=''
```

Without the `codspeed` CLI, `pytest tests/benchmarks -o python_files='bench_*.py' -o addopts=''`
still runs each benchmark body once, which is enough to prove they work.

## What is measured

| File | Surface |
| --- | --- |
| `bench_redaction.py` | `arena.observability.redact` -- the credential scrubber on every audit / request-log write |
| `bench_security_ssrf.py` | `arena.security_ssrf` -- URL and address validation for browser/fetch endpoints |
| `bench_handler_params.py` | `arena.handler_params`, `arena.safe_numeric`, `arena.jsonshape` -- request body/query parsing |
| `bench_memory_recall.py` | `arena.memory.recall_score` -- tokenisation and TF scoring for memory recall |

Every benchmark is pure CPU: no sockets, no clocks, no filesystem. The SSRF
cases are chosen so the validator returns before it reaches
`socket.getaddrinfo`, otherwise the measurement would be a DNS lookup.
