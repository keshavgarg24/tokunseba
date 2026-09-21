"""Regex-based detection and redaction of credential-like strings.

Pure stdlib. Detection is heuristic and intentionally conservative about
overlapping matches: overlapping findings collapse to a single finding so a
credential is never reported (or redacted) twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

__all__ = ["Finding", "scan", "redact", "has_secret"]


@dataclass(frozen=True)
class Finding:
    """A single credential-like span located inside a scanned text."""

    kind: str
    start: int
    end: int


#: Inputs larger than this are truncated before scanning so that pathological
#: payloads cannot turn a guard check into an unbounded amount of regex work.
MAX_SCAN_CHARS: Final[int] = 2_000_000

#: Ordered on purpose: earlier patterns win ties during overlap resolution,
#: so the more specific ``anthropic_key`` precedes the generic ``openai_like_key``.
_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b", re.MULTILINE)),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}", re.MULTILINE)),
    ("openai_like_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}", re.MULTILINE)),
    (
        "github_token",
        re.compile(
            r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b"
            r"|\bgithub_pat_[A-Za-z0-9_]{22,}",
            re.MULTILINE,
        ),
    ),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b", re.MULTILINE)),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}", re.MULTILINE)),
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY(?: BLOCK)?-----",
            re.MULTILINE,
        ),
    ),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
            re.MULTILINE,
        ),
    ),
    (
        "env_secret",
        re.compile(
            r"^(?:export )?[A-Z][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD)=\S{8,}$",
            re.MULTILINE,
        ),
    ),
)


def scan(text: str) -> list[Finding]:
    """Return every credential-like span in ``text``, sorted by start offset.

    Overlapping findings are collapsed: the earlier-starting one wins, and on
    an equal start the longer one wins. When start and length are also equal
    the pattern declared first in :data:`_PATTERNS` wins, which is why an
    ``sk-ant-...`` string reports as ``anthropic_key`` rather than
    ``openai_like_key``.

    Only the first :data:`MAX_SCAN_CHARS` characters are examined.
    """
    haystack = text if len(text) <= MAX_SCAN_CHARS else text[:MAX_SCAN_CHARS]

    candidates: list[Finding] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(haystack):
            candidates.append(Finding(kind=kind, start=match.start(), end=match.end()))

    # Stable sort keeps pattern declaration order for identical spans.
    candidates.sort(key=lambda f: (f.start, -(f.end - f.start)))

    findings: list[Finding] = []
    covered_until = -1
    for finding in candidates:
        if finding.start < covered_until:
            continue
        findings.append(finding)
        covered_until = finding.end
    return findings


def redact(text: str, findings: list[Finding]) -> str:
    """Replace each finding's span in ``text`` with ``[REDACTED:{kind}]``.

    Spans are rewritten from the end of the string backwards so that offsets of
    not-yet-applied findings stay valid. ``findings`` must come from scanning
    this exact ``text``; other offsets yield undefined output.
    """
    out = text
    for finding in sorted(findings, key=lambda f: f.start, reverse=True):
        out = f"{out[: finding.start]}[REDACTED:{finding.kind}]{out[finding.end :]}"
    return out


def has_secret(text: str) -> bool:
    """Return whether ``text`` contains any credential-like span.

    Short-circuits on the first pattern that matches instead of building the
    full finding list.
    """
    haystack = text if len(text) <= MAX_SCAN_CHARS else text[:MAX_SCAN_CHARS]
    return any(pattern.search(haystack) is not None for _, pattern in _PATTERNS)
