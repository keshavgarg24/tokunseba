# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-22

First public release.

### Added

- Local HTTP proxy on `127.0.0.1` with one path prefix per upstream provider
  (`/anthropic`, `/openai`, `/gemini`, `/ollama`, `/custom/<name>`). Unknown paths
  under a prefix are forwarded untouched.
- Protocol adapters for the Anthropic Messages API, the OpenAI Chat Completions and
  Responses APIs, Gemini, and Ollama, including streaming passthrough.
- Tier 0 observation: a local SQLite ledger recording tokens, cost, and the
  counterfactual cost of every request, with per tool, per session, and per project
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
