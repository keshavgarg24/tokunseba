import json

import pytest

from tokunseba import config
from tokunseba.ledger import Ledger
from tokunseba.protocols.anthropic import AnthropicAdapter
from tokunseba.transform.handles import HandleStore
from tokunseba.transform.pipeline import Pipeline

A = AnthropicAdapter()


class Est:
    def count(self, text, provider, model):
        return max(len(text) // 4, 0)


@pytest.fixture
def pipe(home):
    cfg = config.load()
    led = Ledger(home / "l.sqlite")
    return Pipeline(cfg, led, HandleStore(home / "blobs"), Est()), cfg, led


def build(pairs, trailing_user=None):
    msgs = []
    for i, (name, path, content) in enumerate(pairs):
        msgs.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{i}", "name": name,
             "input": ({"file_path": path} if path else {"command": "run"})}]})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}",
             "content": [{"type": "text", "text": content}]}]})
    if trailing_user:
        msgs.append({"role": "user", "content": trailing_user})
    return {"model": "claude-opus-5", "messages": msgs}


def text_at(body, msg_index):
    return body["messages"][msg_index]["content"][0]["content"][0]["text"]


def test_ansi_is_stripped_losslessly(pipe):
    p, _cfg, _led = pipe
    body = build([("Bash", None, "\x1b[31mERROR\x1b[0m here")])
    res = p.apply(A.parse(body), body, 0, "s", "r")
    assert text_at(res.body, 1) == "ERROR here"
    assert res.applied[0].kind == "canonical"


def test_dedup_second_read_becomes_reference(pipe):
    p, _cfg, _led = pipe
    big = "\n".join(f"line {i}" for i in range(400))
    body = build([("Read", "/a.py", big), ("Read", "/b.py", big)])
    res = p.apply(A.parse(body), body, 0, "s", "r")
    assert "identical to an earlier tool result" in text_at(res.body, 3)
    assert res.tokens_after < res.tokens_before


def test_reread_becomes_a_diff(pipe):
    p, _cfg, _led = pipe
    v1 = "\n".join(f"line {i}" for i in range(400))
    v2 = v1.replace("line 7", "line SEVEN")
    body = build([("Read", "/a.py", v1), ("Read", "/a.py", v2)])
    res = p.apply(A.parse(body), body, 0, "s", "r")
    out = text_at(res.body, 3)
    assert "changed since it was last read" in out and "line SEVEN" in out
    assert len(out) < len(v2) / 2


def test_delta_only_leaves_history_untouched(pipe):
    p, _cfg, _led = pipe
    noisy = "\x1b[31mred\x1b[0m"
    body = build([("Bash", None, noisy), ("Bash", None, noisy)])
    res = p.apply(A.parse(body), body, delta_start=2, session_id="s", request_id="r")
    assert text_at(res.body, 1) == noisy       # already sent, never rewritten
    assert text_at(res.body, 3) == "red"       # new, cleaned


def test_tiny_duplicate_is_not_worth_a_pointer(pipe):
    p, _cfg, _led = pipe
    short = "ok"
    body = build([("Bash", None, short), ("Bash", None, short)])
    res = p.apply(A.parse(body), body, 0, "s", "r")
    assert text_at(res.body, 3) == "ok"


def test_materialize_rescues_a_dangling_reference(pipe):
    """A stored pointer is only valid while its target is still in the request."""
    p, _cfg, led = pipe
    from tokunseba.ledger import TransformRow
    row = TransformRow("k", "dedup_ref", "[tokunseba: identical to an earlier tool result (h_x)]",
                       100, 5, "h_x", "deadbeef")
    body = build([("Bash", None, "\x1b[31mred\x1b[0m")])
    norm = A.parse(body)
    assert p._materialize(norm, 1, row, "\x1b[31mred\x1b[0m") == "red"
    assert led.stats(0)["events"]["ref_dangling"] == 1


def test_frozen_table_replays_identical_bytes(pipe):
    p, _cfg, _led = pipe
    big = "\n".join(f"x{i}" for i in range(500))
    b1 = build([("Read", "/a.py", big)])
    r1 = p.apply(A.parse(b1), b1, 0, "s", "r1")
    first = text_at(r1.body, 1)
    b2 = build([("Read", "/a.py", big)], trailing_user="next")
    r2 = p.apply(A.parse(b2), b2, 2, "s", "r2")
    assert text_at(r2.body, 1) == first


def test_frozen_table_survives_a_restart(home):
    cfg = config.load()
    led = Ledger(home / "l.sqlite")
    big = "\n".join(f"x{i}" for i in range(500))
    b1 = build([("Read", "/a.py", big)])
    first = Pipeline(cfg, led, HandleStore(home / "blobs"), Est()).apply(
        A.parse(b1), b1, 0, "s", "r1")
    saved = text_at(first.body, 1)
    led2 = Ledger(home / "l.sqlite")
    b2 = build([("Read", "/a.py", big)])
    again = Pipeline(cfg, led2, HandleStore(home / "blobs"), Est()).apply(
        A.parse(b2), b2, 0, "s", "r2")
    assert text_at(again.body, 1) == saved


def test_truncation_keeps_head_and_tail_with_handle(pipe):
    p, cfg, _led = pipe
    cfg.thresholds.truncate_lines = 20
    cfg.thresholds.truncate_tokens = 50
    body = build([("Bash", None, "\n".join(f"u{i} = some prose value here" for i in range(500)))])
    res = p.apply(A.parse(body), body, 0, "s", "r")
    out = text_at(res.body, 1)
    assert out.startswith("u0 = some") and out.rstrip().endswith("u499 = some prose value here")
    assert "tokunseba expand h_" in out


