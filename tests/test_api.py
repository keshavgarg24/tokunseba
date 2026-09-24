"""The library surface: `compress`, `shrink`, `expand`.

The property that matters most is that this is not a second implementation. Whatever the
library does to a request has to be what the proxy would have done to it, against the same
ledger and the same handle store -- otherwise a handle minted here would not expand from
the command line, and the two would drift apart the first time either changed.
"""
import json

import pytest

import tokunseba
from tokunseba import config
from tokunseba.transform.handles import HandleStore


def _module(bodies=6, lines=14):
    parts = ["import os", "from typing import Any", "", "TIMEOUT = 30.0", "",
             "class Client:", '    """A client."""', ""]
    for i in range(bodies):
        parts += ["    @property", f"    def method_{i}(self, arg: str) -> int:",
                  f'        """What method {i} does."""']
        parts += [f"        x_{j} = {j} * {i}" for j in range(lines)]
        parts += ["        return x_0", ""]
    return "\n".join(parts)


def _log(n=900):
    return "\n".join(f"2026-01-01 12:00:{i % 60:02d} INFO worker {i} handled request" 
                     for i in range(n))


# ------------------------------------------------------------------ importability
def test_the_package_exports_the_three_functions_and_nothing_starts():
    """Importing must not open a socket, read a network, or cost anything noticeable."""
    assert set(tokunseba.__all__) == {"Change", "Result", "__version__", "compress",
                                      "expand", "shrink"}
    assert callable(tokunseba.compress) and callable(tokunseba.shrink)
    assert callable(tokunseba.expand) and tokunseba.__version__


# ------------------------------------------------------------------------ shrink
def test_shrink_outlines_a_source_file_and_the_handle_brings_it_back(home):
    src = _module()
    out = tokunseba.shrink(src, path="client.py")
    assert len(out) < len(src)
    assert "class Client:" in out and "def method_5(self, arg: str) -> int:" in out
    handle = next(w.rstrip("]") for w in out.split() if w.startswith("h_"))
    assert tokunseba.expand(handle) == src, "the handle must hold the original to the byte"


def test_shrink_summarises_program_output_when_told_the_command(home):
    log = _log()
    assert len(tokunseba.shrink(log, command="tail -f app.log")) < len(log) / 2


def test_shrink_leaves_something_small_exactly_as_it_was(home):
    for text in ("", "one line", "a\nb\nc\n"):
        assert tokunseba.shrink(text, path="a.py") == text


def test_shrink_without_a_path_still_works_on_plain_output(home):
    assert len(tokunseba.shrink(_log())) < len(_log())


# ---------------------------------------------------------------------- compress
@pytest.mark.parametrize("protocol", ["anthropic", "openai"])
def test_compress_handles_a_request_in_either_wire_shape(home, protocol):
    src = _module()
    body = _anthropic(src) if protocol == "anthropic" else _openai(src)
    r = tokunseba.compress(body, protocol=protocol)
    assert r.saved > 0 and r.tokens_after < r.tokens_before
    assert 0 < r.ratio < 1 and bool(r) is True
    assert [c.kind for c in r.changes] == ["outline:python"]
    assert r.changes[0].saved == r.changes[0].tokens_before - r.changes[0].tokens_after


def _anthropic(text):
    return {"model": "claude-sonnet-5", "messages": [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t0", "name": "Read", "input": {"file_path": "c.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t0",
             "content": [{"type": "text", "text": text}]}]}]}


def _openai(text):
    return {"model": "gpt-5", "messages": [
        {"role": "assistant", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "read_file", "arguments": json.dumps({"path": "c.py"})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": text}]}


def test_compress_returns_the_body_in_the_shape_it_was_given(home):
    body = _openai(_module())
    out = tokunseba.compress(body, protocol="openai").body
    assert out["model"] == "gpt-5"
    assert out["messages"][1]["role"] == "tool" and isinstance(out["messages"][1]["content"], str)
    assert "class Client:" in out["messages"][1]["content"]


def test_compress_never_touches_a_prompt_somebody_typed(home):
    """Only tool results are rewritten. A question that contains code is still a question."""
    prose = _module()
    body = {"model": "claude-sonnet-5",
            "messages": [{"role": "user", "content": prose}]}
    r = tokunseba.compress(body, protocol="anthropic")
    assert r.body["messages"][0]["content"] == prose
    assert r.changes == [] and r.saved == 0 and bool(r) is False


def test_compress_leaves_a_request_with_nothing_to_do_untouched(home):
    body = _anthropic("short enough")
    before = json.dumps(body, sort_keys=True)
    r = tokunseba.compress(body, protocol="anthropic")
    assert json.dumps(r.body, sort_keys=True) == before and r.saved == 0


def test_an_unknown_protocol_is_refused_by_name(home):
    with pytest.raises(ValueError, match="unknown protocol"):
        tokunseba.compress({}, protocol="carrier-pigeon")


def test_ratio_is_zero_rather_than_a_division_error_on_an_empty_request(home):
    r = tokunseba.compress({"model": "m", "messages": []}, protocol="anthropic")
    assert r.ratio == 0.0 and r.saved == 0


# ------------------------------------------------------------------------ expand
def test_expand_returns_none_for_a_handle_that_was_never_minted(home):
    assert tokunseba.expand("h_nothinghere") is None


def test_expand_reads_the_same_store_the_command_line_reads(home):
    """A handle from a library call has to work in `tokunseba expand`, and the reverse."""
    src = _module()
    tokunseba.shrink(src, path="c.py")
    store = HandleStore(config.home() / "blobs")
    handle = store.put(src)
    assert tokunseba.expand(handle) == src


def test_a_different_home_keeps_a_different_store(home, tmp_path):
    """So a test, or a tool with its own data directory, cannot write into the real one."""
    other = tmp_path / "elsewhere"
    out = tokunseba.shrink(_module(), path="c.py", home=other)
    handle = next(w.rstrip("]") for w in out.split() if w.startswith("h_"))
    assert tokunseba.expand(handle, home=other) is not None
    assert tokunseba.expand(handle) is None
    assert (other / "blobs").exists() and (other / "ledger.sqlite").exists()


# ------------------------------------------------------- the same thing as the proxy
def test_the_library_and_the_pipeline_produce_the_same_bytes(home):
    """Not a second implementation: the library calls the pipeline the proxy calls."""
    from tokunseba.ledger import Ledger
    from tokunseba.protocols.anthropic import AnthropicAdapter
    from tokunseba.tokens.estimator import Estimator
    from tokunseba.transform.pipeline import Pipeline

    src = _module()
    through_library = tokunseba.compress(_anthropic(src), protocol="anthropic").body

    led = Ledger(home / "direct.sqlite")
    pipe = Pipeline(config.load(), led, HandleStore(home / "blobs"), Estimator(None))
    body = _anthropic(src)
    direct = pipe.apply(AnthropicAdapter().parse(body), body, 0, "s", "r").body
    led.close()

    a = through_library["messages"][1]["content"][0]["content"][0]["text"]
    b = direct["messages"][1]["content"][0]["content"][0]["text"]
    assert a == b


def test_a_library_call_is_recorded_where_the_reports_look(home):
    from tokunseba.ledger import Ledger
    tokunseba.shrink(_module(), path="c.py")
    led = Ledger(config.home() / "ledger.sqlite")
    try:
        assert led.summary_counts(0)["transforms"] >= 1
    finally:
        led.close()
