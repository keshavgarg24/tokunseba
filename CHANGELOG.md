# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `tokunseba apps` for applications launched from the Dock, Spotlight or a desktop
  menu. Such an application is started by the operating system rather than by a shell,
  so it never reads the shell profile `init` writes to and silently goes straight to
  the provider. `apps on` sets the four base URLs in the login session after printing
  the exact commands it will run; `apps off` removes them, clearing only variables that
  point at a tokunseba proxy. macOS uses `launchctl` plus a launch agent so the setting
  survives a restart, Linux uses `~/.config/environment.d`, and Windows prints the
  `setx` lines to run by hand.
- `TOKUNSEBA_NO_SESSION_ENV` makes tokunseba never read or write the login session.
- `stats` and `report` show the average provider round trip beside the token counts, and
  `stats --ab` compares latency per request across the two arms. A request that got
  smaller but slower is not an improvement, and nothing said so before.
- `advise` reports the share of context and of answers a routing rule would move, not
  only the number of conversations. Ten trivial one-liners are not the same prize as one
  easy conversation carrying 200k tokens of context.
- `init` prints every file it will change, what it needs (nothing but the machine), and
  how to undo it, then asks. `--dry-run` prints the plan and stops; `-y` skips the
  question for scripts and images. It used to start writing to the home directory
  immediately, which is a poor introduction for the first command anybody runs.

### Fixed

- `retention show` crashed with a `TypeError` on any non-empty ledger: the oldest day
  arrived as a unix timestamp and went straight to rich's markup escaper. It now reads
  as a date and says how long ago that was. The unit tests only ever ran it on an empty
  ledger, which is why it shipped.
- `verify` footnoted an advisory failure with the check's name, so six cache drift
  signals were reported as `(no cache drift)`. It now prints what actually happened.
- `apps` blamed the operating system when `TOKUNSEBA_NO_SESSION_ENV` was what stopped
  it, telling macOS users macOS could not do this.

### Removed

- Every currency figure, and the price table behind them. A per-token price is correct
  for exactly one kind of access and silently wrong for all the others, so `--money`,
  `pricing.py`, the `pricing` config section and the `cost_usd` and `counterfactual_usd`
  ledger columns are gone. Savings are reported in tokens, ratios and time, which mean
  the same thing to everybody. A test now fails if a currency figure comes back.
- The generated design and plan documents under `docs/`. They described the code as it
  was going to be written, not as it is, and shipped in the source distribution.

### Changed

- `budget.daily_usd` becomes `budget.daily_tokens`: a ceiling on tokens read and written
  in a day, counted from the ledger and including cache reads.

- The "configured but nothing has come through" message now names the Dock case, which
  is the commonest reason for a correct install that records nothing.
- `tokunseba stop` says that routed tools will fail to connect while the proxy is down
  rather than falling back to the provider, and asks before stopping. `-y` skips it.
- `tokunseba off` and `tokunseba uninstall` also clear the login-session variables.


## [0.1.0] - 2026-09-22

First public release.

### Added

- Local HTTP proxy on `127.0.0.1` with one path prefix per upstream provider
  (`/anthropic`, `/openai`, `/gemini`, `/ollama`, `/custom/<name>`). Unknown paths
  under a prefix are forwarded untouched.
- Protocol adapters for the Anthropic Messages API, the OpenAI Chat Completions and
  Responses APIs, Gemini, and Ollama, including streaming passthrough.
- Tier 0 observation: a local SQLite ledger recording tokens, cache behaviour and
  latency for every request, with per tool, per session, and per project
  breakdowns.
- Tier 1 lossless transforms: ANSI and progress-bar stripping, repeat collapsing,
  session dedup by reference, diff on re-read, and tokenizer-measured encoding choices.
- Tier 2 reach-preserving transforms: structural summaries of test, build, and log
  output, and head-and-tail truncation, each leaving a handle the model can expand.
- Tier 3, off by default: effort right-sizing, model routing, local versus cloud
  routing, and secret redaction, each confidence-gated and measured against a control
  arm in the ledger.
- Content-addressed frozen transforms, so the same original bytes always produce the
  same replacement and re-sent history stays byte-identical for prompt caching.
- Cache guardian that detects and reports prefix drift, and a cache injector that adds
  breakpoints when a client sends none.
- Handle expansion through the `tokunseba expand` command and through a bundled MCP
  server for agents without a shell.
- Optional local judge backed by [Laya](https://github.com/NandhaKishorM/laya), used
  only for decisions whose wrong answer costs tokens rather than correctness.
- Automatic configuration of Claude Code, Codex CLI, shell-exported base URLs for
  OpenAI and Anthropic SDK clients, and local runtimes such as Ollama, LM Studio,
  llama.cpp, and vLLM, with a backup of every file touched and a one-command restore.
- Secret scanning before anything is written to disk.
- CLI: `init`, `doctor`, `start`, `stop`, `status`, `statusline`, `stats`, `top`, `ui`,
  `watch`, `explain`, `expand`, `advise`, `verify`, `run`, `config`, `on`, `off`,
  `prune`, `hook`, `mcp`, `uninstall`.

[Unreleased]: https://github.com/keshavgarg24/tokunseba/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/keshavgarg24/tokunseba/releases/tag/v0.1.0
