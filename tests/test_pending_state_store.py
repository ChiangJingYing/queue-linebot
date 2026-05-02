from services.pending_state_store import ConfigPendingStateStore, MemoryPendingStateStore


class TestMemoryPendingStateStore:
    def test_round_trip_by_flow_key(self):
        store = MemoryPendingStateStore()

        assert store.get(user_id="alice", flow="register") == {}

        store.set(user_id="alice", flow="register", state={"type": "register_name"})
        store.set(user_id="alice", flow="cancel", state={"type": "cancel_when_closed", "step": 2})

        assert store.get(user_id="alice", flow="register") == {"type": "register_name"}
        assert store.get(user_id="alice", flow="cancel") == {"type": "cancel_when_closed", "step": 2}

    def test_clear_is_scoped_to_one_flow(self):
        store = MemoryPendingStateStore()
        store.set(user_id="alice", flow="register", state={"type": "register_name"})
        store.set(user_id="alice", flow="cancel", state={"type": "cancel_when_closed"})

        store.clear(user_id="alice", flow="register")

        assert store.get(user_id="alice", flow="register") == {}
        assert store.get(user_id="alice", flow="cancel") == {"type": "cancel_when_closed"}


class TestConfigPendingStateStore:
    def test_round_trip_by_platform_and_flow(self, db_manager):
        store = ConfigPendingStateStore(db_manager, namespace="telegram")

        assert store.get(user_id="alice", flow="register") == {}

        store.set(user_id="alice", flow="register", state={"type": "register_name"})
        store.set(user_id="alice", flow="cancel", state={"type": "cancel_when_closed", "step": 2})

        assert store.get(user_id="alice", flow="register") == {"type": "register_name"}
        assert store.get(user_id="alice", flow="cancel") == {"type": "cancel_when_closed", "step": 2}

    def test_clear_is_scoped_to_one_flow(self, db_manager):
        store = ConfigPendingStateStore(db_manager, namespace="discord")
        store.set(user_id="alice", flow="register", state={"type": "register_name"})
        store.set(user_id="alice", flow="cancel", state={"type": "cancel_when_closed"})

        store.clear(user_id="alice", flow="cancel")

        assert store.get(user_id="alice", flow="register") == {"type": "register_name"}
        assert store.get(user_id="alice", flow="cancel") == {}

    def test_invalid_json_reads_as_empty_state(self, db_manager):
        db_manager.set_config("telegram_pending_register:alice", "not-json")
        store = ConfigPendingStateStore(db_manager, namespace="telegram")

        assert store.get(user_id="alice", flow="register") == {}
