"""Tests for tokunseba.guards.secrets.

Every credential literal below is synthetic and obviously fake.
"""

from __future__ import annotations

import pytest

from tokunseba.guards.secrets import Finding, MAX_SCAN_CHARS, has_secret, redact, scan

# --- synthetic, non-functional credential samples -------------------------

FAKE_AWS = "AKIAIOSFODNN7EXAMPLE"
FAKE_ANTHROPIC = "sk-ant-api03-" + "A" * 40
FAKE_OPENAI = "sk-" + "T" * 32
FAKE_GHP = "ghp_" + "B" * 36
FAKE_GH_PAT = "github_pat_" + "C" * 22
FAKE_GOOGLE = "AIza" + "D" * 35
FAKE_SLACK = "xoxb-123456789012-abcdefghij"
FAKE_PRIVATE_KEY_HEADER = "-----BEGIN RSA PRIVATE KEY-----"
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWtlIn0.0000000000AAAAAAAAAA"
FAKE_ENV_LINE = "export DATABASE_PASSWORD=hunter2hunter2"


def _only(text: str) -> Finding:
    findings = scan(text)
    assert len(findings) == 1, findings
    return findings[0]


# --- positive: one per pattern --------------------------------------------


@pytest.mark.parametrize(
    ("secret", "kind"),
    [
        (FAKE_AWS, "aws_access_key"),
        (FAKE_ANTHROPIC, "anthropic_key"),
        (FAKE_OPENAI, "openai_like_key"),
        (FAKE_GHP, "github_token"),
        (FAKE_GH_PAT, "github_token"),
        (FAKE_GOOGLE, "google_api_key"),
        (FAKE_SLACK, "slack_token"),
        (FAKE_PRIVATE_KEY_HEADER, "private_key"),
        (FAKE_JWT, "jwt"),
    ],
)
def test_detects_secret_kind_and_span(secret: str, kind: str) -> None:
    text = f"leading words {secret} trailing words"
    finding = _only(text)
    assert finding.kind == kind
    assert text[finding.start : finding.end] == secret


def test_detects_env_secret_line() -> None:
    text = FAKE_ENV_LINE
    finding = _only(text)
    assert finding.kind == "env_secret"
    assert text[finding.start : finding.end] == FAKE_ENV_LINE


# --- negatives -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "sk-short",
        "AKIAxyz",
        "PATH=/usr/bin:/bin",
        "HOME=/Users/x",
        "api_key=foo",
        "Remember to change your password before the trip.",
        "NODE_ENV=production",
    ],
)
def test_benign_text_has_no_findings(text: str) -> None:
    assert scan(text) == []
    assert has_secret(text) is False


def test_node_env_is_not_an_env_secret() -> None:
    # Explicit: the suffix list is KEY/SECRET/TOKEN/PASSWORD/PASSWD only.
    assert scan("NODE_ENV=production\nAPP_MODE=debugmode123") == []


# --- overlap / dedup -------------------------------------------------------


def test_anthropic_key_wins_over_openai_like_on_same_span() -> None:
    text = f"key: {FAKE_ANTHROPIC} end"
    findings = scan(text)
    assert len(findings) == 1
    assert findings[0].kind == "anthropic_key"
    assert text[findings[0].start : findings[0].end] == FAKE_ANTHROPIC


def test_overlapping_findings_prefer_earlier_start() -> None:
    # The env_secret line starts before the embedded AWS key, so only the
    # enclosing env_secret finding survives.
    text = f"AWS_SECRET_ACCESS_KEY={FAKE_AWS}"
    finding = _only(text)
    assert finding.kind == "env_secret"
    assert finding.start == 0
    assert finding.end == len(text)


# --- redaction -------------------------------------------------------------


def test_redact_replaces_secret_and_preserves_surroundings() -> None:
    text = f"before {FAKE_AWS} after"
    out = redact(text, scan(text))
    assert FAKE_AWS not in out
    assert "[REDACTED:aws_access_key]" in out
    assert out == "before [REDACTED:aws_access_key] after"


def test_redact_multiple_findings_across_lines() -> None:
    text = "\n".join(
        [
            "config start",
            f"aws = {FAKE_AWS}",
            "harmless line",
            f"gh = {FAKE_GHP}",
            f"goog = {FAKE_GOOGLE}",
            "config end",
        ]
    )
    findings = scan(text)
    assert len(findings) == 3
    out = redact(text, findings)
    for secret in (FAKE_AWS, FAKE_GHP, FAKE_GOOGLE):
        assert secret not in out
    for marker in (
        "[REDACTED:aws_access_key]",
        "[REDACTED:github_token]",
        "[REDACTED:google_api_key]",
    ):
        assert marker in out
    assert out.count("\n") == text.count("\n")
    assert len(out.splitlines()) == len(text.splitlines())
    assert out.splitlines()[0] == "config start"
    assert out.splitlines()[-1] == "config end"


def test_redact_with_no_findings_is_identity() -> None:
    text = "nothing sensitive here"
    assert redact(text, scan(text)) == text


# --- has_secret ------------------------------------------------------------


def test_has_secret_true_and_false() -> None:
    assert has_secret(f"token is {FAKE_SLACK}") is True
    assert has_secret("token is not present in this sentence") is False


# --- large input cap -------------------------------------------------------


def _filler(target_chars: int) -> str:
    line = "harmless text line\n"
    return line * (target_chars // len(line) + 1)


def test_secret_past_the_scan_cap_is_ignored() -> None:
    text = _filler(3_000_000) + FAKE_AWS
    assert len(text) > MAX_SCAN_CHARS
    assert scan(text) == []


def test_secret_before_the_scan_cap_is_found() -> None:
    text = f"{FAKE_AWS}\n" + _filler(3_000_000)
    assert len(text) > MAX_SCAN_CHARS
    findings = scan(text)
    assert len(findings) == 1
    assert findings[0].kind == "aws_access_key"
    assert text[findings[0].start : findings[0].end] == FAKE_AWS


def test_finding_is_frozen() -> None:
    finding = Finding(kind="jwt", start=0, end=3)
    with pytest.raises(Exception):
        finding.start = 5  # type: ignore[misc]
