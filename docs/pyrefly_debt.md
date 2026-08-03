# pyrefly debt: what is real, what is the checker

`quality_ratchet.py` reports ~742 pyrefly findings. That number is the reason
the **Debt visibility** CI job is red, so it is worth knowing exactly what it
is made of before anyone tries to make it zero.

This page exists because the obvious move — flip a config switch and watch the
number collapse — turns out to be the wrong one, and the reasoning should not
have to be rediscovered.

## The headline finding

**Roughly 90 % of the count is one checker limitation, not 700 defects.**

pyrefly 1.2.0 does not narrow a *union of tuples* when the result is unpacked.
Given the accurate signature

```python
def resolve_home_path(...) -> tuple[Path, None, int] | tuple[None, str, int]:
```

a caller that writes

```python
target_path, err, status = resolve_home_path(...)
if err:
    return None, err, status
target_path.resolve()          # pyrefly: "NoneType has no attribute resolve"
```

still sees `target_path` as `Path | None`. Confirmed with `reveal_type`: the
signature is read correctly, the correlation between tuple elements is lost the
moment it is unpacked.

Indexing instead of unpacking (`parsed[0]`, `parsed[1]`) preserves the
narrowing — but rewriting ~50 handlers into that shape to satisfy a checker is
a worse codebase for a better number.

## The trap: `preset = "basic"`

Switching pyrefly to the `basic` preset takes the count from **742 to 24**, and
it narrows unions correctly. It is still the wrong answer.

`basic` does not fix the narrowing *and* keep the checks. It disables entire
categories. Measured, kind by kind:

| kind | legacy | basic |
| --- | --- | --- |
| `missing-attribute` | 520 | **0 (not reported)** |
| `bad-argument-type` | 71 | **0 (not reported)** |
| `bad-assignment` | 51 | **0 (not reported)** |
| `bad-argument-count` | 11 | **0 (not reported)** |
| `no-matching-overload` | 14 | **0 (not reported)** |
| `unexpected-keyword` | 11 | 11 |
| `not-async` | 5 | 5 |

pyrefly's own `--help` says it plainly: basic enables "a small set of
high-confidence, locally-fixable checks", while "broader call-shape or
assignment validation are disabled".

So `basic` would turn the Debt visibility job green while **removing the
ability to detect the class of bug this project keeps finding**. That is a
green light that means less than the red one it replaced.

## Why the repo is on `legacy` at all

Nothing chose it deliberately. pyrefly has no config of its own here, so it
imports settings from `[tool.mypy]` in `pyproject.toml` — and the mere
*presence* of that section, even completely empty, selects the `legacy` preset:

```
No `pyrefly.toml` found — using settings imported from `[tool.mypy]`
in your `pyproject.toml` (preset: legacy).
```

Verified by bisection in a scratch directory: an empty `pyproject.toml`
narrows fine, `[tool.mypy]` with no options at all does not.

Preset comparison on this tree:

| preset | total | narrows unions | keeps call/assignment checks |
| --- | --- | --- | --- |
| `basic` | 24 | yes | **no** |
| `default` | 801 | no | yes |
| `legacy` (current) | 742 | no | yes |
| `strict` | — | no | yes, plus more |

There is no preset that does both. That is the honest state of the tool as of
1.2.0.

## What the 742 actually contains

| bucket | approx | nature |
| --- | --- | --- |
| union-of-tuples narrowing | ~90 | checker limitation, code is correct |
| optional-dependency stubs | ~110 | `psutil`/`pywin32` guarded by `HAS_*` flags |
| mixin attributes | large share of `missing-attribute` | interfaces supplied by the mixing class |
| genuinely worth fixing | the remainder | real nullability and call-shape debt |

Fixes already taken from this list, each by finding the systemic cause rather
than silencing sites one at a time:

- handler dataclass fields typed `Callable[..., Any]` instead of `object`
  — **−74** (`scripts/typed_handler_fields.py`)
- optional imports declared `Any` before the `try`, so the `None` fallback stops
  poisoning every later attribute — **−27**
- `CDPTabConnectionMixin` interface declared under `TYPE_CHECKING` — **−26**

## The rule for anyone continuing this

1. Find the **systemic cause**. One `object` annotation was 74 findings; one
   optional-import fallback was 27. Chasing individual lines is how a week
   disappears for no gain.
2. Never buy the number with `# type: ignore` or a looser preset. The count is
   only useful while it means something.
3. When a finding is the checker's fault, say so **in the code**, keep the
   accurate annotation anyway, and leave the number alone. `resolve_home_path`
   and `parse_json_body` both carry the correct union signature today even
   though pyrefly cannot yet use it — the annotation describes the function,
   and the debt stays honest.
4. Re-check this page when pyrefly updates. Correct union narrowing would erase
   ~90 findings with no code change at all.
