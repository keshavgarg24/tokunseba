# Tokunseba Design Spec

Date: 2026-09-22
Status: implemented. Amended 2026-09-22 to match what was built and measured.

## 1. What it is

Tokunseba is a local CLI proxy. You install it once, run one command, and it sits between every AI coding tool on the machine and every model those tools talk to, cloud or local. Its job is to cut token usage without changing what the model can know or do.

Guiding sentence: every transformation is either provably information-preserving, or reversible through a handle the model can expand on demand. Anything that could change an answer lives behind an explicit opt-in tier.

## 2. Goals and non-goals

Goals

- One install, one `init`, one `start`. Supported tools are reconfigured automatically. Nothing else to learn.
- Default behaviour never changes the model, the effort level, or the meaning of the context.
- Savings are measured in a local ledger with a counterfactual cost, never promised.
- Works fully offline with local models, and uses Laya as an offline decision model with no fine-tuning. There is no hosted judge and no paid dependency of any kind.
- Instant bypass at any moment.

Non-goals for version 1

- Intercepting Cursor, Copilot, or Windsurf. They talk to closed backends over proprietary protocols and would need a root certificate plus reverse engineering.
- Any TLS man-in-the-middle mode.
- Fine-tuning Laya or any other model.
- Any hosted component, account, or telemetry.
- Any hosted decision model. An earlier draft of this spec paired Laya with TypeSafe's hosted
  Jev. That was dropped: the tool must run entirely locally and for free.

## 3. Principles

- P1 Delta-only. Only content that is new in this request is ever transformed.
- P2 Frozen transforms. A transformation is content-addressed by the SHA-256 of the original bytes and stored. The same original always produces the same transformed bytes forever, so re-sent history stays byte-identical and prompt caches survive.
- P3 Reach-preserving. Whatever is removed from context is stored locally under a handle, and the model is told in one line how to expand it.
- P4 Conservative judge. A decision model may only make a decision whose wrong answer costs tokens, never correctness. Low confidence means do the conservative thing.
- P5 Append-only history. The proxy never rewrites a turn that has already been sent, because caches are prefix-matched and newer Anthropic models bind thinking blocks to the unedited history.
- P6 Bypass always available. `tokunseba off` restores every tool config in one command.

## 4. Tiers

| Tier | Default | What it contains |
|---|---|---|
| 0 Observe | on | Ledger of tokens and cost per request, tool, session, project. Counterfactual cost. Cache-drift detection. Waste detectors. Dashboard, statusline, budgets as warnings. |
| 1 Lossless | on | Cache-control injection and TTL advice. Canonicalization of tool output. Session dedup by reference. Diff on re-read. Tokenizer-measured encodings. Junk-file guard. |
| 2 Reach-preserving | on | Structural summaries of test, build, and log output with handles. Head-and-tail truncation with handles for oversized output. Local-model context fitting. `expand` via shell command and MCP tool. |
| 3 Opt-in | off | Effort right-sizing. Model routing at session start. Local-versus-cloud routing. Secret redaction. Each is confidence-gated by the judge and A/B measured in the ledger. |

## 5. Architecture

Single Python process, single localhost port, default 7777. Each upstream provider is a path prefix so that a tool's base URL is unambiguous:

```
http://127.0.0.1:7777/anthropic/...   -> https://api.anthropic.com/...
http://127.0.0.1:7777/openai/...      -> https://api.openai.com/...
http://127.0.0.1:7777/gemini/...      -> https://generativelanguage.googleapis.com/...
http://127.0.0.1:7777/ollama/...      -> http://127.0.0.1:11434/...
http://127.0.0.1:7777/custom/<name>/... -> whatever config maps <name> to
```

Unknown paths under a prefix are forwarded untouched, so endpoints the proxy does not model still work.

Request lifecycle

1. Receive request, keep raw body bytes and all headers.
2. Adapter parses body into `NormalizedRequest` (provider, model, system blocks, messages, tools, stream flag, cache markers, raw dict).
3. Session matcher finds the previous request whose per-message hash chain is a prefix of this one. Delta = messages after the match. No match means a new session and the whole request is delta.
4. Guards run on the delta: secret scanner, injection screen. Default action is a ledger event, not a change.
5. Transform pipeline runs on tool-result blocks in the delta only, consulting the frozen table first. Blocks outside the delta are substituted from the table if present, else passed through untouched and recorded as passthrough.
6. Cache guardian compares the prefix up to each cache breakpoint with the previous request and records drift. Cache injector adds breakpoints when the request has none.
7. Tier 3 decisions, if enabled, run here with judge gating.
8. Forward upstream with the tool's own auth headers. Stream the response back unchanged.
9. Usage is captured from the response or the stream events. Ledger stores the request record, transforms applied, tokens before and after, cost, and counterfactual cost.

