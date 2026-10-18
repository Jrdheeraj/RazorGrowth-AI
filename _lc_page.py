"""AgentsPage: read-only mount, no auto-start, real Stop, submit guard."""
import io
import sys

PATH = "frontend/src/pages/AgentsPage.tsx"
with io.open(PATH, "r", encoding="utf-8") as fh:
    src = fh.read()

FIXES = []

# ── 1. import the new client functions ─────────────────────────────────────
FIXES.append((
    """  OrchestratorRunResponse,
  OrchestrationAgentOutput,""",
    """  OrchestratorRunResponse,
  OrchestrationAgentOutput,
  cancelAgentRun,
  fetchActiveRun,""",
))

# ── 2. the mount effect must ask the backend, not infer liveness ───────────
OLD_MOUNT = '''        const magiActive = magi.runs?.[0]
          ? magi.runs[0].status === "queued" || magi.runs[0].status === "running"
          : false;
        // The Product Agent is part of the same cycle: a live Product run
        // keeps the page in monitoring mode exactly like the Marketing Agent.
        const productActive = isProductAgentActive(product.runs?.[0]?.status);
        const teamActive = cycleRuns.some((r) => r.status === "running");
        if ((teamActive || magiActive || productActive) && cycleId) {
          // An analysis is still running server-side: resume observing it.
          activeCycleIdRef.current = cycleId;
          setIsWorking(true);
          setIsPaused(false);
          setCurrentPhaseText("Resumed — watching persisted analysis…");
          workingSinceRef.current = Date.now();
          startPolling(cycleId);
        } else {'''
NEW_MOUNT = '''        // Liveness comes from the backend, NOT from the presence of a
        // `running` row. A crashed worker leaves exactly such a row behind, and
        // inferring activity from it is what made this page show "ANALYZING…"
        // forever on a plain visit. `fetchActiveRun` applies a staleness bound
        // and never mutates anything, so mount, refresh and StrictMode remount
        // are all safe to call.
        const active = await fetchActiveRun().catch(() => null);
        if (cancelled) return;

        if (active?.active && active.run_id) {
          // Genuinely live server-side: observe it. This attaches to an existing
          // run; it never creates one.
          activeCycleIdRef.current = active.run_id;
          setIsWorking(true);
          setIsPaused(false);
          setCurrentPhaseText("Resumed — watching the active analysis…");
          workingSinceRef.current = Date.now();
          startPolling(active.run_id);
        } else {'''
FIXES.append((OLD_MOUNT, NEW_MOUNT))

# ── 3. DELETE the ?objective= auto-start effect ────────────────────────────
OLD_AUTOSTART = '''  // auto-start from URL
  useEffect(() => {
    if (urlObjective && agentsMeta && !autoStartedRef.current && !isWorking) {
      autoStartedRef.current = true;
      void handleStartAiWork(urlObjective);
    }
  }, [urlObjective, agentsMeta]);

'''
FIXES.append((OLD_AUTOSTART, '''  // NOTE: there is deliberately NO auto-start effect here.
  //
  // An effect that started analysis whenever a `?objective=` query parameter was
  // present meant simply navigating to /agents?objective=... launched a full
  // 14-agent cycle with no user action. Starting analysis is now reachable ONLY
  // from the explicit Start Analysis control (handleStartAiWork is called from
  // the button handler and nowhere else), which is also what makes "one click,
  // one run" enforceable.

'''))

# ── 4. real Stop, plus a submit guard ──────────────────────────────────────
OLD_START = '''  const handleStartAiWork = async (targetObjective?: string) => {
    const obj = targetObjective || urlObjective || DEFAULT_OBJECTIVE;
    if (isWorking) return;
    setIsWorking(true);'''
NEW_START = '''  const handleStartAiWork = async (targetObjective?: string) => {
    const obj = targetObjective || urlObjective || DEFAULT_OBJECTIVE;
    // Guard against a double submission with a ref, not React state: state is
    // not updated until after this function yields, so two rapid clicks in the
    // same tick would both pass an `isWorking` check. The backend also
    // deduplicates, so this is defence in depth rather than the only defence.
    if (startInFlightRef.current || isWorking) return;
    startInFlightRef.current = true;
    setIsWorking(true);'''
FIXES.append((OLD_START, NEW_START))

FIXES.append((
    '''      const cycleId = res.orchestrator_run_id;
      setLastRunResult(res);
      setLastAnalysisTime(Date.now());
      setCurrentPhaseText(`ANALYSIS STARTED — Cycle ${cycleId.slice(0, 8)}…`);
      startPolling(cycleId);
    } catch (e) {
      stopPolling();''',
    '''      const cycleId = res.orchestrator_run_id;
      setLastRunResult(res);
      setLastAnalysisTime(Date.now());
      setCurrentPhaseText(`ANALYSIS STARTED — Cycle ${cycleId.slice(0, 8)}…`);
      startPolling(cycleId);
    } catch (e) {
      stopPolling();
      activeCycleIdRef.current = null;''',
))

FIXES.append((
    '''      setIsWorking(false);
      setIsPaused(false);
      setCurrentPhaseText("");
    }
  };

  const togglePause = () => {''',
    '''      setIsWorking(false);
      setIsPaused(false);
      setCurrentPhaseText("");
    } finally {
      startInFlightRef.current = false;
    }
  };

  /**
   * Stop actually stops the backend.
   *
   * The previous control only suspended polling and its own message said
   * "Backend analysis continues" — the run kept executing with no way to halt
   * it. This calls the cancel endpoint, which persists the request and
   * terminalises the cycle, so no further plan step starts.
   *
   * Honest about the limit: cancellation is observed BETWEEN steps. A step
   * already inside an agent body — or inside an external call the provider
   * controls — is not recalled. That is why the endpoint marks the cycle
   * cancelled immediately rather than waiting for the worker to notice.
   */
  const handleStopAiWork = async () => {
    const cycleId = activeCycleIdRef.current;
    if (!cycleId) {
      stopPolling();
      setIsWorking(false);
      setIsPaused(false);
      setCurrentPhaseText("");
      return;
    }
    setIsCancelling(true);
    setCurrentPhaseText("Stopping — requesting cancellation…");
    try {
      await cancelAgentRun(cycleId);
      stopPolling();
      activeCycleIdRef.current = null;
      setIsWorking(false);
      setIsPaused(false);
      setCurrentPhaseText("Analysis cancelled.");
      setLastAnalysisTime(Date.now());
      const finalRuns = await fetchAgentRuns(50, cycleId).catch(() => null);
      if (finalRuns?.runs) setLiveRuns(finalRuns.runs);
    } catch (e) {
      setWorkError(
        e instanceof Error ? e.message : "Could not cancel the analysis.",
      );
      // The run may still be live: keep observing rather than lying about it.
    } finally {
      setIsCancelling(false);
    }
  };

  const togglePause = () => {''',
))

# ── 5. state for the guards ────────────────────────────────────────────────
FIXES.append((
    '''  const autoStartedRef = useRef(false);''',
    '''  // Ref-based submit guard: see handleStartAiWork.
  const startInFlightRef = useRef(false);''',
))
FIXES.append((
    '''  const [isWorking, setIsWorking] = useState(false);''',
    '''  const [isWorking, setIsWorking] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);''',
))

for old, new in FIXES:
    if old not in src:
        print("MISSING ->", old.splitlines()[0][:70])
        sys.exit(1)
    src = src.replace(old, new, 1)

with io.open(PATH, "w", encoding="utf-8", newline="") as fh:
    fh.write(src)

import io as _io
print("AGENTS_PAGE_LIFECYCLE_OK")