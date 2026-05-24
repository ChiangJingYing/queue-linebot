"""Additional notifier tests."""

import json
from types import SimpleNamespace
from urllib import error as urllib_error

from services.notifier import Notifier


class TestNotifierAdditional:
    def test_notify_user_formats_push_message(self):
        notifier = Notifier("secret", "token")
        result = notifier.notify_user("alice", "hello")

        assert result == "已推送給 alice：hello"

    def test_notify_position_changed_uses_queue_updated_message_contract(self):
        notifier = Notifier("secret", "token")
        result = notifier.notify_queue_updated("alice", 2)

        assert "alice" in result
        assert "順位：2" in result

    def test_notify_served_contains_service_area_instruction(self):
        notifier = Notifier("secret", "token")
        result = notifier.notify_served("alice", 9)

        assert "請做好準備" in result
        assert "助教" in result
        assert "#9" in result

    def test_notify_served_can_skip_line_push_when_config_disabled(self):
        notifier = Notifier("secret", "token", line_push_on_served=False)
        result = notifier.notify_served("alice", 9)

        assert result.startswith("已略過 LINE 被叫號推播給 alice：")
        assert "請做好準備" in result
        assert "助教" in result
        assert "#9" in result

    def test_notify_join_success_contains_checkmark_and_number(self):
        notifier = Notifier("secret", "token")
        result = notifier.notify_join_success("alice", 4)

        assert "加入隊列" in result
        assert "#4" in result

    def test_notify_served_routes_to_discord_sender_for_marked_user(self, tmp_path):
        from core.database import DatabaseManager

        db = DatabaseManager(str(tmp_path / "discord-user.db"))
        db.set_config("discord_user:discord_user_1", "1")
        sent = []

        notifier = Notifier("secret", "token", discord_sender=lambda user_id, text: sent.append((user_id, text)), db=db)
        result = notifier.notify_served("discord_user_1", 7)

        assert result == "已推送給 discord_user_1：" + sent[0][1]
        assert sent == [("discord_user_1", sent[0][1])]
        assert "#7" in sent[0][1]

    def test_notify_user_returns_before_deferred_sender_runs(self, tmp_path):
        from core.database import DatabaseManager

        db = DatabaseManager(str(tmp_path / "deferred-telegram-user.db"))
        db.set_config("telegram_user:tg_user_1", "1")
        sent = []
        queued = []

        class DeferringDispatcher:
            def dispatch(self, func):
                queued.append(func)

        notifier = Notifier(
            telegram_sender=lambda user_id, text: sent.append((user_id, text)),
            db=db,
            dispatcher=DeferringDispatcher(),
        )

        result = notifier.notify_user("tg_user_1", "hello")

        assert result == "已推送給 tg_user_1：hello"
        assert sent == []
        assert len(queued) == 1

    def test_push_flex_returns_fallback_message_when_token_missing(self):
        notifier = Notifier("secret", "")

        result = notifier.push_flex(
            "alice",
            {
                "type": "flex",
                "altText": "審核通知",
                "contents": {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": []}},
            },
        )

        assert result == "已推送 Flex 給 alice：審核通知"

    def test_push_flex_posts_raw_line_payload(self, monkeypatch):
        captured = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = request.data.decode("utf-8")
            captured["timeout"] = timeout
            return _Response()

        monkeypatch.setattr("services.notifier.urllib_request.urlopen", fake_urlopen)
        notifier = Notifier("secret", "token")

        result = notifier.push_flex(
            "alice",
            {
                "type": "flex",
                "altText": "審核通知",
                "contents": {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": []}},
            },
        )

        assert result == "已推送 Flex 給 alice：審核通知"
        assert captured["url"] == "https://api.line.me/v2/bot/message/push"
        assert captured["timeout"] == 10
        assert json.loads(captured["body"]) == {
            "to": "alice",
            "messages": [
                {
                    "type": "flex",
                    "altText": "審核通知",
                    "contents": {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": []}},
                }
            ],
        }

    def test_push_flex_hides_http_error_body_from_return_value(self, monkeypatch):
        def fake_urlopen(request, timeout=0):
            error = urllib_error.HTTPError(
                request.full_url,
                400,
                "Bad Request",
                hdrs=None,
                fp=None,
            )
            error.read = lambda: b'{"message":"bad request","details":[{"secret":"x"}]}'
            raise error

        monkeypatch.setattr("services.notifier.urllib_request.urlopen", fake_urlopen)
        notifier = Notifier("secret", "token")

        result = notifier.push_flex(
            "alice",
            {
                "type": "flex",
                "altText": "審核通知",
                "contents": {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": []}},
            },
        )

        assert result == "推播 Flex 失敗給 alice：LINE API 暫時不可用"

    def test_get_user_rich_menu_normalizes_sdk_response_object(self):
        notifier = Notifier("secret", "token")

        result = notifier._normalize_rich_menu_id_response(SimpleNamespace(rich_menu_id="richmenu-123"))

        assert result == "richmenu-123"
