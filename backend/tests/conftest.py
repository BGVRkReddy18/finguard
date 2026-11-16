import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User


@pytest.fixture
def make_event():
    def _make(score=0.2, flagged=False, risk="LOW", **overrides):
        event = {
            "txn_id": str(uuid.uuid4()),
            "customer_id": "C0001",
            "customer_name": "Asha Rao",
            "home_city": "Hyderabad",
            "amount": 1250.50,
            "currency": "INR",
            "merchant": "BigBasket",
            "merchant_category": "grocery",
            "city": "Hyderabad",
            "lat": 17.385,
            "lon": 78.4867,
            "channel": "POS",
            "timestamp": timezone.now().isoformat(),
            "label_is_fraud": flagged,
            "score": {
                "fraud_score": score,
                "risk_level": risk,
                "is_flagged": flagged,
                "reasons": ["Amount is 9.0x the customer's average"] if flagged else [],
                "features": {},
                "model_version": "rules-v1",
                "latency_ms": 1.2,
            },
        }
        event.update(overrides)
        return event

    return _make


@pytest.fixture
def analyst(db):
    return User.objects.create_user("ana", password="pw-12345678", role=User.Role.ANALYST)


@pytest.fixture
def other_analyst(db):
    return User.objects.create_user("bob", password="pw-12345678", role=User.Role.ANALYST)


@pytest.fixture
def manager(db):
    return User.objects.create_user("mgr", password="pw-12345678", role=User.Role.MANAGER)


@pytest.fixture
def client_for():
    def _client(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    return _client
