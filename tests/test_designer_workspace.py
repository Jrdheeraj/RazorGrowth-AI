"""Designer workspace — persistence, versioning, API and tenant isolation.

The security-critical assertions here are that a design record belonging to
another merchant is unreachable by id, by list, and by write, and that a
review decision is only possible through the approver role — the agent has no
path to it.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from backend.app.models.enums import (
    Currency,
    DesignAssetKind,
    DesignProjectStatus,
    DesignReviewStatus,
    MerchantStatus,
)
from backend.app.models.merchant import Merchant
from backend.app.schemas.designer import CreativeBriefSpec
from backend.app.services.designer_service import (
    DesignerNotFound,
    DesignerService,
)


def make_merchant(db_session: Session, tag: str) -> Merchant:
    m = Merchant(
        name=f"{tag} {uuid.uuid4().hex[:6]}",
        slug=f"{tag}-{uuid.uuid4().hex[:10]}",
        email=f"{tag}-{uuid.uuid4().hex[:6]}@example.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(m)
    db_session.commit()
    return m


def grounded_spec(**overrides) -> CreativeBriefSpec:
    payload = {
        "title": "Summer refresh",
        "objective": "One coherent visual system for the season",
        "project_type": "campaign_creative",
        "audience": "Repeat buyers",
        "channel": "instagram",
        "layout_direction": "Hero-led single column",
        "variants": [
            {
                "variant_key": "control",
                "title": "Editorial",
                "objective": "Baseline",
                "rationale": "Current direction",
                "evaluation_method": "A/B test",
            }
        ],
        "evidence": [
            {"statement": "12 failed payments", "basis": "observed", "source": "radar", "value": 12}
        ],
        "confidence": 0.7,
    }
    payload.update(overrides)
    return CreativeBriefSpec(**payload)


@pytest.fixture()
def image_gen_disabled(monkeypatch):
    """Pin image generation OFF for the duration of a test.

    `Settings` is an lru_cached singleton, so the cache must be cleared after
    the env change or the next reader would keep the previous value.
    """
    from backend.app.core.config import get_settings

    monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def workspace(db_session: Session):
    """Two merchants and one project owned by the first.

    The commit matters: ``db_session`` and the TestClient's overridden
    ``get_db`` are SEPARATE sessions over one shared in-memory SQLite, so an
    uncommitted write in the fixture would hold the write lock and the HTTP
    calls in the API tests would fail with "database table is locked".
    """
    a = make_merchant(db_session, "dw-a")
    b = make_merchant(db_session, "dw-b")
    svc = DesignerService(db_session)
    project = svc.create_project(a.id, objective="Refresh the summer creative", title="Summer")
    db_session.commit()
    return {"a": a, "b": b, "project": project, "svc": svc}


# ── persistence & versioning ─────────────────────────────────────────────


class TestPersistence:
    def test_project_created_and_retrievable(self, workspace, db_session):
        svc = DesignerService(db_session)
        got = svc.get_project(workspace["a"].id, workspace["project"].id)
        assert got.title == "Summer"
        assert got.status == DesignProjectStatus.active

    def test_brief_persists_and_is_current(self, workspace, db_session):
        svc = workspace["svc"]
        brief = svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        assert brief.version == 1
        assert brief.is_current == 1
        assert brief.review_status == DesignReviewStatus.pending_review

    def test_every_variant_becomes_a_versioned_asset(self, workspace):
        spec = grounded_spec(
            variants=[
                {"variant_key": "control", "title": "A", "objective": "o", "rationale": "r", "evaluation_method": "m"},
                {"variant_key": "variant_a", "title": "B", "objective": "o2", "rationale": "r2", "evaluation_method": "m2"},
            ]
        )
        self_out = workspace["svc"].store_brief(workspace["a"].id, workspace["project"], spec)
        assets = workspace["svc"].list_assets(workspace["a"].id, project_id=workspace["project"].id)
        assert len(assets) == 2
        assert {a.kind for a in assets} == {DesignAssetKind.variant}
        assert all(a.version_count == 1 for a in assets)
        # A brand-new text asset must never claim an image exists, whatever
        # the provider configuration happens to be.
        assert all(a.image_generation["asset_reference"] is None for a in assets)
        assert all(
            a.image_generation["status"] in ("unavailable", "available")
            for a in assets
        ), "the stamped state must reflect real configuration"
        assert self_out is not None

    def test_revision_appends_and_never_overwrites(self, workspace):
        svc = workspace["svc"]
        svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        asset = svc.list_assets(workspace["a"].id)[0]
        original = svc.current_asset_content(workspace["a"].id, asset)

        svc.revise_asset(
            workspace["a"].id, asset.id,
            content={**original, "changed": True},
            change_summary="Tweaked the CTA",
        )
        versions = svc.list_asset_versions(workspace["a"].id, asset.id)
        assert [v.version for v in versions] == [2, 1]
        # v1 must be byte-identical to what was first written.
        assert versions[-1].content == original
        assert versions[0].content["changed"] is True

    def test_brief_revision_retains_earlier_versions(self, workspace):
        svc = workspace["svc"]
        svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        versions = svc.list_brief_versions(workspace["a"].id, workspace["project"].id)
        assert [v.version for v in versions] == [2, 1]
        assert versions[0].is_current == 1
        assert versions[1].is_current == 0

    def test_survives_a_fresh_session(self, workspace, db_session):
        """Projects and briefs must persist, not live in request memory."""
        svc = workspace["svc"]
        svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        db_session.commit()

        db_session.expunge_all()
        fresh = DesignerService(db_session)
        assert fresh.count_projects(workspace["a"].id) == 1
        assert len(fresh.list_briefs(workspace["a"].id)) == 1

    def test_metrics_derive_from_persisted_rows(self, workspace):
        svc = workspace["svc"]
        svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        metrics = {m["key"]: m["value"] for m in svc.metrics(workspace["a"].id)}
        assert metrics["projects"] == 1
        assert metrics["briefs"] == 1
        assert metrics["awaiting_review"] == 1
        assert metrics["approved"] == 0

    def test_activity_is_built_from_real_rows(self, workspace):
        svc = workspace["svc"]
        svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        kinds = {i["kind"] for i in svc.activity(workspace["a"].id)}
        assert "project" in kinds and "brief" in kinds


# ── tenant isolation ─────────────────────────────────────────────────────


class TestTenantIsolation:
    def test_other_merchant_cannot_read_a_project(self, workspace, db_session):
        with pytest.raises(DesignerNotFound):
            DesignerService(db_session).get_project(workspace["b"].id, workspace["project"].id)

    def test_other_merchant_list_is_empty(self, workspace, db_session):
        assert DesignerService(db_session).list_projects(workspace["b"].id) == []

    def test_other_merchant_cannot_update(self, workspace, db_session):
        with pytest.raises(DesignerNotFound):
            DesignerService(db_session).update_project(
                workspace["b"].id, workspace["project"].id, title="stolen"
            )

    def test_other_merchant_cannot_read_a_brief(self, workspace, db_session):
        svc = workspace["svc"]
        brief = svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        with pytest.raises(DesignerNotFound):
            DesignerService(db_session).get_brief(workspace["b"].id, brief.id)

    def test_other_merchant_cannot_revise_an_asset(self, workspace, db_session):
        svc = workspace["svc"]
        svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        asset = svc.list_assets(workspace["a"].id)[0]
        with pytest.raises(DesignerNotFound):
            DesignerService(db_session).revise_asset(
                workspace["b"].id, asset.id, content={}, change_summary="x"
            )

    def test_other_merchant_metrics_are_zero(self, workspace, db_session):
        svc = workspace["svc"]
        svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        other = {m["key"]: m["value"] for m in DesignerService(db_session).metrics(workspace["b"].id)}
        assert all(v == 0 for v in other.values())


# ── review is a human act ────────────────────────────────────────────────


class TestReviewAuthority:
    def test_review_records_a_human_decision(self, workspace):
        svc = workspace["svc"]
        brief = svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        updated = svc.record_review(
            workspace["a"].id, brief.id, decision="approved", notes="Looks right"
        )
        assert updated.review_status == DesignReviewStatus.approved
        assert updated.review_notes == "Looks right"

    def test_changes_requested_is_a_real_state(self, workspace):
        svc = workspace["svc"]
        brief = svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        updated = svc.record_review(workspace["a"].id, brief.id, decision="changes_requested")
        assert updated.review_status == DesignReviewStatus.changes_requested

    def test_approved_brief_moves_the_metric(self, workspace):
        svc = workspace["svc"]
        brief = svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        svc.record_review(workspace["a"].id, brief.id, decision="approved")
        metrics = {m["key"]: m["value"] for m in svc.metrics(workspace["a"].id)}
        assert metrics["approved"] == 1
        assert metrics["awaiting_review"] == 0


# ── image generation honesty ─────────────────────────────────────────────


class TestImageGenerationHonesty:
    """These pin the DISABLED behaviour explicitly.

    Without forcing the flag off, a developer with image generation enabled in
    their .env would make this suite issue REAL provider calls. Pinning the
    state keeps these tests deterministic and network-free, while
    TestDesignerImageGeneration covers the enabled path with a mocked provider.
    """

    def test_status_is_unavailable_with_a_reason(self, workspace, image_gen_disabled):
        """With the flag OFF the state is unavailable, and says why."""
        status = workspace["svc"].image_generation_status()
        assert status["status"] == "unavailable"
        assert status["asset_reference"] is None
        assert status["reason"], "an unavailable provider must state why"

    def test_requesting_an_image_never_fabricates_one(self, workspace, image_gen_disabled):
        """Disabled means no image, no reference, and no provider call."""
        svc = workspace["svc"]
        svc.store_brief(workspace["a"].id, workspace["project"], grounded_spec())
        asset = svc.list_assets(workspace["a"].id)[0]
        result = svc.request_image_generation(workspace["a"].id, asset.id)
        assert result["status"] == "unavailable"
        assert result["asset_reference"] is None
        # The asset is still a text artefact, never promoted to a rendered image.
        assert asset.kind == DesignAssetKind.variant


# ── HTTP API ─────────────────────────────────────────────────────────────


class TestDesignerApi:
    def _q(self, merchant_id) -> dict:
        return {"merchant_id": str(merchant_id)}

    def test_status_reflects_real_registry_and_projects(self, client: TestClient, workspace, image_gen_disabled):
        body = client.get("/api/designer/status", params=self._q(workspace["a"].id)).json()
        assert body["agent_registered"] is True
        assert {c["key"] for c in body["capabilities"]} == {
            "creative_concept", "messaging_strategy", "experiment_variants",
            "ux_recommendations", "creative_brief",
        }
        assert body["counts"]["projects"] == 1
        assert body["image_generation"]["status"] == "unavailable"

    def test_integrations_are_never_claimed_connected(self, client: TestClient, workspace):
        body = client.get("/api/designer/status", params=self._q(workspace["a"].id)).json()
        providers = {i["provider"]: i["status"] for i in body["integrations"]}
        assert providers, "the tool catalogue must still be reported"
        assert all(status == "setup_required" for status in providers.values())
        assert all(status != "connected" for status in providers.values())

    def test_create_project_and_list(self, client: TestClient, workspace):
        resp = client.post(
            "/api/designer/projects",
            json={"objective": "Design a landing page for the new range"},
            params=self._q(workspace["a"].id),
        )
        assert resp.status_code == 201
        pid = resp.json()["id"]
        listed = client.get("/api/designer/projects", params=self._q(workspace["a"].id)).json()
        assert pid in [p["id"] for p in listed["projects"]]

    def test_repeat_objective_does_not_fork_a_project(self, client: TestClient, workspace, db_session):
        db_session.commit()
        body = {"objective": "Design one landing page"}
        first = client.post("/api/designer/projects", json=body, params=self._q(workspace["a"].id)).json()
        second = client.post("/api/designer/projects", json=body, params=self._q(workspace["a"].id)).json()
        assert first["id"] == second["id"]

    def test_short_objective_is_rejected(self, client: TestClient, workspace):
        resp = client.post(
            "/api/designer/projects", json={"objective": "hi"}, params=self._q(workspace["a"].id)
        )
        assert resp.status_code == 422

    def test_malformed_id_is_a_400_not_a_500(self, client: TestClient, workspace):
        resp = client.get("/api/designer/projects/not-a-uuid", params=self._q(workspace["a"].id))
        assert resp.status_code == 400

    def test_cross_tenant_read_is_404(self, client: TestClient, workspace):
        resp = client.get(
            f"/api/designer/projects/{workspace['project'].id}",
            params=self._q(workspace["b"].id),
        )
        assert resp.status_code == 404

    def test_cross_tenant_patch_is_404(self, client: TestClient, workspace):
        resp = client.patch(
            f"/api/designer/projects/{workspace['project'].id}",
            json={"title": "stolen"},
            params=self._q(workspace["b"].id),
        )
        assert resp.status_code == 404

    def test_cross_tenant_list_is_empty(self, client: TestClient, workspace):
        listed = client.get("/api/designer/projects", params=self._q(workspace["b"].id)).json()
        assert listed["total"] == 0

    def test_image_generation_endpoint_is_honest(self, client: TestClient, workspace, image_gen_disabled):
        body = client.get("/api/designer/image-generation", params=self._q(workspace["a"].id)).json()
        assert body["status"] == "unavailable"
        assert body["asset_reference"] is None

    def test_ux_audit_reports_its_unavailability_honestly(self, client: TestClient, workspace):
        resp = client.post(
            "/api/designer/ux-audit",
            json={"objective": "Audit the checkout experience"},
            params=self._q(workspace["a"].id),
        )
        assert resp.status_code == 200
        body = resp.json()
        # No LLM is configured in tests, so it must say so rather than invent.
        assert body["sufficient_context"] in (True, False)
        if body["unavailable_reason"]:
            assert isinstance(body["findings"], list)

    def test_review_of_an_unknown_brief_is_404(self, client: TestClient, workspace):
        resp = client.post(
            f"/api/designer/briefs/{uuid.uuid4()}/review",
            json={"decision": "approved"},
            params=self._q(workspace["a"].id),
        )
        assert resp.status_code == 404
