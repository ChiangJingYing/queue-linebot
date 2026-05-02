from pathlib import Path

from scripts.register_discord_commands import build_discord_command_payloads, register_discord_commands


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body


def test_build_discord_command_payloads_contains_expected_user_commands():
    payloads = build_discord_command_payloads()

    names = [item["name"] for item in payloads]
    assert names == ["menu", "register", "join", "cancel", "status", "history", "help"]
    assert all(item["type"] == 1 for item in payloads)
    assert all(item["dm_permission"] is True for item in payloads)
    assert all(item["contexts"] == [1, 2] for item in payloads)

    join_payload = next(item for item in payloads if item["name"] == "join")
    assert "options" not in join_payload



def test_register_discord_commands_sends_bulk_overwrite_request(monkeypatch):
    captured = {}

    def fake_urlopen(request):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["authorization"] = request.get_header("Authorization")
        captured["content_type"] = request.get_header("Content-type")
        captured["body"] = request.data.decode("utf-8")
        return _FakeResponse(b'[{"id":"cmd_1","name":"menu"}]')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = register_discord_commands(application_id="app_123", bot_token="bot_456")

    assert captured["url"] == "https://discord.com/api/v10/applications/app_123/commands"
    assert captured["method"] == "PUT"
    assert captured["authorization"] == "Bot bot_456"
    assert captured["content_type"] == "application/json"
    assert [item["name"] for item in __import__("json").loads(captured["body"])] == [
        "menu",
        "register",
        "join",
        "cancel",
        "status",
        "history",
        "help",
    ]
    assert result == [{"id": "cmd_1", "name": "menu"}]



def test_readme_mentions_discord_command_registration_and_modal_flow():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "python scripts/register_discord_commands.py" in readme
    assert "Discord DM" in readme
    assert "modal" in readme
    assert "/api/discord/interactions" in readme