def test_handle_expands_to_the_original(pipe, home):
    p, cfg, _led = pipe
    cfg.thresholds.truncate_lines = 20
    cfg.thresholds.truncate_tokens = 50
    original = "\n".join(f"u{i} = some prose value here" for i in range(500))
    body = build([("Bash", None, original)])
    res = p.apply(A.parse(body), body, 0, "s", "r")
    handle = res.applied[0].handle
    assert HandleStore(home / "blobs").get(handle) == original


def test_secret_never_reaches_a_blob(home):
    cfg = config.load()
    cfg.thresholds.truncate_lines = 10
    cfg.thresholds.truncate_tokens = 20
    led = Ledger(home / "l.sqlite")
    from tokunseba.guards import secrets
    p = Pipeline(cfg, led, HandleStore(home / "blobs"), Est(),
                 pre_store=lambda t: not secrets.has_secret(t))
    leaky = "\n".join(["AKIAIOSFODNN7EXAMPLE"] + [f"line {i}" for i in range(300)])
    body = build([("Bash", None, leaky)])
    res = p.apply(A.parse(body), body, 0, "s", "r")
    out = text_at(res.body, 1)
    assert "not stored because it contains a detected secret" in out
    blobs = [f for f in (home / "blobs").iterdir() if f.name != "index.json"]
    assert all("AKIA" not in f.read_text() for f in blobs)


def test_lossless_disabled_is_a_no_op(home):
    cfg = config.load()
    cfg.lossless = False
    led = Ledger(home / "l.sqlite")
    p = Pipeline(cfg, led, HandleStore(home / "blobs"), Est())
    body = build([("Bash", None, "\x1b[31mred\x1b[0m")])
    before = json.dumps(body)
    p.apply(A.parse(body), body, 0, "s", "r")
    assert json.dumps(body) == before


def test_reach_preserving_off_still_cleans(home):
    cfg = config.load()
    cfg.reach_preserving = False
    led = Ledger(home / "l.sqlite")
    p = Pipeline(cfg, led, HandleStore(home / "blobs"), Est())
    body = build([("Bash", None, "\x1b[31mred\x1b[0m\n" + "\n".join(f"z{i}" for i in range(900)))])
    res = p.apply(A.parse(body), body, 0, "s", "r")
    out = text_at(res.body, 1)
    assert "\x1b" not in out and "tokunseba expand" not in out


def test_accounting_is_recorded(pipe):
    p, _cfg, led = pipe
    body = build([("Bash", None, "\x1b[31mERROR\x1b[0m " + "x" * 400)])
    res = p.apply(A.parse(body), body, 0, "s", "req9")
    assert res.tokens_before > res.tokens_after and res.saved > 0
    rows = led.transforms_for("req9")
    assert rows and rows[0]["kind"] == "canonical"


def test_non_tool_result_blocks_are_never_touched(pipe):
    p, _cfg, _led = pipe
    body = {"model": "claude-opus-5", "messages": [
        {"role": "user", "content": "\x1b[31mkeep my ansi\x1b[0m"}]}
    before = json.dumps(body)
    p.apply(A.parse(body), body, 0, "s", "r")
    assert json.dumps(body) == before


def test_token_heavy_single_line_is_cut_not_duplicated(pipe):
    """Truncation triggered by the token budget must still shorten the text.

    A payload can blow the token budget while having far fewer lines than the
    line budget -- one enormous line of JSON or minified output is the usual
    case. Slicing a head and a tail out of it by line index returns the whole
    thing twice.
    """
    p, cfg, _led = pipe
    cfg.thresholds.truncate_lines = 300
    cfg.thresholds.truncate_tokens = 50
    original = "x" * 40000
    body = build([("Bash", None, original)])
    res = p.apply(A.parse(body), body, 0, "s", "r")
    out = text_at(res.body, 1)
    assert out.count(original) == 0, "the whole payload was re-emitted verbatim"
    assert len(out) < len(original)
    assert res.tokens_after < res.tokens_before
    assert "tokunseba expand h_" in out


def test_handle_holds_the_original_bytes_not_the_canonical_ones(pipe, home):
    """`expand` has to return what the tool actually produced.

    Canonicalization drops whatever a carriage return overwrote. That is a fair
    bet for a progress bar and a wrong one for CR-delimited data, so the bytes
    it drops must still be reachable through the handle.
    """
    p, cfg, _led = pipe
    cfg.thresholds.truncate_lines = 20
    cfg.thresholds.truncate_tokens = 50
    original = "COLUMN A\rCOLUMN B\rvisible\n" + "\n".join(f"u{i} = value" for i in range(500))
    body = build([("Bash", None, original)])
    res = p.apply(A.parse(body), body, 0, "s", "r")
    assert HandleStore(home / "blobs").get(res.applied[0].handle) == original


def test_reference_survives_history_compaction(pipe):
    """A harness that compacts history renumbers messages. The same bytes must still
    produce the same replacement, or the whole cached prefix is paid for again."""
    p, _cfg, _led = pipe
    big = "\n".join(f"line {i}" for i in range(400))
    before = build([("Read", "/a.py", big), ("Read", "/b.py", "filler " * 500),
                    ("Read", "/c.py", big)])
    r1 = p.apply(A.parse(before), before, 0, "s", "r1")
    original = text_at(r1.body, 5)
    assert "identical to an earlier tool result" in original

    # the middle exchange is compacted away and everything after it shifts down
    after = build([("Read", "/a.py", big), ("Read", "/c.py", big)])
    r2 = p.apply(A.parse(after), after, 0, "s", "r2")
    assert text_at(r2.body, 3) == original, "renumbering produced a different replacement"
