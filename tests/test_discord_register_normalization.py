from services.discord_commands import DiscordCommandService


class TestDiscordRegisterNormalization:
    def test_register_pending_normalizes_group_token_before_shared_flow(self, db_manager):
        service = DiscordCommandService(db=db_manager, location_options={"A": ["1", "2"], "B": ["1"]})

        step1 = service.handle_interaction(user_id="discord_user_1", input_value="register:submit:B12345678")
        assert step1["status"] == "pending"

        step2 = service.handle_interaction(user_id="discord_user_1", input_value="register:group:A")
        assert step2["status"] == "pending"
        assert "請選擇您的座位（A-?）" in step2["message"]

    def test_register_pending_normalizes_item_token_before_shared_flow(self, db_manager):
        service = DiscordCommandService(db=db_manager, location_options={"A": ["1", "2"], "B": ["1"]})

        service.handle_interaction(user_id="discord_user_1", input_value="register:submit:B12345678")
        service.handle_interaction(user_id="discord_user_1", input_value="register:group:A")
        step3 = service.handle_interaction(user_id="discord_user_1", input_value="register:item:1")

        assert step3["status"] == "success"
        assert step3["message"] == "✅ 已更新學號：B12345678\n位置：A-1"
