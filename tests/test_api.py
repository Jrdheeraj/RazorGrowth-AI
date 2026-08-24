"""
Integration tests for the RazorGrowth AI HTTP API.

Tests run entirely in-process via HTTPX + ASGI transport — no server needs
to be running. All data is deterministic synthetic data so assertions on
specific values are stable across runs.
"""
from __future__ import annotations


# --------------------------------------------------------------------------- #
# GET /
# --------------------------------------------------------------------------- #

class TestRoot:
    def test_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_response_shape(self, client):
        body = client.get("/").json()
        assert body["name"] == "RazorGrowth AI"
        assert body["status"] == "running"
        assert "version" in body

    def test_version_is_string(self, client):
        body = client.get("/").json()
        assert isinstance(body["version"], str)


# --------------------------------------------------------------------------- #
# GET /api/health
# --------------------------------------------------------------------------- #

class TestHealth:
    def test_returns_200(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_status_is_healthy(self, client):
        body = client.get("/api/health").json()
        assert body == {"status": "healthy"}


# --------------------------------------------------------------------------- #
# GET /api/opportunities
# --------------------------------------------------------------------------- #

class TestOpportunities:
    def test_returns_200(self, client):
        response = client.get("/api/opportunities")
        assert response.status_code == 200

    def test_response_has_items_list(self, client):
        body = client.get("/api/opportunities").json()
        assert "items" in body
        assert isinstance(body["items"], list)

    def test_at_least_one_opportunity(self, client):
        body = client.get("/api/opportunities").json()
        assert len(body["items"]) >= 1

    def test_opportunity_schema(self, client):
        item = client.get("/api/opportunities").json()["items"][0]
        required_fields = {
            "id", "type", "title", "target_product", "target_customers",
            "confidence", "expected_revenue", "reasoning", "status",
        }
        assert required_fields.issubset(item.keys()), (
            f"Missing fields: {required_fields - item.keys()}"
        )

    def test_cross_sell_opportunity_present(self, client):
        items = client.get("/api/opportunities").json()["items"]
        ids = [o["id"] for o in items]
        assert "opp_headphone_case" in ids

    def test_confidence_in_valid_range(self, client):
        items = client.get("/api/opportunities").json()["items"]
        for item in items:
            assert 0.0 <= item["confidence"] <= 1.0, (
                f"Confidence out of range for {item['id']}: {item['confidence']}"
            )

    def test_expected_revenue_is_positive(self, client):
        items = client.get("/api/opportunities").json()["items"]
        for item in items:
            assert item["expected_revenue"] > 0, (
                f"Expected revenue must be positive for {item['id']}"
            )

    def test_target_customers_is_positive(self, client):
        items = client.get("/api/opportunities").json()["items"]
        for item in items:
            assert item["target_customers"] > 0

    def test_reasoning_is_non_empty_list(self, client):
        items = client.get("/api/opportunities").json()["items"]
        for item in items:
            assert isinstance(item["reasoning"], list)
            assert len(item["reasoning"]) > 0

    def test_status_is_pending_approval(self, client):
        items = client.get("/api/opportunities").json()["items"]
        for item in items:
            assert item["status"] == "pending_approval"

    def test_deterministic_across_calls(self, client):
        """Same endpoint called twice must return identical results."""
        first  = client.get("/api/opportunities").json()
        second = client.get("/api/opportunities").json()
        assert first == second
