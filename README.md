<img src="assets/logo-wordmark.svg" alt="tokunseba" width="232" height="64">

# tokunseba

A local proxy that cuts token usage for every AI coding tool on your machine, without changing what the model can know.

Install it once, run one command, and it sits between your tools and every model they talk to, cloud or local. It never sends anything anywhere except to the provider your tool was already using. There is no account, no telemetry, and nothing to pay for.

```bash
git clone <this repo> tokunseba && cd tokunseba
uv tool install ".[laya,mcp]"
tokunseba init
tokunseba doctor
```

Not on PyPI yet, so install from the checkout. Drop `laya` to skip the 808 MB local judge,
or `mcp` if every tool you use has a shell. The core needs neither.

Then use your tools exactly as before. When you want to see what changed:

```bash
tokunseba stats --since 7d
```

## The idea

In agentic coding, almost none of the tokens are your prompt. They are tool output, conversation history re-sent on every turn, and prompt caches that break without anyone noticing. tokunseba works on those three things, under one rule:

> Every transformation is either provably information-preserving, or reversible through a handle the model can expand on demand.

Nothing is thrown away. When output is too large to be worth its tokens, tokunseba replaces the bulk with a short line telling the model how to get the rest:

```
[tokunseba: 312 lines / ~4100 tokens omitted. Full output: run `tokunseba expand h_9cc6cd18e7d9`]
```

The model can run that command, or call the bundled MCP `expand` tool if it has no shell. The information is deferred, never lost.

## Tiers

| Tier | Default | What it does |
|---|---|---|
| 0 Observe | on | Records every request with its real and counterfactual cost. Detects broken caches, leaked credentials, wasted re-reads. Changes nothing. |
| 1 Lossless | on | Strips ANSI codes and progress-bar spam, collapses repeats, adds cache breakpoints clients forgot, replaces repeat file reads with references and re-reads with diffs, picks cheaper encodings only when the tokenizer agrees. |
| 2 Reach-preserving | on | Summarises test, build and install output down to what failed, with a handle to the full text. Keeps local-model prompts inside the context window so they are not silently truncated. |
| 3 Opt-in | off | Lowers effort and routes easy turns to cheaper or local models. Redacts credentials. Confidence-gated and measured against a control group. |

Tier 3 is the only tier that can change an answer. It is off until you turn it on, and when it is on, half your sessions run untouched so the ledger can tell you whether it actually helped.

## Why it does not break your prompt cache

A prompt cache matches on an exact byte prefix. Change one byte in a turn you already sent, and everything after it reverts to full price, which costs about ten times more than it saves.

So tokunseba only ever transforms content that is new in this request, and it stores every transformation keyed by the hash of its original. The same original always produces the same replacement, forever. Re-sent history stays byte-identical. History is never rewritten, which also keeps it compatible with models that bind reasoning to an unedited transcript.

It also watches the cache for you. When a client puts a timestamp or a fresh identifier inside its cached prefix, tokunseba records exactly which region drifted and why:

```
cache_drift    3    a cached prefix changed, so the next request paid full price
```

## The local judge