Components

```
cli            click commands
server         starlette app, one route per prefix, catch-all passthrough
protocols/     anthropic, openai (chat + responses), gemini, ollama adapters
session        prefix hashing, delta computation
cache/         guardian, injector, ttl advisor
transform/     table, handles, canonical, junk, dedup, encodings, summarize, pipeline
tokens/        estimator per provider
judge/         Judge protocol, laya, rules
guards/        secrets, injection
detect/        installed-tool detection and config writers
hooks/         Claude Code hook, run wrapper, mcp expand server
ledger         sqlite, pricing, stats
ui/            dashboard static page and JSON api
service        launchd and systemd units
```

## 6. Supported tools and how they are pointed at the proxy

| Tool | Mechanism written by `init` |
|---|---|
| Claude Code | `~/.claude/settings.json` `env.ANTHROPIC_BASE_URL = http://127.0.0.1:7777/anthropic` plus statusLine and hooks entries |
| Codex CLI | `~/.codex/config.toml` model provider with `base_url = http://127.0.0.1:7777/openai/v1` |
| Aider, Continue, Cline, OpenCode, Roo, any OpenAI or Anthropic SDK program | `~/.tokunseba/env.sh` exporting `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `OPENAI_API_BASE`, `OLLAMA_HOST`, sourced from the shell profile |
| Ollama clients | `OLLAMA_HOST=http://127.0.0.1:7777/ollama` |
| Gemini CLI | verified during Task 3; marked unsupported in `doctor` if no base-URL setting exists |

Every write keeps a `.tokunseba.bak` copy and `off` restores it.

## 7. Judge layer

Verified against laya 0.3.5 on an M-series laptop, 2026-09-22.

- PyPI package `laya` 0.3.5, Python 3.10 or newer, torch 2.14, transformers 5.x, Apache 2.0.
- Weights `convaiinnovations/laya`, about 808 MB, auto-selects CUDA, then Apple MPS, then CPU.
  Loaded on MPS here.
- `laya.load(model_id) -> Agent`, `Agent.predict(state, questions)` returning
  `{"answers": {qid: {type, choice|score|noul, probabilities, confidence}}}`. Confirmed by
  inspecting the installed package, not assumed.
- Presets confirmed present: `router_questions()` with `difficulty` (score, 4 levels), `domain`
  (choice, 6 labels), `needs_tools` and `is_sensitive` (noul); `guard_questions()` with
  `jailbreak`, `prompt_injection`, `sensitive_data`, `harm_severity`, `topic`.
- State budget is about 1,200 characters. Every state is trimmed before it is asked.

### Two measurements that changed the design

**Latency is roughly 1.5 seconds per call.** Far too slow to sit in front of every request.
So the judge runs *after* the response has been dispatched and its answers only reach the
ledger. `judge.inline` moves it back into the request path for tier 3 gating, at that cost.
A regression test asserts a deliberately slow judge cannot delay a request.

**Its zero-shot guard is not trustworthy.** Asked whether `def add(a, b): return a + b` is a
prompt injection, it answers yes at 1.000 confidence. It handles genuine injections and test
output correctly. So regex is authoritative for injection detection and the judge may only
*corroborate* a regex hit, never raise one. This is pinned by a smoke test that will fail if
a future checkpoint fixes the behaviour.

Both findings are what the Laya model card warns about in general terms: base checkpoints
score near chance on unfamiliar questions. The conservative-gate rule is what makes the model
safe to use anyway.

### Judge protocol

```
Judge.available() -> bool
Judge.ask(state, questions) -> dict[str, Answer]
Answer(type, value, confidence, probabilities)
gate(answer, threshold) -> True | False | None   # None means abstain
JudgeChain.decide(answers, key, want) -> True | False | None
```

Backends in order: `rules` (deterministic, always available) then `laya` (optional extra).
The first backend to answer a question wins; an abstention falls through; a failure or timeout
is recorded and skipped. With no backend at all, every caller takes the conservative path.

### What the judge is allowed to decide

| Question | Source | Used for | On doubt |
|---|---|---|---|
| `prompt_injection`, `jailbreak` | Laya guard preset | corroborating a regex hit, ledger only | record nothing |
| `sensitive_data` | regex, Laya as background signal | ledger warning; opt-in redaction | warn only |
| `difficulty`, `domain`, `needs_tools`, `is_sensitive` | Laya router preset | analytics; tier 3 gating when `judge.inline` | keep the default model and effort |
| `output_type` | regex first, judge as tie-breaker | choosing a summariser | generic canonicalisation |

