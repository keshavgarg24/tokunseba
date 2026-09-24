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
    produce the same replacement, or the whole cached prefix has to be read again."""
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


def test_parallel_tool_calls_in_one_message_are_deduped(pipe):
    """Claude Code returns every parallel tool result into a single user message.

    Scanning only previous messages missed the commonest duplicate there is: the same file
    read twice in one turn.
    """
    p, _cfg, _led = pipe
    same = "\n".join(f"{i}\tdef f{i}(): return {i}" for i in range(200))
    body = {"model": "claude-opus-5", "messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "a", "name": "Read", "input": {"file_path": "/m0.py"}},
            {"type": "tool_use", "id": "b", "name": "Read", "input": {"file_path": "/m1.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "a", "content": [{"type": "text", "text": same}]},
            {"type": "tool_result", "tool_use_id": "b", "content": [{"type": "text", "text": same}]}]}]}
    res = p.apply(A.parse(body), body, 0, "s", "r")
    first = body["messages"][1]["content"][0]["content"][0]["text"]
    second = body["messages"][1]["content"][1]["content"][0]["text"]
    assert "identical to an earlier tool result" in second
    assert "identical to an earlier tool result" not in first
    assert res.tokens_after < res.tokens_before


def test_a_reread_inside_one_message_becomes_a_diff(pipe):
    p, _cfg, _led = pipe
    v1 = "\n".join(f"line {i}" for i in range(300))
    v2 = v1.replace("line 9", "line NINE")
    body = {"model": "claude-opus-5", "messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "a", "name": "Read", "input": {"file_path": "/x.py"}},
            {"type": "tool_use", "id": "b", "name": "Read", "input": {"file_path": "/x.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "a", "content": [{"type": "text", "text": v1}]},
            {"type": "tool_result", "tool_use_id": "b", "content": [{"type": "text", "text": v2}]}]}]}
    p.apply(A.parse(body), body, 0, "s", "r")
    second = body["messages"][1]["content"][1]["content"][0]["text"]
    assert "changed since it was last read" in second and "line NINE" in second


def test_the_first_block_of_a_message_is_never_a_reference_to_itself(pipe):
    p, _cfg, _led = pipe
    text = "\n".join(f"row {i}" for i in range(300))
    body = {"model": "claude-opus-5", "messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "a", "name": "Read", "input": {"file_path": "/only.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "a", "content": [{"type": "text", "text": text}]}]}]}
    p.apply(A.parse(body), body, 0, "s", "r")
    assert "identical to an earlier" not in body["messages"][1]["content"][0]["content"][0]["text"]


# ------------------------------------------------------- outlining a source file
def _module(bodies=6, lines=14):
    parts = ["import os", "from typing import Any", "", "TIMEOUT = 30.0", "",
             "class Client:", '    """A client."""', ""]
    for i in range(bodies):
        parts += ["    @property", f"    def method_{i}(self, arg: str) -> int:",
                  f'        """What method {i} does."""']
        parts += [f"        x_{j} = {j} * {i}" for j in range(lines)]
        parts += ["        return x_0", ""]
    return "\n".join(parts)


def test_a_source_file_comes_back_as_an_outline(pipe):
    p, _cfg, led = pipe
    src = _module()
    body = build([("Read", "/repo/client.py", src)])
    out = p.apply(A.parse(body), body, 0, "s", "req1")
    assert [a.kind for a in out.applied] == ["outline:python"]
    shown = text_at(out.body, 1)
    assert "class Client:" in shown and "def method_5(self, arg: str) -> int:" in shown
    assert "x_9 = 9 * 5" not in shown
    assert out.saved > 0


def test_the_outlined_file_is_recoverable_to_the_byte(pipe, home):
    """The marker names a handle. That handle has to hold the file exactly as it arrived."""
    p, _cfg, _led = pipe
    src = _module()
    body = build([("Read", "/repo/client.py", src)])
    out = p.apply(A.parse(body), body, 0, "s", "req1")
    handle = out.applied[0].handle
    assert handle and handle in text_at(out.body, 1)
    assert HandleStore(home / "blobs").get(handle) == src


def test_a_source_file_small_enough_to_send_is_sent(pipe):
    p, _cfg, _led = pipe
    src = "import os\n\n\ndef f():\n    return 1\n"
    body = build([("Read", "/repo/tiny.py", src)])
    out = p.apply(A.parse(body), body, 0, "s", "req1")
    assert text_at(out.body, 1) == src


def test_a_log_file_is_still_summarised_rather_than_outlined(pipe):
    """The outline step must not swallow the cases the summariser already handled."""
    p, _cfg, _led = pipe
    log = "\n".join(f"2026-01-01 12:00:{i:02d} INFO worker {i} ok" for i in range(400))
    body = build([("Bash", None, log)])
    out = p.apply(A.parse(body), body, 0, "s", "req1")
    assert out.applied and not out.applied[0].kind.startswith("outline")


def test_the_users_own_prose_is_never_outlined(pipe):
    """Only tool results are rewritten. A question that happens to contain code is not one."""
    p, _cfg, _led = pipe
    body = {"model": "claude-opus-5", "messages": [{"role": "user", "content": _module()}]}
    out = p.apply(A.parse(body), body, 0, "s", "req1")
    assert out.body["messages"][0]["content"] == _module()
