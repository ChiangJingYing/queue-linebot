from bot.handler import LineBotHandler
from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.discord_commands import DiscordCommandService
from services.telegram_commands import TelegramCommandService
from services.vip_service import VipService
from tests.test_handler import make_event, reply_texts


def _make_line_handler(db: DatabaseManager) -> LineBotHandler:
    return LineBotHandler(
        queue_manager=QueueManager(db),
        vip_service=VipService(db),
        location_options={"A": ["1", "2"], "B": ["1"]},
    )


def _make_telegram_service(db: DatabaseManager) -> TelegramCommandService:
    return TelegramCommandService(db=db, location_options={"A": ["1", "2"], "B": ["1"]})


def _make_discord_service(db: DatabaseManager) -> DiscordCommandService:
    return DiscordCommandService(db=db, location_options={"A": ["1", "2"], "B": ["1"]})


def test_join_requires_registration_message_is_consistent_across_platforms(tmp_path):
    line_db = DatabaseManager(str(tmp_path / "line-join.db"))
    telegram_db = DatabaseManager(str(tmp_path / "telegram-join.db"))
    discord_db = DatabaseManager(str(tmp_path / "discord-join.db"))

    line = _make_line_handler(line_db)
    telegram = _make_telegram_service(telegram_db)
    discord = _make_discord_service(discord_db)

    line_result = line.handle_event(make_event("/join", user_id="alice"))
    telegram_result = telegram.handle_text(user_id="alice", text="/join")
    discord_result = discord.handle_interaction(user_id="alice", input_value="/join")

    expected = "❌ 錯誤：請先完成註冊（學號與座位）後再加入隊列。"
    assert reply_texts(line_result)[0] == expected
    assert telegram_result["message"] == expected
    assert discord_result["message"] == expected


def test_status_total_count_when_not_in_queue_is_consistent_across_platforms(tmp_path):
    line_db = DatabaseManager(str(tmp_path / "line-status.db"))
    telegram_db = DatabaseManager(str(tmp_path / "telegram-status.db"))
    discord_db = DatabaseManager(str(tmp_path / "discord-status.db"))

    for db in (line_db, telegram_db, discord_db):
        db.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        QueueManager(db).join("alice", "regular")

    line = _make_line_handler(line_db)
    telegram = _make_telegram_service(telegram_db)
    discord = _make_discord_service(discord_db)

    line_result = line.handle_event(make_event("/status", user_id="bob"))
    telegram_result = telegram.handle_text(user_id="bob", text="/status")
    discord_result = discord.handle_interaction(user_id="bob", input_value="/status")

    expected = "📊 目前有 1 人在排隊中"
    assert reply_texts(line_result)[0] == expected
    assert telegram_result["message"] == expected
    assert discord_result["message"] == expected


def test_empty_history_message_is_consistent_across_platforms(tmp_path):
    line_db = DatabaseManager(str(tmp_path / "line-history.db"))
    telegram_db = DatabaseManager(str(tmp_path / "telegram-history.db"))
    discord_db = DatabaseManager(str(tmp_path / "discord-history.db"))

    line = _make_line_handler(line_db)
    telegram = _make_telegram_service(telegram_db)
    discord = _make_discord_service(discord_db)

    line_result = line.handle_event(make_event("/history", user_id="alice"))
    telegram_result = telegram.handle_text(user_id="alice", text="/history")
    discord_result = discord.handle_interaction(user_id="alice", input_value="/history")

    expected = "查無排隊歷史紀錄。"
    assert reply_texts(line_result)[0] == expected
    assert telegram_result["message"] == expected
    assert discord_result["message"] == expected


def test_closed_queue_cancel_abort_message_is_consistent_across_platforms(tmp_path):
    line_db = DatabaseManager(str(tmp_path / "line-cancel.db"))
    telegram_db = DatabaseManager(str(tmp_path / "telegram-cancel.db"))
    discord_db = DatabaseManager(str(tmp_path / "discord-cancel.db"))

    for db in (line_db, telegram_db, discord_db):
        db.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        qm = QueueManager(db)
        qm.join("alice", "regular")
        qm.set_queue_enabled(False)

    line = _make_line_handler(line_db)
    telegram = _make_telegram_service(telegram_db)
    discord = _make_discord_service(discord_db)

    line.handle_event(make_event("/cancel", user_id="alice", reply_token="r1"))
    telegram.handle_text(user_id="alice", text="/cancel")
    discord.handle_interaction(user_id="alice", input_value="/cancel")

    line_abort = line.handle_event(make_event("取消放棄", user_id="alice", reply_token="r2"))
    telegram_abort = telegram.handle_text(user_id="alice", text="取消放棄")
    discord_abort = discord.handle_interaction(user_id="alice", input_value="cancel:abort")

    expected = "好的，已取消放棄"
    assert reply_texts(line_abort)[0] == expected
    assert telegram_abort["message"] == expected
    assert discord_abort["message"] == expected

    assert line.queue_manager.get_user_position("alice") == 1
    assert telegram.queue_manager.get_user_position("alice") == 1
    assert discord.queue_manager.get_user_position("alice") == 1
