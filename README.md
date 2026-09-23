<div align="center">

<img src="assets/logo-wordmark.svg" alt="tokunseba" width="232" height="64">

**A local proxy that cuts token usage for every AI coding tool on your machine, without changing what the model can know.**

[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-687%20passing-brightgreen)](#development)
[![Local only](https://img.shields.io/badge/network-localhost%20only-lightgrey)](#privacy-and-safety)

</div>

---

tokunseba sits between your coding tools and every model they talk to, cloud or local. It rewrites the parts of a request that cost tokens without carrying information, and it leaves everything else byte for byte alone.

There is no account, no telemetry, and nothing to pay for. The only outbound traffic is to the provider your tool was already using.

## Install

```bash
uv tool install "git+https://github.com/keshavgarg24/tokunseba"
tokunseba init
tokunseba doctor
```

`init` detects the AI tools installed on this machine, points them at the proxy, backs up every file it touches, and starts the proxy in the background. It prints each change before making it. `tokunseba off` reverses all of it in one command.

Open a new terminal afterwards, because the shell block only runs when a shell starts.

If you open your AI tool from the Dock, Spotlight or a desktop menu rather than by typing its name, it is not started by a shell and never reads your shell profile, so it will keep going straight to the provider and every report will read zero. One more command fixes that:

```bash
tokunseba apps on
```

It prints exactly what it will change, asks, and changes nothing if you say no. `tokunseba apps off` removes it. See [Applications you open from the Dock](#applications-you-open-from-the-dock).

With pip instead of uv:

```bash
pip install "git+https://github.com/keshavgarg24/tokunseba"
```

Optional extras:

```bash
uv tool install "git+https://github.com/keshavgarg24/tokunseba#egg=tokunseba[mcp]"
```

| Extra | Size | What it adds |
|---|---|---|
| `mcp` | small | An MCP server so an assistant with no shell can still expand a handle. |
| `laya` | 808 MB download, 2.2 GB RAM when loaded | A local judge model. Off by default and never loaded until you run `tokunseba judge enable`. See [The local judge](#the-local-judge). |

The core needs neither. Requires Python 3.12 or 3.13. Works on macOS, Linux and Windows.

## The rule

In agentic coding, almost none of the tokens are your prompt. They are tool output, conversation history re-sent every turn, and prompt caches that break without anyone noticing. tokunseba works on those three things under one rule:

> Every transformation is either provably information-preserving, or reversible through a handle the model can expand on demand.

Nothing is discarded. When output is too large to be worth its tokens, the bulk is replaced with a line telling the model how to get the rest:

```
[tokunseba: 312 lines / ~4100 tokens omitted. Full output: run `tokunseba expand h_9cc6cd18e7d9`]
```

The model can run that command, or call the bundled MCP `expand` tool if it has no shell. The information is deferred, never lost.

## Tiers

How much tokunseba is allowed to do is a decision you make one layer at a time. Run `tokunseba tier` to see the current state, and `tokunseba tier explain 2` for the full text of any one of them.

| Tier | Default | What it may change |
|---|---|---|
| 0 observe | always on | Nothing. Every byte is forwarded exactly as the client sent it. Counts tokens, records what the cache did, writes the ledger. |
| 1 reversible | on | Tool results only. Strips ANSI codes and progress-bar spam, replaces a repeated result with a pointer, replaces a re-read file with the diff since you last saw it, adds cache breakpoints clients forgot. |
| 2 reach-preserving | on | The shape of a long tool result. Summarises test, build and install output down to what failed, with a handle to the full text. Replaces lock files and binaries with a one-line description. |
| 3 opt-in | off | Which model answers, and the text of a request. Routes easy turns to cheaper or local models, redacts credentials, labels suspected prompt injection. |

Tier 3 is the only tier that can change an answer. It is off until you turn it on, and when it is on, sessions are randomly split between a control arm and a treatment arm so the ledger can tell you whether it actually helped.

## Prompt-driven routing

If you run a subscription coding tool, an API key for something like DeepSeek, and a local model through Ollama, the expensive part is not any one of them. It is that the cheapest capable model never gets the easy turns.

tokunseba reads the opening prompt of each conversation, labels its domain and difficulty, and sends the turn wherever you said turns like that should go.

```bash
tokunseba models add deepseek https://api.deepseek.com
tokunseba route add --max-difficulty 1 --to deepseek --model deepseek-chat
tokunseba route enable
```

Check what would happen to any prompt before turning anything on:

```
$ tokunseba route test "hey there"

 signal        answer     confidence
 domain        chitchat         0.90  above the gate
 difficulty    0 trivial        0.92  above the gate
 needs_tools   discarded        0.55  below 0.8

Matches: domain=chitchat and difficulty<=1 -> deepseek / deepseek-chat
```

Four things bound this:

- A rule only ever fires on the first turn of a conversation, never mid-thread.
- A signal below the confidence gate is discarded, so an unsure read changes nothing.
- A rule with no conditions never matches, so a typo cannot route everything.
- tokunseba rewrites request bodies, it does not translate between provider formats. A request arriving as Anthropic cannot be sent to an endpoint speaking OpenAI, and such a rule is refused and recorded rather than attempted. Same-protocol model swaps, including Claude Opus to Claude Haiku, work everywhere.

`tokunseba models` shows which of your endpoints each client protocol can reach.

This needs no model, no key and no download. The default judge answers from calibrated rules and costs nothing measurable.

## The local judge

Some decisions want judgement rather than a rule. [Laya](https://github.com/NandhaKishorM/laya) is an open-weights Apache 2.0 decision model that runs locally on CPU or Apple Silicon and returns calibrated probabilities. No API key, no network, no fine-tuning.

It is strictly opt in, because it is not free:

| | |
|---|---|
| One-time download | about 808 MB, kept under `~/.cache/huggingface` |
| Memory while loaded | about 2.2 GB of RAM, held for as long as the proxy runs |
| Where it runs | entirely on this machine, on CPU or Apple Silicon |
| Licence | Apache 2.0 |

```bash
tokunseba judge status     # what it costs here, and what it is used for
tokunseba judge enable     # states the cost, then asks
tokunseba judge disable    # gives the memory back on the next restart
tokunseba judge remove     # deletes the weights from disk
```

While the judge is disabled nothing imports torch, nothing is downloaded and nothing is held in memory. A test asserts this, because an optional dependency that loads anyway is not optional.

One rule governs every use of it: the judge may only make a decision whose wrong answer costs tokens, never correctness. Below the confidence threshold it abstains, and abstaining always means doing the conservative thing.

Two measurements from running the real model on an M-series laptop, both of which shaped the design:

- It takes roughly 1.5 seconds per call. That is too slow to sit in front of every request, so by default it runs after the response has been dispatched and only feeds the ledger. `judge.inline` moves it into the request path, at that cost.
- Asked whether `def add(a, b): return a + b` is a prompt injection, it answers yes at 1.000 confidence. It gets genuine injections right, but a detector that calls ordinary source code an attack cannot raise an alarm on its own. Regex is authoritative for injection detection and the model may only corroborate a regex hit.

Both are pinned by tests, so a future checkpoint that fixes them will say so.

## Applications you open from the Dock

A terminal reads your shell profile every time it opens, which is why `tokunseba init` is enough for anything you start by typing its name. An application launched from the Dock, Spotlight or a desktop menu is started by the operating system, not by a shell. It never reads that file, so it never learns the proxy exists.

Nothing fails when this happens, which is what makes it hard to spot. The tool works normally, goes straight to the provider, and tokunseba records nothing. Every number in every report reads zero, which looks exactly like there having been nothing to save.

`tokunseba apps` shows what such an application would actually connect to. `tokunseba apps on` fixes it by setting the four base URLs in your login session, and it prints the exact commands first:

```
This will change your login session, not just this project.

  launchctl setenv ANTHROPIC_BASE_URL http://127.0.0.1:7777/anthropic
  launchctl setenv OPENAI_BASE_URL http://127.0.0.1:7777/openai/v1
  launchctl setenv OPENAI_API_BASE http://127.0.0.1:7777/openai/v1
  launchctl setenv OLLAMA_HOST http://127.0.0.1:7777/ollama
  write ~/Library/LaunchAgents/dev.tokunseba.appenv.plist so the four survive a restart

Every application you open afterwards inherits these four variables, not only AI tools.
A program that reads none of them is unaffected. tokunseba apps off removes them.

Apply this? [y/N]:
```

| Platform | What it sets | When it takes effect |
|---|---|---|
| macOS | `launchctl setenv`, plus a launch agent so it survives a restart | applications opened after the command |
| Linux | `~/.config/environment.d/tokunseba.conf` | next login |
| Windows | not automated; prints the four `setx` lines to run | next login |

`tokunseba apps off` removes them, and only clears a variable that points at a tokunseba proxy, so a value you set yourself for another reason survives. `tokunseba off` and `tokunseba uninstall` do this for you. Set `TOKUNSEBA_NO_SESSION_ENV=1` if you want tokunseba never to read or write your login session at all.

## Supported tools

| Tool | How |
|---|---|
| Claude Code | `ANTHROPIC_BASE_URL` in settings, plus a status line and session hooks |
| Codex CLI | a `tokunseba` model provider in `config.toml` |
| Aider, Cline, Continue, OpenCode, Roo, any OpenAI or Anthropic SDK program | exported base URLs from a shell block |
| Ollama, LM Studio, llama.cpp, vLLM | `OLLAMA_HOST` or an OpenAI-compatible base URL |

`tokunseba wrappable` lists what is installed here. `tokunseba wrap claude` runs one tool through the proxy without changing any config at all.

Cursor, Copilot and Windsurf talk to their vendors' own backends over proprietary protocols. Covering them would need a root certificate and protocol reverse engineering, so they are out of scope.

## Commands

**Setup**

```
tokunseba init                 configure every tool and start in the background
tokunseba doctor               check the install and anything silently costing tokens
tokunseba verify               prove the proxy is in the path, with evidence
tokunseba on | off             re-apply or restore every tool config
tokunseba apps                 what an app launched from the Dock would connect to
tokunseba apps on | off        route those too, after saying what it changes
tokunseba start | stop | restart
tokunseba uninstall            remove the service and restore everything
```

**Seeing what happened**

```
tokunseba status               is it running, and what did it save today
tokunseba stats --since 7d     what was saved, by tool, with signals
tokunseba stats --ab           compare the tier 3 arms
tokunseba report --since 30d   the whole picture in one page, with graphs
tokunseba report --save out.txt        write the same page to a file
tokunseba top                  the biggest savings, and what could not be helped
tokunseba ui                   dashboard in this terminal
tokunseba watch                the same, live
tokunseba explain <request-id> original beside replacement, block by block
tokunseba expand <handle>      the full original text behind a handle
```

**Deciding what it may do**

```
tokunseba tier                 which tiers are on and what each may change
tokunseba tier explain 2       one tier in full
tokunseba tier enable 3        turn one on, after saying what it costs
tokunseba judge status         the local judge: cost, state, what it is for
tokunseba route                prompt-driven routing rules
tokunseba route test "..."     what would happen to this prompt
tokunseba models               endpoints you can reach, and models you used
tokunseba models add NAME URL  add DeepSeek, a second Ollama host, anything
tokunseba config show | set    the raw configuration file
```

**History**

```
tokunseba retention show       how long history is kept, and how much is stored
tokunseba retention keep 1y    24h, 30d, 6w, 6m, 1y, or forever
tokunseba retention auto off   stop the once-a-day automatic prune
tokunseba prune --days 30      delete everything older than that, now
```

**Other**

```
tokunseba run -- pytest -q     run a command with its output already compressed
tokunseba wrap claude          run one tool through the proxy, no config change
tokunseba mcp                  MCP server exposing the expand tool
tokunseba advise               what your prompts looked like, and what routing would save
```

## Reports

`tokunseba report` is one page covering the whole window: tokens saved per day and per hour, where the compressible mass is by tool-result size, transforms by kind, savings by tool and by model, the biggest untouched blocks, every signal with an explanation, what you asked about by domain and by difficulty, and context growth in the newest session.

Everything is counted in tokens, because tokens are true whether you pay per token or pay a flat subscription. Dollar figures are behind `--money` and off by default.

History is kept for 90 days unless you say otherwise:

```bash
tokunseba retention keep 1y
```

## Why it does not break your prompt cache

A prompt cache matches on an exact byte prefix. Change one byte in a turn you already sent and everything after it reverts to full price, which costs about ten times more than it saves.

tokunseba only ever transforms content that is new in this request, and it stores every transformation keyed by the hash of its original. The same original always produces the same replacement, forever. Re-sent history stays byte-identical, which also keeps it compatible with models that bind reasoning to an unedited transcript.

It also watches the cache for you. When a client puts a timestamp or a fresh identifier inside its cached prefix, tokunseba records exactly which region drifted and why:

```
cache_drift    3    a cached prefix changed, so the next request paid full price
```

## Privacy and safety

- Binds `127.0.0.1` only.
- API keys are forwarded from your tool's own headers and never stored.
- No telemetry, no account, no phoning home. The only outbound traffic is to the provider your tool chose.
- Credentials are scanned for before anything is written to disk, so a detected secret never reaches a stored blob or a stored request body.
- If tokunseba hits a bug it forwards your request exactly as your tool sent it and records the failure. Optimising a request is never worth failing it.
- Bash command rewriting is deliberately not implemented. The documented way to modify a tool's input also requires auto-approving it, which would bypass your own permission prompt. Use `tokunseba run` explicitly instead.
- Everything lives in `~/.tokunseba`: the SQLite ledger, blobs behind handles, backups of every file touched, and logs.

## What to expect

Savings depend entirely on what you do. Long agentic sessions with heavy tool use are where the wins are. Short chats save almost nothing.

Rather than promise a number, tokunseba ships the measurement first: every request records what it cost and what it would have cost without the proxy, and `stats` shows the difference.

For calibration, one realistic agentic turn measured end to end during development, made of a system prompt, a pytest run and a recursive directory listing, went from 45,715 bytes on the wire to 12,461. That is a 72.7% reduction, with every test failure still present in what the model received and the full output one `expand` away. Your numbers will differ.

Judge it on cost per finished task, not per request. A cheaper model that needs two more turns is not cheaper.

## Configuration

`~/.tokunseba/config.toml`. The commands above cover most of it; anything else is reachable directly:

```bash
tokunseba config set budget.daily_usd 5
tokunseba config set judge.gate_threshold 0.85
tokunseba config set thresholds.truncate_tokens 6000
```

A note on concurrency: two requests from the same conversation in flight at once can leave one of them with a stale view of what was already sent. The consequence is that a new block is treated as history and skipped, which costs a little compression. It cannot corrupt a request or change an answer, because transformations are content-addressed and history is never rewritten.

## Development

```bash
uv sync --group dev
uv run pytest -q
```

687 tests, no network access required, and no model weights downloaded by the default run.

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## Licence

MIT. See [LICENSE](LICENSE).
