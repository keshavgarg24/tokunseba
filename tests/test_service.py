import platform

from tokunseba import service


def test_unit_or_plist_mentions_entry_point(home, monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda _n: "/usr/local/bin/tokunseba")
    if platform.system() == "Darwin":
        xml = service._plist_xml()
        assert "/usr/local/bin/tokunseba" in xml
        assert "<key>KeepAlive</key><true/>" in xml
        assert "<string>start</string>" in xml and "<string>--foreground</string>" in xml
        assert str(home) in xml
    else:
        unit = service._unit_text()
        assert "ExecStart=/usr/local/bin/tokunseba start --foreground" in unit
        assert "Restart=always" in unit


def test_executable_falls_back_to_module(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda _n: None)
    assert "tokunseba.cli" in service.executable()


def test_running_is_false_on_a_dead_port():
    assert service.running(59999) is False


def test_paths_are_user_scoped():
    assert "LaunchAgents" in str(service.plist_path())
    assert "systemd/user" in str(service.unit_path())


def test_run_never_raises():
    code, out = service._run(["definitely-not-a-real-binary-xyz"])
    assert code == 1 and isinstance(out, str)


def test_logs_directory_is_created(home):
    assert service._logs().parent.exists()
