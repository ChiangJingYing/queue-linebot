from services.background_dispatcher import ThreadedDispatcher


def test_threaded_dispatcher_workers_are_daemon_threads():
    dispatcher = ThreadedDispatcher(max_workers=2)

    try:
        assert all(worker.daemon for worker in dispatcher._workers)
    finally:
        dispatcher.shutdown(wait=True)
