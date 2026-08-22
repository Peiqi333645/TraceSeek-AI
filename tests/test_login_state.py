import json

from xianyu_crawler.config import Settings
from xianyu_crawler.web import login_runner


def _use_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(login_runner, "Settings", lambda: Settings(data_dir=tmp_path))


def test_empty_storage_state_is_not_login(monkeypatch, tmp_path):
    _use_data_dir(monkeypatch, tmp_path)
    (tmp_path / "storage_state.json").write_text(
        json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    assert login_runner.has_session() is False
    assert login_runner.status()["authenticated"] is False


def test_account_cookie_counts_as_saved_session(monkeypatch, tmp_path):
    _use_data_dir(monkeypatch, tmp_path)
    (tmp_path / "storage_state.json").write_text(
        json.dumps({"cookies": [{"name": "tracknick", "value": "buyer"}]}),
        encoding="utf-8")
    assert login_runner.has_session() is True
    assert login_runner.status()["authenticated"] is True


def test_logout_removes_session_but_keeps_other_data(monkeypatch, tmp_path):
    _use_data_dir(monkeypatch, tmp_path)
    state = tmp_path / "storage_state.json"
    database = tmp_path / "xianyu.db"
    state.write_text(json.dumps({"cookies": [{"name": "tracknick", "value": "buyer"}]}))
    database.write_bytes(b"account data")

    result = login_runner.logout()

    assert result["authenticated"] is False
    assert not state.exists()
    assert database.read_bytes() == b"account data"
