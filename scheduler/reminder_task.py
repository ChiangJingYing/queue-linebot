"""Scheduler reminder task."""

from __future__ import annotations


def check_reminders(queue_manager, notifier) -> dict:
    """Check reminders and push notifications.

    Looks for queue entries that expose a ``reminder_position`` attribute and
    sends a notification once their live queue position reaches that threshold.
    """
    reminders_sent = []

    for position, entry in enumerate(queue_manager.get_queue(), start=1):
        reminder_target = getattr(entry, "reminder_position", None)
        reminder_sent = getattr(entry, "reminder_sent", False)

        if reminder_target is None or reminder_sent:
            continue

        if position <= reminder_target:
            notifier.notify_user(
                entry.user_id,
                f"🔔 Queue update: your current position is {position}.",
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
