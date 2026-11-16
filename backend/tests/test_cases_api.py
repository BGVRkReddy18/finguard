import pytest
from rest_framework.test import APIClient

from cases.models import FraudCase
from transactions.services import ingest_scored_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def case(make_event):
    txn, _ = ingest_scored_event(make_event(score=0.9, flagged=True, risk="HIGH"))
    return txn.fraud_case


def test_requires_authentication():
    assert APIClient().get("/api/cases/").status_code == 401


def test_analyst_can_claim_and_resolve(case, analyst, client_for):
    client = client_for(analyst)
    resp = client.post(f"/api/cases/{case.id}/assign/", {}, format="json")
    assert resp.status_code == 200
    assert resp.data["status"] == "INVESTIGATING"

    resp = client.post(
        f"/api/cases/{case.id}/resolve/", {"status": "CONFIRMED_FRAUD", "note": "Customer confirmed"}, format="json"
    )
    assert resp.status_code == 200
    case.refresh_from_db()
    assert case.status == FraudCase.Status.CONFIRMED_FRAUD
    assert case.resolved_at is not None


def test_analyst_cannot_assign_to_someone_else(case, analyst, other_analyst, client_for):
    resp = client_for(analyst).post(f"/api/cases/{case.id}/assign/", {"user_id": other_analyst.id}, format="json")
    assert resp.status_code == 403


def test_analyst_cannot_resolve_unassigned_case(case, analyst, client_for):
    resp = client_for(analyst).post(f"/api/cases/{case.id}/resolve/", {"status": "FALSE_POSITIVE"}, format="json")
    assert resp.status_code == 403


def test_manager_can_assign_and_view_audit_log(case, manager, analyst, client_for):
    client = client_for(manager)
    resp = client.post(f"/api/cases/{case.id}/assign/", {"user_id": analyst.id}, format="json")
    assert resp.status_code == 200
    assert resp.data["assigned_to"]["username"] == "ana"

    actions = [e["action"] for e in client.get("/api/audit-logs/").data["results"]]
    assert "case.assigned" in actions and "case.opened" in actions


def test_analyst_cannot_view_audit_log(analyst, client_for):
    assert client_for(analyst).get("/api/audit-logs/").status_code == 403


def test_cannot_resolve_twice(case, manager, client_for):
    client = client_for(manager)
    client.post(f"/api/cases/{case.id}/resolve/", {"status": "FALSE_POSITIVE"}, format="json")
    resp = client.post(f"/api/cases/{case.id}/resolve/", {"status": "CONFIRMED_FRAUD"}, format="json")
    assert resp.status_code == 400


def test_stats_endpoint(make_event, analyst, client_for):
    ingest_scored_event(make_event())
    ingest_scored_event(make_event(score=0.9, flagged=True, risk="HIGH"))
    resp = client_for(analyst).get("/api/transactions/stats/")
    assert resp.status_code == 200
    assert resp.data["total"] == 2
    assert resp.data["flagged"] == 1
    assert resp.data["flag_rate"] == 0.5


REPORT = {
    "recommendation": "BLOCK", "confidence": 0.9, "summary": "Card used 1,200 km from home minutes after a home purchase.",
    "key_evidence": ["Impossible travel"], "next_steps": ["Block card"], "model": "test-llm",
}


def test_ai_report_requires_service_token(case, settings):
    settings.AI_SERVICE_TOKEN = "s3cret"
    client = APIClient()
    assert client.post(f"/api/cases/{case.id}/ai-report/", REPORT, format="json").status_code == 403
    resp = client.post(f"/api/cases/{case.id}/ai-report/", REPORT, format="json", HTTP_X_SERVICE_TOKEN="wrong")
    assert resp.status_code == 403


def test_ai_report_disabled_when_no_token_configured(case, settings):
    settings.AI_SERVICE_TOKEN = ""
    resp = APIClient().post(f"/api/cases/{case.id}/ai-report/", REPORT, format="json", HTTP_X_SERVICE_TOKEN="")
    assert resp.status_code == 403


def test_ai_report_is_stored_and_audited(case, settings):
    settings.AI_SERVICE_TOKEN = "s3cret"
    resp = APIClient().post(f"/api/cases/{case.id}/ai-report/", REPORT, format="json", HTTP_X_SERVICE_TOKEN="s3cret")
    assert resp.status_code == 200
    case.refresh_from_db()
    assert case.ai_recommendation == "BLOCK"
    assert case.ai_model == "test-llm"
    assert case.ai_generated_at is not None
    from cases.models import AuditLog
    assert AuditLog.objects.filter(action="case.ai_report", entity_id=str(case.id)).exists()


def test_ai_report_rejects_invalid_recommendation(case, settings):
    settings.AI_SERVICE_TOKEN = "s3cret"
    bad = {**REPORT, "recommendation": "DELETE_ACCOUNT"}
    resp = APIClient().post(f"/api/cases/{case.id}/ai-report/", bad, format="json", HTTP_X_SERVICE_TOKEN="s3cret")
    assert resp.status_code == 400


def test_timeseries_buckets_and_bad_params(make_event, analyst, client_for):
    ingest_scored_event(make_event())
    ingest_scored_event(make_event(score=0.9, flagged=True, risk="HIGH"))
    client = client_for(analyst)
    data = client.get("/api/transactions/timeseries/?hours=1&bucket=5").data
    assert data["bucket_minutes"] == 5
    assert 12 <= len(data["points"]) <= 13
    assert sum(p["total"] for p in data["points"]) == 2
    assert sum(p["flagged"] for p in data["points"]) == 1
    assert client.get("/api/transactions/timeseries/?hours=abc").status_code == 200  # falls back to default
    assert client.get("/api/transactions/stats/?hours=nope").status_code == 200
