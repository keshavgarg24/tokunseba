import stat

from tokunseba.transform.handles import HandleStore


def test_put_get_roundtrip(home):
    s = HandleStore(home / "blobs")
    h = s.put("hello world")
    assert h.startswith("h_") and len(h) == 14
    assert s.get(h) == "hello world"


def test_unknown_handle(home):
    assert HandleStore(home / "blobs").get("h_nope") is None


def test_same_text_same_handle(home):
    s = HandleStore(home / "blobs")
    assert s.put("x" * 100) == s.put("x" * 100)


def test_blob_is_private(home):
    s = HandleStore(home / "blobs")
    h = s.put("secretish")
    sha = __import__("json").loads((home / "blobs" / "index.json").read_text())[h]
    assert stat.S_IMODE((home / "blobs" / sha).stat().st_mode) == 0o600


def test_footer_text():
    assert HandleStore.footer("h_abc", 120, 4000) == (
        "[tokunseba: 120 lines / ~4000 tokens omitted. Full output: run `tokunseba expand h_abc`]")


def test_blocked_footer_mentions_secret():
    assert "secret" in HandleStore.blocked_footer()


def test_prune_keeps_live(home):
    s = HandleStore(home / "blobs")
    keep, drop = s.put("keep me"), s.put("drop me")
    assert s.prune({keep}) == 1
    assert s.get(keep) == "keep me" and s.get(drop) is None
