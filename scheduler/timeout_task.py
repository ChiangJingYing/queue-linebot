"""Scheduler tasks for queue system."""

from __future__ import annotations

from datetime import datetime, timedelta


def check_timeouts(queue_manager, notifier) -> dict:
    """Check for timeout entries and auto-remove them.

    Returns summary information about any auto-removed entries.
    """
    timeout_minutes = queue_manager.db.get_queue_timeout_minutes()
    cutoff = datetime.now() - timedelta(minutes=timeout_minutes)

    timed_out = []
    for entry in queue_manager.get_queue():
        try:
            joined_at = datetime.fromisoformat(entry.join_time)
        except (TypeError, ValueError):
            continue

        if joined_at <= cutoff:
            result = queue_manager.cancel(entry.user_id)
            if result.get("status") == "cancelled":
                notifier.notify_user(
                    entry.user_id,
                    f"⌛ Your queue entry #{entry.queue_number} timed out and was removed automatically.",
                )
                timed_out.append(
                    {
                        "user_id": entry.user_id,
                        "queue_number": entry.queue_number,
                        "queue_type": entry.queue_type,
                    }
                )

    return {
        "status": "ok",
        "timeout_minutes": timeout_minutes,
        "removed_count": len(timed_out),
        "removed": timed_out,
    }


def register_timeout_job(scheduler, queue_manager, notifier) -> None:
    """Register timeout job to run every 60 seconds."""
    scheduler.add_job(
        check_timeouts,
        "interval",
        seconds=60,
        id="queue-timeout-check",
        replace_existing=True,
        args=[queue_manager, notifier],
    )


def check_reminders(queue_manager, notifier) -> dict:
    """Check for reminders and push notifications."""
    reminders_sent = []
    queue_entries = queue_manager.get_queue()

    for position, entry in enumerate(queue_entries, start=1):
        reminder_target = getattr(entry, "reminder_position", None)
        reminder_sent = getattr(entry, "reminder_sent", False)

        if reminder_target is None or reminder_sent:
            continue

        if position <= reminder_target:
            notifier.notify_user(
                entry.user_id,
                f"🔔 It's almost your turn. Your current position is {position}.",
            )
            setattr(entry, "reminder_sent", True)
            reminders_sent.append(
                {
                    "user_id": entry.user_id,
                    "position": position,
                    "reminder_target": reminder_target,
                }
            )

    return {
        "status": "ok",
        "sent_count": len(reminders_sent),
        "sent": reminders_sent,
    }
