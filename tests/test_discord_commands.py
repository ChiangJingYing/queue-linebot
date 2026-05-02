from services.discord_commands import DiscordCommandService


class TestDiscordCommandService:
    def test_menu_returns_user_action_buttons(self, db_manager):
        service = DiscordCommandService(db=db_manager)

        result = service.handle_interaction(user_id="discord_user_1", input_value="/menu")

        assert result["status"] == "success"
        assert result["message"] == "請使用下方功能選單。"
        first_row = result["components"][0]["components"]
        second_row = result["components"][1]["components"]
        assert [item["label"] for item in first_row] == ["舉手", "放棄", "看狀態"]
        assert [item["label"] for item in second_row] == ["看紀錄", "設定資料", "幫助"]

    def test_join_requires_registration_and_returns_register_button(self, db_manager):
        service = DiscordCommandService(db=db_manager)

        result = service.handle_interaction(user_id="discord_user_1", input_value="/join")

        assert result["status"] == "error"
        assert "請先完成註冊" in result["message"]
        button = result["components"][0]["components"][0]
        assert button["label"] == "設定基本資料"
        assert button["custom_id"] == "register:start"

    def test_register_starts_with_modal_trigger(self, db_manager):
        service = DiscordCommandService(db=db_manager)

        result = service.handle_interaction(user_id="discord_user_1", input_value="/register")

        assert result["status"] == "modal"
        assert result["modal"]["custom_id"] == "register:submit"
        assert result["modal"]["title"] == "設定基本資料"
        assert result["modal"]["components"][0]["components"][0]["custom_id"] == "student_id"

    def test_register_modal_submit_enters_multistep_location_flow(self, db_manager):
        service = DiscordCommandService(db=db_manager, location_options={"A": ["1", "2"], "B": ["1"]})

        step1 = service.handle_interaction(user_id="discord_user_1", input_value="register:submit:B12345678")
        assert step1["status"] == "pending"
        assert "請選擇您在第幾排座位" in step1["message"]
        assert [item["label"] for item in step1["components"][0]["components"]] == ["A", "B"]

        step2 = service.handle_interaction(user_id="discord_user_1", input_value="register:group:A")
        assert step2["status"] == "pending"
        assert "請選擇您的座位（A-?）" in step2["message"]
        assert [item["label"] for item in step2["components"][0]["components"]] == ["1", "2"]

        step3 = service.handle_interaction(user_id="discord_user_1", input_value="register:item:1")
        assert step3["status"] == "success"
        assert step3["message"] == "✅ 已更新學號：B12345678\n位置：A-1"
        profile = db_manager.get_user_profile("discord_user_1")
        assert profile is not None
        assert profile.display_name == "B12345678"
        assert profile.location == "A-1"

    def test_register_flow_uses_multistep_buttons_and_completes(self, db_manager):
        service = DiscordCommandService(db=db_manager, location_options={"A": ["1", "2"], "B": ["1"]})

        step1 = service.handle_interaction(user_id="discord_user_1", input_value="register:submit:B12345678")
        assert step1["status"] == "pending"
        assert "請選擇您在第幾排座位" in step1["message"]

        step2 = service.handle_interaction(user_id="discord_user_1", input_value="register:group:A")
        assert step2["status"] == "pending"
        assert "請選擇您的座位（A-?）" in step2["message"]
        assert [item["label"] for item in step2["components"][0]["components"]] == ["1", "2"]

        step3 = service.handle_interaction(user_id="discord_user_1", input_value="register:item:1")
        assert step3["status"] == "success"
        assert step3["message"] == "✅ 已更新學號：B12345678\n位置：A-1"
        profile = db_manager.get_user_profile("discord_user_1")
        assert profile is not None
        assert profile.display_name == "B12345678"
        assert profile.location == "A-1"

    def test_join_success_returns_followup_buttons(self, db_manager):
        db_manager.upsert_user_profile("discord_user_1", "B12345678", location="A-1", verified=True, role="user")
        service = DiscordCommandService(db=db_manager)

        result = service.handle_interaction(user_id="discord_user_1", input_value="menu:join")

        assert result["status"] == "success"
        assert "已加入隊列" in result["message"]
        labels = [item["label"] for row in result["components"] for item in row["components"]]
        assert labels == ["放棄", "看狀態", "看紀錄"]

    def test_status_returns_total_count_when_user_not_in_queue(self, db_manager):
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = DiscordCommandService(db=db_manager)
        service.handle_interaction(user_id="alice", input_value="/join")

        result = service.handle_interaction(user_id="bob", input_value="/status")

        assert result["status"] == "success"
        assert result["message"] == "📊 目前有 1 人在排隊中"
        labels = [item["label"] for row in result["components"] for item in row["components"]]
        assert labels == ["舉手", "設定資料"]

    def test_history_returns_empty_shared_message_when_no_history(self, db_manager):
        service = DiscordCommandService(db=db_manager)

        result = service.handle_interaction(user_id="alice", input_value="/history")

        assert result["status"] == "success"
        assert result["message"] == "查無排隊歷史紀錄。"

    def test_help_uses_shared_message_shape(self, db_manager):
        service = DiscordCommandService(db=db_manager)

        result = service.handle_interaction(user_id="alice", input_value="/help")

        assert result["status"] == "success"
        assert "/register - 依提示完成學號與座位註冊" in result["message"]
        assert "/menu - 顯示常用功能按鈕" in result["message"]
        assert "管理員指令" not in result["message"]

    def test_status_returns_position_and_buttons(self, db_manager):
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        db_manager.upsert_user_profile("bob", "B23456789", location="A-2", verified=True, role="user")
        service = DiscordCommandService(db=db_manager)
        service.handle_interaction(user_id="alice", input_value="/join")
        service.handle_interaction(user_id="bob", input_value="/join")

        result = service.handle_interaction(user_id="bob", input_value="/status")

        assert result["status"] == "success"
        assert "目前排在第 2 位" in result["message"]
        labels = [item["label"] for row in result["components"] for item in row["components"]]
        assert labels == ["舉手", "放棄", "看紀錄"]

    def test_cancel_when_queue_closed_requires_double_confirmation(self, db_manager):
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = DiscordCommandService(db=db_manager)
        service.handle_interaction(user_id="alice", input_value="/join")
        db_manager.set_config("queue_enabled", "false")

        first = service.handle_interaction(user_id="alice", input_value="/cancel")
        assert first["status"] == "pending"
        assert "當前隊列已關閉" in first["message"]
        labels1 = [item["label"] for item in first["components"][0]["components"]]
        assert labels1 == ["確認放棄", "取消放棄"]

        second = service.handle_interaction(user_id="alice", input_value="cancel:confirm")
        assert second["status"] == "pending"
        assert second["message"] == "您確定要放棄嗎？"

        final = service.handle_interaction(user_id="alice", input_value="cancel:confirm")
        assert final["status"] == "success"
        assert final["message"] == "✅ 已取消排隊"

    def test_cancel_abort_keeps_queue_entry(self, db_manager):
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = DiscordCommandService(db=db_manager)
        service.handle_interaction(user_id="alice", input_value="/join")
        db_manager.set_config("queue_enabled", "false")

        service.handle_interaction(user_id="alice", input_value="/cancel")
        result = service.handle_interaction(user_id="alice", input_value="cancel:abort")

        assert result["status"] == "success"
        assert result["message"] == "好的，已取消放棄"
        assert service.queue_manager.get_user_position("alice") == 1


    def test_cancel_abort_invalidates_stale_confirm_button(self, db_manager):
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = DiscordCommandService(db=db_manager)
        service.handle_interaction(user_id="alice", input_value="/join")
        db_manager.set_config("queue_enabled", "false")

        service.handle_interaction(user_id="alice", input_value="/cancel")
        abort_result = service.handle_interaction(user_id="alice", input_value="cancel:abort")
        stale_confirm = service.handle_interaction(user_id="alice", input_value="cancel:confirm")

        assert abort_result["status"] == "success"
        assert abort_result["message"] == "好的，已取消放棄"
        assert stale_confirm["status"] == "error"
        assert "確認流程已失效" in stale_confirm["message"]
        assert service.queue_manager.get_user_position("alice") == 1

    def test_history_returns_recent_user_events(self, db_manager):
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = DiscordCommandService(db=db_manager)
        service.handle_interaction(user_id="alice", input_value="/join")
        service.handle_interaction(user_id="alice", input_value="/cancel")

        result = service.handle_interaction(user_id="alice", input_value="/history")

        assert result["status"] == "success"
        assert "排隊歷史紀錄" in result["message"]
        assert "join" in result["message"]
        assert "cancel" in result["message"]
