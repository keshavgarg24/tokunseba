# Contributing

Thanks for looking. tokunseba sits in the path of somebody's real work, so the bar for a change is less about style than about what it can break.

## Getting set up

```bash
git clone https://github.com/keshavgarg24/tokunseba
cd tokunseba
uv sync --group dev
uv run pytest -q
```

The suite needs no network and downloads no model weights. If a run of `pytest` pulls torch into memory, something has regressed and a test will say so.

To work against your own proxy without touching your real configuration:

```bash
TOKUNSEBA_HOME=/tmp/ts-dev uv run tokunseba start
```

## The rules that are not negotiable

These are the invariants the design rests on. A change that breaks one of them needs a very good argument, not a test update.

1. **A transformation is information-preserving or reversible.** Anything removed from a request must be retrievable through a handle, byte for byte, with `tokunseba expand`.
2. **History is never rewritten.** A prompt cache matches on an exact byte prefix. Only content that is new in the current request may be touched, and the same original must always produce the same replacement.
3. **A failure forwards the original.** If tokunseba hits a bug, the request goes upstream exactly as the client sent it and the failure is recorded. Optimising a request is never worth failing it.
4. **The judge may only make decisions whose wrong answer costs tokens.** Never correctness. Below the confidence gate it abstains, and abstaining means doing the conservative thing.
5. **Optional means not loaded.** While the local judge is disabled, nothing imports torch and nothing is downloaded. `tests/test_rules_router.py` asserts this.
6. **Nothing leaves the machine except the upstream request.** No telemetry, no analytics, no crash reporting.

## Tests

Every behaviour change needs a test that fails without it. Prefer testing what a user would notice over testing how it is implemented.

A few conventions that are easy to trip over:

- The A/B arm is drawn at random per session and only the treatment arm reaches tier 3, so pin it with `monkeypatch.setattr("random.choice", lambda seq: "treatment")` or the test passes half the time for the wrong reason.
- A module-level `pytest.importorskip` runs at collection time whatever markers the tests carry. Guard heavy imports with `pytest.skip(..., allow_module_level=True)` before the import, not after.
- Rich wraps output to the terminal width. Compare on collapsed whitespace rather than exact lines.

The laya smoke tests are opt in because they download 808 MB and load a 2.2 GB model:

```bash
TOKUNSEBA_LAYA_SMOKE=1 uv run pytest tests/test_laya_smoke.py
```

Do not run them in CI and do not run them on a machine with 8 GB of RAM while doing anything else.

## Style

Follow what is already there. Two things worth stating:

- Comments explain why, not what. A comment that restates the line above it is noise; a comment recording the measurement or the bug that forced a decision is the most valuable thing in the file.
- Terminal output is the whole interface. There is no web page and no docs site, so a new signal, event or command has to explain itself where it appears. A test asserts that every event the code emits has an explanation in `ui/terminal.py`.

## Adding a new event or signal

1. Emit it with `ledger.record_event(kind, payload, session_id, request_id)`.
2. Add it to `EVENT_HELP` and `EVENT_TONE` in `src/tokunseba/ui/terminal.py`.
3. The guard tests will fail until you do.

## Pull requests

Keep them focused on one thing. Include what you measured, not only what you changed: a savings claim without a before and after number is not reviewable.

Run the full suite before opening one.

```bash
uv run pytest -q
```

## Reporting a security issue

Open a private security advisory on GitHub rather than a public issue. tokunseba handles API keys in transit, so anything touching credential handling, the blob store or the ledger should go that route first.

## Licence

By contributing you agree that your contributions are licensed under the MIT licence, the same as the project.
