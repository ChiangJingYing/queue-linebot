from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.serve_flow import serve_user


class FakeAnnouncementService:
    def __init__(self, should_raise: bool = False):
        self.calls = []
        self.should_raise = should_raise

    def announce_called_guest(self, *, display_name: str):
        self.calls.append(display_name)
        if self.should_raise:
            raise RuntimeError('boom')
        return {"ok": True}


def test_serve_user_serves_next_and_announces_profile_display_name(tmp_path):
    db = DatabaseManager(str(tmp_path / 'serve-flow-next.db'))
    qm = QueueManager(db)
    announcement_service = FakeAnnouncementService()

    qm.register_name('alice', '110316888', location='A-1')
    qm.join('alice', 'regular')

    outcome = serve_user(queue_manager=qm, announcement_service=announcement_service)

    assert outcome['status'] == 'served'
    assert outcome['target_user_id'] == 'alice'
    assert outcome['display_name'] == '110316888（A-1）'
    assert outcome['announcement_display_name'] == '110316888'
    assert announcement_service.calls == ['110316888']


def test_serve_user_serves_specific_and_ignores_announcement_failures(tmp_path):
    db = DatabaseManager(str(tmp_path / 'serve-flow-specific.db'))
    qm = QueueManager(db)
    announcement_service = FakeAnnouncementService(should_raise=True)

    qm.register_name('alice', '110316888', location='A-1')
    qm.register_name('bob', '110316999', location='A-2')
    qm.join('alice', 'regular')
    qm.join('bob', 'regular')

    outcome = serve_user(queue_manager=qm, target_user_id='bob', announcement_service=announcement_service)

    assert outcome['status'] == 'served'
    assert outcome['target_user_id'] == 'bob'
    assert outcome['display_name'] == '110316999（A-2）'
    assert outcome['announcement_display_name'] == '110316999'
    assert announcement_service.calls == ['110316999']


def test_serve_user_includes_location_in_result(tmp_path):
    db = DatabaseManager(str(tmp_path / 'serve-flow-location.db'))
    qm = QueueManager(db)

    qm.register_name('alice', '110316888', location='A-1')
    qm.join('alice', 'regular')

    outcome = serve_user(queue_manager=qm)

    assert outcome['location'] == 'A-1'


def test_serve_user_auto_released_display_name_is_none_on_first_serve(tmp_path):
    db = DatabaseManager(str(tmp_path / 'serve-flow-first.db'))
    qm = QueueManager(db)

    qm.register_name('alice', '110316888', location='A-1')
    qm.join('alice', 'regular')

    outcome = serve_user(queue_manager=qm, admin_user_id='admin1')

    assert outcome['auto_released_display_name'] is None


def test_serve_user_includes_auto_released_display_name_when_admin_has_prior_session(tmp_path):
    db = DatabaseManager(str(tmp_path / 'serve-flow-auto-release.db'))
    qm = QueueManager(db)

    qm.register_name('alice', '110316888', location='A-1')
    qm.register_name('bob', '110316999', location='A-2')
    qm.join('alice', 'regular')
    qm.join('bob', 'regular')

    serve_user(queue_manager=qm, admin_user_id='admin1')
    outcome = serve_user(queue_manager=qm, admin_user_id='admin1')

    assert outcome['auto_released_display_name'] == '110316888（A-1）'
