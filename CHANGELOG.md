# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Cross-protocol routing. A rule may now send a turn to an upstream that speaks a
  different protocol from the client: `protocols/translate.py` rewrites the request on
  the way out and the reply on the way back, for Anthropic to OpenAI and Anthropic to
  Ollama. System prompts, tool definitions, tool calls and their results, images, stop
  reasons, usage and error envelopes are mapped, and a streamed reply is re-framed event
  by event rather than buffered, so it still arrives a token at a time. Without this the
  routing tier could not do the thing it exists for, because a coding agent speaks one
  protocol to every model it talks to and `COMPATIBLE["anthropic"]` was `{"anthropic"}`.
  Two invariants hold it together: dropping a field is allowed and inventing one is not,
  and upstream tool-call identifiers travel through untouched in both directions because
  the client hands them straight back on the next turn. Usage is still read with the
  upstream's own adapter on the upstream's own bytes, so the ledger stays exact. Every
  translated turn records a `protocol_translated` signal. A pair with no translator is
  still refused and recorded rather than attempted.
- `tokunseba replay`: re-run recorded traffic under a configuration you have not committed
  to, and report what would have been different. It works from the request bodies already
  on disk, walks each conversation in the order it happened so the prefix every decision
  rests on is the real one, and sends nothing anywhere. Its ledger and blob store live in a
  temporary directory that is removed on the way out, so a replay cannot write a handle, an
  event, a frozen replacement or a learned token ratio into real history. `--tier`, `--set`
  and `--verbose` cover "what would tier 2 have caught", "what would this threshold do" and
  "which requests, so I can read one". Tier 3 is not replayed: it decides which model
  answers, and no offline pass can know what a different model would have said.
- `ledger.requests_in_order` and `config.apply_override`, which `replay` needs and
  `config set` now shares.
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

- Everything that was denominated in a currency, and the rate table behind it. One rate
  is right for exactly one kind of access and quietly wrong for every other, so the
  `--money` flag, `pricing.py`, the `pricing` config section and the `cost_usd` and
  `counterfactual_usd` ledger columns are all gone. Results are reported in tokens, ratios
  and time, which mean the same thing to everybody. A test fails if any of it returns.
- The vocabulary as well as the figures. A smaller model is described as smaller, a faster
  path as faster and a lighter encoding as lighter, because that is the actual property and
  it is true whatever your access looks like. The guard covers the package and the docs.
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