Some decisions need judgement rather than a rule: is this tool result still relevant, is this text trying to talk to the assistant, is this turn easy. tokunseba uses [Laya](https://github.com/NandhaKishorM/laya), an open-weights Apache 2.0 decision model that runs locally on CPU or Apple Silicon and returns calibrated probabilities in tens of milliseconds. No API key, no network, no fine-tuning, no cost.

One rule governs every use of it: **the judge may only make a decision whose wrong answer costs tokens, never correctness.** Below the confidence threshold it abstains, and abstaining always means doing the conservative thing. Laya's own documentation is candid that its base checkpoints score near chance on unfamiliar questions, which is exactly why the confidence gate, not the accuracy, is what makes it safe to use.

It is optional. Without it, tokunseba falls back to deterministic rules and keeps working.

**What measuring it actually showed.** Two findings from running the real model on an M-series
laptop on 2026-09-22, both of which shaped the design:

- It takes roughly 1.5 seconds per call. That is far too slow to sit in front of every request,
  so the judge runs *after* the response has been dispatched and its answers only feed the
  ledger. It can be moved into the request path with `judge.inline`, but only tier 3 gating
  needs that, and you pay the latency.
- Asked whether `def add(a, b): return a + b` is a prompt injection, it answers yes at 1.000
  confidence. It gets genuine injections and test output right, but a detector that calls
  ordinary source code an attack cannot be allowed to raise an alarm on its own. So regex is
  authoritative for injection detection and the model may only *corroborate* a regex hit.

Both findings are pinned by tests, so if a future checkpoint fixes them, the tests will say so.

## Supported tools

`tokunseba init` detects and configures what it finds, backing up every file it touches.

| Tool | How |
|---|---|
| Claude Code | `ANTHROPIC_BASE_URL` in settings, plus a status line and session hooks |
| Codex CLI | a `tokunseba` model provider in `config.toml` |
| Aider, Cline, Continue, OpenCode, Roo, any OpenAI or Anthropic SDK program | exported base URLs from a shell block |
| Ollama, LM Studio, llama.cpp, vLLM | `OLLAMA_HOST` or an OpenAI-compatible base URL |

Cursor, Copilot and Windsurf talk to their vendors' own backends over proprietary protocols. Covering them would need a root certificate and protocol reverse engineering, so they are out of scope.

`tokunseba off` reverses every change in one command. Files that did not exist before are removed, not left behind.

## Commands

```
tokunseba init                 configure every tool and start in the background
tokunseba doctor               check the install and anything silently costing tokens
tokunseba stats [--since 7d]   what was saved, by tool, with signals
tokunseba stats --ab           compare the tier 3 arms
tokunseba ui                   local dashboard
tokunseba explain <request-id> original beside replacement, block by block
tokunseba expand <handle>      the full original text behind a handle
tokunseba run -- pytest -q     run a command with its output already compressed
tokunseba on | off             re-apply or restore every tool config
tokunseba prune --days 30      delete old bodies, blobs and ledger rows
tokunseba uninstall            remove the service and restore everything
```

## Privacy and safety

- Binds `127.0.0.1` only.
- API keys are forwarded from your tool's own headers and never stored.
- No telemetry. The only outbound traffic is to the provider your tool chose.
- Credentials are scanned for before anything is written to disk, so a detected secret never
  reaches a stored blob or a stored request body.
- If tokunseba itself hits a bug, it forwards your request exactly as your tool sent it and
  records the failure. Optimising a request is never worth failing it.
- Bash command rewriting is deliberately not implemented. Claude Code's documented way to modify a tool's input also requires auto-approving it, which would bypass your own permission prompt. Use `tokunseba run` explicitly instead.

## What to expect

Savings depend entirely on what you do. Long agentic sessions with heavy tool use are where the wins are. Short chats save almost nothing. Rather than promise a number, tokunseba ships the measurement first: every request records what it cost and what it would have cost without the proxy, and `stats` shows you the difference.

For calibration, one realistic agentic turn measured end to end during development — a system
prompt, a pytest run and a recursive directory listing — went from 45,715 bytes on the wire to
12,461, a 72.7% reduction, with every test failure still present in what the model received and
the full output one `expand` away. Your numbers will differ.

Judge it on cost per finished task, not per request. A cheaper model that needs two more turns is not cheaper.

## Configuration

`~/.tokunseba/config.toml`. Everything is editable with `tokunseba config set`:

```bash
tokunseba config set tiers.tier3 true
tokunseba config set tier3.effort_routing true
tokunseba config set budget.daily_usd 5
tokunseba config set judge.gate_threshold 0.85
```

A note on concurrency: two requests from the same conversation in flight at once can leave
one of them with a stale view of what was already sent. The consequence is that a new block
is treated as history and skipped, which costs a little compression. It cannot corrupt a
request or change an answer, because transformations are content-addressed and history is
never rewritten.

Storage lives in `~/.tokunseba`: the SQLite ledger, blobs behind handles, backups of every file touched, and logs.

## Development

```bash
uv sync --group dev
uv run pytest -q
```

MIT licensed.