In practice the router preset's confidence on short coding requests sits well below the 0.80
gate, so tier 3 gating abstains often. That is the intended failure mode: abstaining costs
tokens, never correctness.

## 8. Features beyond the core

- Secret and PII outbound guard. Regex set for cloud keys, private key blocks, JWTs, and high-entropy env values, plus the Laya `sensitive_data` signal. Default warns in ledger and statusline. Opt-in redaction is the only default-off transform that removes content, and redacted secrets are never written to blobs.
- Budgets. Daily and weekly USD or token budgets per project. Warn by default, hard stop opt-in.
- Dashboard. `tokunseba ui` serves a single local page: savings over time, per tool, per session, cache hit rate, top re-read files, top tool outputs, cache-drift events, guard events.
- Statusline. `tokunseba statusline` prints one line for Claude Code's statusLine setting: session tokens saved, percent, cache hit rate, budget state.
- `tokunseba run <cmd>`. Runs a shell command and prints the compressed output with a handle, for any agent with a shell. A Claude Code PreToolUse hook rewrites Bash commands through it.
- MCP `expand` tool for agents without a shell.
- `explain <request-id>`. Shows original versus transformed for every block in a request with token counts.
- Local-model context fitting. Reads the model's context length from the local server and applies handles so the request fits instead of being silently truncated from the front.
- Same-model failover, opt-in. On 429 or 5xx, retry the identical request on another configured endpoint serving the same model.
- Waste detectors. Repeated identical tool calls, files read many times per session, retries after stream disconnects, oversized system prompts and MCP tool schemas.

## 9. Storage

```
~/.tokunseba/
  config.toml
  ledger.sqlite         requests, transforms, events, sessions
  blobs/<sha256>        handle contents, mode 0600, directory 0700
  backups/              copies of tool configs before init
  logs/proxy.log
```

Retention: blobs and request bodies older than 30 days are pruned by `tokunseba prune`, configurable.

## 10. Security and privacy

- Binds 127.0.0.1 only. Refuses to start on any other address.
- Never stores API keys. Auth headers are forwarded as received.
- No telemetry. The only outbound traffic is to the upstream the tool already chose.
- Secret scanner runs before any content is written to blobs.
- Requests bodies are stored only when `store_bodies = true`, default true, because `explain` needs them. Documented and prunable.

## 11. Config schema

```toml
[proxy]
port = 7777
store_bodies = true
cache_ttl = ""
rewrite_bash = false

[tiers]
lossless = true
reach_preserving = true
tier3 = false

[tier3]
effort_routing = false
model_routing = false
local_routing = false
redact_secrets = false
annotate_injections = false
model_map = {}
local_model = ""

[judge]
backends = ["rules", "laya"]
laya_model = "convaiinnovations/laya"
laya_device = "auto"
gate_threshold = 0.80
timeout = 5.0
inline = false          # keep the judge out of the request path

[thresholds]
truncate_lines = 300
truncate_tokens = 6000
cache_min_tokens = 1024
local_truncate_tokens = 1500

[budget]
daily_usd = 0.0
hard_stop = false

[failover]
enabled = false

[upstreams.openrouter]
base_url = "https://openrouter.ai/api"
kind = "openai"
```

Every key above is read by code, and a test asserts the file round-trips.

## 12. CLI surface

```
tokunseba init            detect tools, write configs, install service
tokunseba start | stop | status
tokunseba on | off        restore or reapply tool configs
tokunseba doctor          port, tools, cache drift, judge availability
tokunseba stats [--since 7d] [--project PATH]
tokunseba explain <request-id>
tokunseba expand <handle>
tokunseba run -- <cmd>
tokunseba ui
tokunseba statusline
tokunseba mcp             stdio MCP server exposing expand
tokunseba prune
tokunseba config show | set KEY VALUE
```

## 13. Measurement

Per request: input_tokens, cache_read, cache_write, output_tokens, estimated tokens before transforms, tokens after, provider cost, counterfactual cost, transforms applied with per-transform savings, session id, tool id, project path.

Tier 3 features assign each new session to a control or treatment arm at random and report tokens per completed session and retry counts per arm.

Expected ranges from comparable tools, to be confirmed by the ledger: 20 to 40 percent fewer input tokens from Tier 1 and 2 on long agentic sessions, near zero on short chats.

## 14. Known limits

- No public Claude tokenizer. The estimator learns tokens-per-character per model from usage deltas between consecutive requests in a session.
- Laya's small state budget means it sees the new user message and a short excerpt, never the
  conversation. It is therefore a poor judge of anything that needs history.
- Compaction inside a harness rewrites history wholesale. The proxy treats it as a new session, and the frozen table keeps transforms consistent across it.
