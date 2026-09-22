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


def test_executable_falls_back_to_module(monkeypatch, tmp_path):
    monkeypatch.setattr(service.shutil, "which", lambda _n: None)
    monkeypatch.setattr(service.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(service.Path, "exists", lambda _self: False)
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


def _sandbox(service, monkeypatch, tmp_path):
    """install() writes a real file. Never let a test point it at the user's own agent."""
    monkeypatch.setattr(service, "plist_path", lambda: tmp_path / "agent.plist")
    monkeypatch.setattr(service, "unit_path", lambda: tmp_path / "unit.service")


def test_install_explains_a_port_already_in_use(home, tmp_path, monkeypatch):
    """A proxy the user started by hand is the usual cause, not a launchd fault."""
    from tokunseba import service
    _sandbox(service, monkeypatch, tmp_path)
    monkeypatch.setattr(service, "_run", lambda cmd: (1, "Bootstrap failed: 5: Input/output error"))
    monkeypatch.setattr(service, "running", lambda _p: True)
    _path, state = service.install(port=7777)
    assert "already listening on 7777" in state
    assert "Input/output error" not in state


def test_install_still_reports_a_genuine_failure(home, tmp_path, monkeypatch):
    from tokunseba import service
    _sandbox(service, monkeypatch, tmp_path)
    monkeypatch.setattr(service, "_run", lambda cmd: (1, "plist is malformed"))
    monkeypatch.setattr(service, "running", lambda _p: False)
    _path, state = service.install(port=7777)
    assert "plist is malformed" in state


def test_install_never_writes_outside_the_sandbox_in_tests(home, tmp_path, monkeypatch):
    """A regression guard for a real incident: a test wrote the user's own launch agent."""
    from tokunseba import service
    _sandbox(service, monkeypatch, tmp_path)
    monkeypatch.setattr(service, "_run", lambda cmd: (0, ""))
    path, _state = service.install(port=7777)
    assert tmp_path in path.parents


def test_install_refuses_a_transient_executable_path(home, tmp_path, monkeypatch):
    """`which` can resolve to a uv build temp dir that vanishes, leaving a dead service."""
    from tokunseba import service
    _sandbox(service, monkeypatch, tmp_path)
    monkeypatch.setattr(service.shutil, "which",
                        lambda _n: "/Users/x/.cache/uv/builds-v0/.tmpAB/bin/tokunseba")
    exe = service.executable()
    assert "builds-v0" not in exe and "/.tmp" not in exe
