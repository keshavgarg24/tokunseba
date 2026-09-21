from tokunseba.session import SessionIndex


def test_session_prefix_and_delta():
    idx = SessionIndex()
    m1 = idx.match(["a"])
    assert m1.is_new and m1.prefix_len == 0
    idx.commit(m1.session_id, "r1", ["a"], [], {}, 100, 10)
    m2 = idx.match(["a", "b", "c"])
    assert not m2.is_new and m2.session_id == m1.session_id and m2.prefix_len == 1
    idx.commit(m2.session_id, "r2", ["a", "b", "c"], [], {}, 300, 20)
    m3 = idx.match(["a", "b", "c"])
    assert m3.prefix_len == 3 and m3.previous_request_id == "r2"
    m4 = idx.match(["x"])
    assert m4.is_new and m4.session_id != m1.session_id


def test_retry_matches_longer_stored_chain():
    idx = SessionIndex()
    m = idx.match(["a", "b"])
    idx.commit(m.session_id, "r1", ["a", "b"])
    again = idx.match(["a"])
    assert not again.is_new and again.session_id == m.session_id and again.prefix_len == 1


def test_longest_prefix_wins():
    idx = SessionIndex()
    idx.commit("s_short", "r1", ["a"])
    idx.commit("s_long", "r2", ["a", "b"])
    m = idx.match(["a", "b", "c"])
    assert m.session_id == "s_long" and m.prefix_len == 2


def test_eviction_and_gaps():
    idx = SessionIndex(max_chains=2)
    for i in range(3):
        idx.commit(f"s{i}", f"r{i}", [f"h{i}"])
    assert "s0" not in idx.sessions and len(idx.sessions) == 2
    idx.commit("s1", "r9", ["h1", "h2"])
    assert idx.get("s1").turns == 2 and len(idx.get("s1").gaps) == 1


def test_empty_chain_is_new():
    idx = SessionIndex()
    assert idx.match([]).is_new
