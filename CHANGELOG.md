# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-09-24

### Fixed

- Source files were never outlined through the proxy. The fold is computed on the source
  under a `cat -n` style line-number gutter, which is how most coding agents hand a file
  over, but canonicalisation strips trailing whitespace from every line first, so the
  gutter on a blank source line arrived as a bare number with its separator gone. Those
  lines stopped matching, the match rate fell below the threshold on any file with blank
  lines in it, and every guttered file fell through to the summariser instead. The unit
  tests missed it because they built their own gutters and never stripped them; an end to
  end run against the published wheel is what caught it.
- The dashboard no longer depends on the machine answering a liveness probe. A network
  stack that raises rather than refusing left the page blank instead of merely saying the
  proxy was not running.

## [0.1.0] - 2026-09-24

First public release.

### Added

- A library surface: `from tokunseba import compress, shrink, expand`. `compress` takes a
  whole request body in any of the four wire shapes and hands back the same shape with an
  account of what changed; `shrink` does one piece of text; `expand` returns an original.
  It runs the pipeline the proxy runs, against the same ledger and handle store, so a
  handle minted from Python expands from the command line and there is no second
  implementation to drift.

- `tokunseba dashboard` serves the same view as `tokunseba ui` as one page off `127.0.0.1`
  and opens it. The terminal dashboard is unchanged and still the default: nothing opens a
  browser unless you run the command whose name says so. The page has no external reference
  in it, refuses any `Host` but this machine's, and the proxy serves the same page at
  `/_tokunseba/` when it is already running.
- Source files are now outlined rather than truncated. A file the assistant asked to read
  comes through with its imports, class declarations, signatures, decorators, docstrings and
  constants intact and each long function body replaced by one line saying how many lines
  went and which handle holds the file. Line-number gutters are preserved, so the gap names
  exactly which lines to ask for. Python is parsed with the standard library; JavaScript,
  TypeScript, Go, Rust, Java, Kotlin, Swift, Scala, C, C++, C#, Objective-C and PHP are
  scanned with a reader that tracks strings and comments and folds nothing when it is not
  certain.

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
  With nothing overridden the two rows usually still differ, which reads as "my
  configuration got worse" and is not what happened: a turn whose earlier identical copy
  falls outside the window has nothing to refer back to, so it is summarised instead of
  deduplicated. The output names that rather than leaving it to be inferred.
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

### Changed

- `budget.daily_usd` becomes `budget.daily_tokens`: a ceiling on tokens read and written
  in a day, counted from the ledger and including cache reads.

- The "configured but nothing has come through" message now names the Dock case, which
  is the commonest reason for a correct install that records nothing.
- `tokunseba stop` says that routed tools will fail to connect while the proxy is down
  rather than falling back to the provider, and asks before stopping. `-y` skips it.
- `tokunseba off` and `tokunseba uninstall` also clear the login-session variables.

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

### Fixed

- `retention show` crashed with a `TypeError` on any non-empty ledger: the oldest day
  arrived as a unix timestamp and went straight to rich's markup escaper. It now reads
  as a date and says how long ago that was. The unit tests only ever ran it on an empty
  ledger, which is why it shipped.
- `verify` footnoted an advisory failure with the check's name, so six cache drift
  signals were reported as `(no cache drift)`. It now prints what actually happened.
- `apps` blamed the operating system when `TOKUNSEBA_NO_SESSION_ENV` was what stopped
  it, telling macOS users macOS could not do this.


- Python 3.14 is supported. `requires-python` said `<3.14`, so on a machine whose `python3`
  is 3.14 -- which is now common -- `pip install tokunseba` refused before it started.
  Every dependency publishes 3.14 wheels and the suite passes on it, so the ceiling was
  only ever conservative. CI runs 3.12, 3.13 and 3.14.
- Two judge tests read whether the laya extra happened to be installed on the machine
  running them. They passed for whoever had run `uv sync --all-extras` and failed for
  everyone else, CI included. They pin it now, like the tests either side of them do.

- On a machine with no user service manager, `tokunseba start` wrote a systemd unit that
  could never run and then reported `Started via ... (start failed: [WinError 2] ...)`.
  It now says there is nothing to keep the proxy alive here, points at
  `tokunseba start --foreground`, and exits non-zero. `stop`, `uninstall` and the `init`
  disclosure say the same thing rather than naming a file that does nothing.

[0.1.1]: https://github.com/keshavgarg24/tokunseba/releases/tag/v0.1.1
[0.1.0]: https://github.com/keshavgarg24/tokunseba/releases/tag/v0.1.0
