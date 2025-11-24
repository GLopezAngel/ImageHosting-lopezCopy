import argparse

import pytest

import cli


class DummyResponse:
    def __init__(self, ok=True):
        self.ok = ok
        self.status_code = 200
        self.text = ""


def test_cmd_login_saves_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "KEY_PATH", tmp_path / "keyfile")
    monkeypatch.setattr(cli, "api_request", lambda *args, **kwargs: {"api_key": "secret", "uid": "u_1"})

    cli.cmd_login(argparse.Namespace())

    captured = capsys.readouterr()
    assert "saved API key" in captured.out
    assert cli.KEY_PATH.read_text().strip() == "secret"


def test_cmd_upload_happy_path(monkeypatch, tmp_path, capsys):
    img = tmp_path / "photo.png"
    img.write_bytes(b"binarydata")

    calls = []

    def fake_api_request(method, path, json_body=None, use_auth=True):
        calls.append((method, path, json_body, use_auth))
        if path == "/api/v1/upload/request":
            return {"iid": "img_1", "key": "k1", "presigned_url": "https://upload"}
        if path == "/api/v1/upload/complete":
            assert json_body["iid"] == "img_1"
            return {"status": "ok"}
        raise AssertionError("unexpected path")

    monkeypatch.setattr(cli, "api_request", fake_api_request)
    monkeypatch.setattr(cli, "load_api_key", lambda: "token")
    monkeypatch.setattr(cli.requests, "put", lambda *_, **__: DummyResponse())

    cli.cmd_upload(argparse.Namespace(path=str(img)))

    captured = capsys.readouterr()
    assert "[ok] upload complete!" in captured.out
    assert calls[0][1] == "/api/v1/upload/request"
    assert calls[1][1] == "/api/v1/upload/complete"

