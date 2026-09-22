from tokunseba.protocols.anthropic import AnthropicAdapter
from tokunseba.protocols.base import sha256_text
from tokunseba.transform import dedup

A = AnthropicAdapter()


def convo(pairs):
    """pairs: list of (path, content). Each becomes a tool_use + tool_result message pair."""
    msgs = []
    for i, (path, content) in enumerate(pairs):
        msgs.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{i}", "name": "Read", "input": {"file_path": path}}]})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": [{"type": "text", "text": content}]}]})
    return A.parse({"model": "claude-opus-5", "messages": msgs})


def test_find_reference_detects_identical():
    n = convo([("/a.py", "SAME"), ("/b.py", "SAME")])
    assert dedup.find_reference(n, 3, sha256_text("SAME")) == (1, sha256_text("SAME"))


def test_find_reference_none_when_unique():
    n = convo([("/a.py", "ONE"), ("/b.py", "TWO")])
    assert dedup.find_reference(n, 3, sha256_text("TWO")) is None


def test_find_reread_same_path_changed():
    n = convo([("/a.py", "v1"), ("/a.py", "v2")])
    block = [b for b in n.messages[3].blocks if b.kind == "tool_result"][0]
    got = dedup.find_reread(n, 3, block)
    assert got and got[0] == 1 and got[2] == "v1"


def test_find_reread_ignores_other_paths():
    n = convo([("/other.py", "v1"), ("/a.py", "v2")])
    block = [b for b in n.messages[3].blocks if b.kind == "tool_result"][0]
    assert dedup.find_reread(n, 3, block) is None


def test_path_of_reads_tool_input():
    n = convo([("/x.py", "c")])
    block = [b for b in n.messages[1].blocks if b.kind == "tool_result"][0]
    assert dedup.path_of(n, block) == "/x.py"


def test_reference_text_points_at_a_handle_not_a_position():
    """Message numbers shift when a harness compacts, which would change these bytes."""
    t = dedup.reference_text("h_abc123456789")
    assert "expand h_abc123456789" in t
    assert "message" not in t


def test_make_diff_used_when_small():
    earlier = "\n".join(f"line {i}" for i in range(200))
    current = earlier.replace("line 5", "line FIVE")
    d = dedup.make_diff(earlier, current, "/a.py", "h_x")
    assert d and "line FIVE" in d and "changed since it was last read" in d


def test_make_diff_rejected_when_large():
    earlier = "\n".join(f"a{i}" for i in range(50))
    current = "\n".join(f"b{i}" for i in range(50))
    assert dedup.make_diff(earlier, current, "/a.py", "h_x") is None
