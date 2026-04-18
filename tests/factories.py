"""Factory-boy factories for queue system tests."""

import factory
from factory.fuzzy import FuzzyText

from core.models import QueueEntry, VipPurchase


class QueueEntryFactory(factory.Factory):
    """Factory for creating QueueEntry instances."""

    class Meta:
        model = QueueEntry

    user_id = factory.Sequence(lambda n: f"user_{n}")
    queue_type = "regular"
    queue_number = 1
    join_time = factory.Faker("past_datetime")
    cancel_time = None
    served_time = None
    served = False


class VipPurchaseFactory(factory.Factory):
    """Factory for creating VipPurchase instances."""

    class Meta:
        model = VipPurchase

    user_id = factory.Sequence(lambda n: f"vip_user_{n}")
    platform = "line"
    coffee_id = FuzzyText(length=20)
    verified = True
    purchased_at = factory.Faker("past_datetime")
