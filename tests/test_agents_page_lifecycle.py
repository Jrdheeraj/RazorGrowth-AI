"""
Frontend regression: /agents must never start analysis on its own.

WHAT THIS CAN AND CANNOT PROVE
------------------------------
The project has no browser-automation harness, and introducing one for a single
page would be a large new dependency rather than "focused tests with the
existing test stack". So these are static assertions on the component's effect
graph and call sites, run under pytest alongside the backend suite.

They are meaningful because the bug WAS structural, not visual: an effect that
called the start handler, and a Stop control wired to a function whose own
message said "Backend analysis continues". Both are properties of the source
that a behavioural test would also be asserting, and both are exactly the kind
of regression a later refactor reintroduces silently.

The backend contract these depend on is covered behaviourally in
``test_analysis_lifecycle.py``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PAGE = Path("frontend/src/pages/AgentsPage.tsx")
API = Path("frontend/src/lib/api.ts")


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def api() -> str:
    return API.read_text(encoding="utf-8")


def _braced(source: str, open_index: int) -> str:
    """Text of a brace-delimited block starting at ``open_index``.

    Brace matching rather than a fixed-width slice: a slice wide enough to be
    useful also spills into the NEXT function, which is how a Stop handler came
    to "contain" a Pause call that actually belonged to the Start handler after
    it.
    """
    depth, i = 0, open_index
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[open_index:i + 1]
        i += 1
    raise AssertionError("unbalanced braces")


def _body(source: str, marker: str) -> str:
    """The block a marker identifies.

    Two marker shapes are supported:

    * ``const someFn`` -> the body of that arrow function, located by following
      the declaration to its own ``=> {``. Searching backwards for an enclosing
      ``useEffect(`` would instead match whichever effect happened to be above
      it, which silently attributed one handler's code to another.
    * anything else (e.g. a line inside an effect) -> the enclosing effect.
    """
    start = source.index(marker)
    if marker.lstrip().startswith("const "):
        arrow = source.index("=>", start)
        return _braced(source, source.index("{", arrow))
    candidates = [p for p in (
        source.rfind("useEffect(", 0, start),
        source.rfind("=> {", 0, start),
    ) if p != -1]
    assert candidates, f"marker {marker!r} is not inside any block"
    return _braced(source, source.index("{", max(candidates)))


def _api_block(source: str, name: str) -> str:
    """An exported api.ts function, up to the next export."""
    start = source.index(f"export function {name}")
    nxt = source.find("\nexport ", start + 1)
    return source[start: nxt if nxt != -1 else len(source)]


# ════════════════════════════════════════════════════════════════════════════
# 1-2. Mount / refresh must not start anything
# ════════════════════════════════════════════════════════════════════════════


class TestNoAutoStart:
    def test_no_effect_calls_the_start_handler(self, page: str):
        """THE BUG: an effect started analysis on mount."""
        offenders = []
        for match in re.finditer(r"useEffect\(\(\)\s*=>\s*\{", page):
            # Walk to the matching close brace.
            depth, i = 1, match.end()
            while depth and i < len(page):
                if page[i] == "{":
                    depth += 1
                elif page[i] == "}":
                    depth -= 1
                i += 1
            body = page[match.start():i]
            if "handleStartAiWork" in body:
                offenders.append(body[:160])
        assert not offenders, (
            f"a useEffect calls the start handler; mounting or remounting the "
            f"page would start analysis without a user action: {offenders}"
        )

    def test_the_url_objective_auto_start_is_gone(self, page: str):
        assert "autoStartedRef" not in page, (
            "the ?objective= auto-start guard still exists"
        )
        assert "auto-start from URL" not in page

    def test_a_plain_objective_does_not_trigger_a_start(self, page: str):
        """The start handler must not fire from any effect or timer."""
        for forbidden in (
            "setTimeout(() => void handleStartAiWork",
            "setInterval(() => void handleStartAiWork",
            "window.setTimeout(handleStartAiWork",
        ):
            assert forbidden not in page, f"{forbidden} would start analysis"

    def test_start_is_only_reachable_from_the_button(self, page: str):
        """Exactly two call sites: its own definition and the control."""
        calls = len(re.findall(r"void handleStartAiWork\(", page))
        assert calls >= 2, "expected the button handlers to call the start handler"
        assert page.count("const handleStartAiWork") == 1


# ════════════════════════════════════════════════════════════════════════════
# 3. StrictMode / remount safety
# ════════════════════════════════════════════════════════════════════════════


class TestRemountSafety:
    def test_the_restore_effect_asks_the_backend_about_liveness(self, page: str):
        """Liveness must be a backend decision, not a client-side guess."""
        body = _body(page, "await fetchActiveRun().catch")
        assert "fetchActiveRun" in body
        assert 'status === "running"' not in body.split("fetchActiveRun")[0], (
            "the mount path must not infer activity from a status string before "
            "consulting the backend"
        )

    def test_the_restore_effect_only_ever_attaches_to_an_existing_run(
        self, page: str
    ):
        body = _body(page, "const active = await fetchActiveRun()")
        assert "handleStartAiWork" not in body, (
            "the restore path must never create a run"
        )
        assert "startPolling(active.run_id)" in body

    def test_polling_never_invokes_a_start_endpoint(self, page: str, api: str):
        for name in ("pollCycle", "startPolling", "finalizeCycle", "togglePause"):
            if f"const {name}" not in page:
                continue
            block = _body(page, f"const {name}")
            assert "startAiTeamWork" not in block, (
                f"{name} must be read-only and must not start anything"
            )
            assert "handleStartAiWork" not in block, (
                f"{name} must never invoke the start handler"
            )

    def test_the_polling_interval_is_cleared_on_unmount(self, page: str):
        assert "clearInterval(pollIntervalRef.current)" in page, (
            "an uncleared interval keeps polling after unmount"
        )


# ════════════════════════════════════════════════════════════════════════════
# 4. Clicking Start issues exactly one start
# ════════════════════════════════════════════════════════════════════════════


class TestSingleStart:
    def test_a_ref_guard_prevents_double_submission(self, page: str):
        """React state is not updated until after the handler yields, so two
        clicks in the same tick would both pass an `isWorking` check."""
        assert "startInFlightRef" in page
        body = _body(page, "const handleStartAiWork")
        assert "if (startInFlightRef.current || isWorking) return;" in body
        assert "startInFlightRef.current = false;" in body, (
            "the guard must be released, or a failed start would wedge the page"
        )

    def test_the_start_button_is_disabled_while_working(self, page: str):
        assert re.search(
            r"disabled=\{isWorking \|\| isCancelling", page
        ), "Start must be disabled while a run is in progress"


# ════════════════════════════════════════════════════════════════════════════
# 5-6. Stop cancels the real run; UI returns to a terminal state
# ════════════════════════════════════════════════════════════════════════════


class TestRealStop:
    def test_stop_calls_the_cancel_endpoint(self, page: str):
        body = _body(page, "const handleStopAiWork")
        assert "cancelAgentRun(cycleId)" in body, (
            "Stop must request backend cancellation of the specific run"
        )

    def test_stop_does_not_merely_pause_polling(self, page: str):
        """The bug: the control only stopped the poll and said so."""
        body = _body(page, "const handleStopAiWork")
        assert "stopPolling()" in body
        assert "togglePause" not in body, (
            "Stop must not be an alias for Pause; Pause only suspends observation"
        )

    def test_stop_clears_the_active_cycle_and_the_working_flag(self, page: str):
        body = _body(page, "const handleStopAiWork")
        assert "activeCycleIdRef.current = null;" in body
        assert "setIsWorking(false);" in body

    def test_stop_reports_the_outcome(self, page: str):
        body = _body(page, "const handleStopAiWork")
        assert "Analysis cancelled." in body, (
            "the operator must be told the run was cancelled, not silently "
            "snapped back to idle"
        )

    def test_pause_still_says_backend_continues(self, page: str):
        """Pause is honest about being observation-only. If this copy changes,
        the two controls have been conflated again."""
        assert "Backend analysis continues" in page

    def test_both_control_clusters_expose_stop(self, page: str):
        assert page.count("void handleStopAiWork()") >= 2


# ════════════════════════════════════════════════════════════════════════════
# 7. API client: read-only probe and real cancel
# ════════════════════════════════════════════════════════════════════════════


class TestApiClient:
    def test_the_probe_is_a_get(self, api: str):
        block = _api_block(api, "fetchActiveRun")
        assert "method:" not in block, (
            "the active-run probe must be a GET; it is called on every mount "
            "and every poll tick"
        )
        assert "/api/agents/active-run" in block

    def test_cancel_uses_post_against_the_specific_run(self, api: str):
        block = _api_block(api, "cancelAgentRun")
        assert 'method: "POST"' in block
        assert "/api/agents/runs/" in block and "cancel" in block
        assert "encodeURIComponent(runId)" in block, (
            "the run id must be encoded and scoped to one run"
        )

    def test_start_is_unchanged_and_still_explicit(self, api: str):
        block = _api_block(api, "startAiTeamWork")
        assert 'method: "POST"' in block
        assert 'mode: "team"' in block
