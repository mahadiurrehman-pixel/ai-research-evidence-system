"use client";

import { useState, useEffect, Suspense, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { ClaimComposer } from "@/components/investigate/ClaimComposer";
import { VerdictDisplay } from "@/components/verdict/VerdictDisplay";
import { EvidenceTimeline } from "@/components/verdict/EvidenceTimeline";
import { startInvestigation, pollInvestigation, getInvestigation } from "@/lib/api";
import { mockPipelineStages } from "@/lib/mock-data";
import type { Investigation, PipelineStage } from "@/lib/types";
import { Clock, FileSearch, Activity, AlertCircle, Terminal, HelpCircle } from "lucide-react";

const statusToStageMap: Record<string, number> = {
  CREATED: 0,
  ROUTING: 1,
  PLANNING: 2,
  SEARCHING: 3,
  VERIFYING: 5,
  COMPLETED: 6,
  INCONCLUSIVE: 6,
  FAILED: 6,
};

function InvestigateContent() {
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") || "";

  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [currentStatus, setCurrentStatus] = useState("");
  const [liveLogs, setLiveLogs] = useState<string[]>([]);
  
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [liveLogs]);

  const handleInvestigate = async (question: string) => {
    setLoading(true);
    setError(null);
    setInvestigation(null);
    setLiveLogs(["Initializing research protocol...", "Connecting to orchestrator..."]);

    const pendingStages = mockPipelineStages.map((s) => ({
      ...s,
      status: "pending" as const,
    }));
    setStages(pendingStages);

    try {
      const { investigation_id } = await startInvestigation(question);
      setLiveLogs(prev => [...prev, `Assigned Investigation ID: ${investigation_id}`]);

      const result = await pollInvestigation(
        investigation_id,
        async (status) => {
          setCurrentStatus(status);
          
          try {
            const tempResult = await getInvestigation(investigation_id);
            if (tempResult.trace_summary && tempResult.trace_summary.length > 0) {
              setLiveLogs(tempResult.trace_summary);
            }
          } catch (e) {
            // ignore temp fetch errors
          }

          const activeIdx = statusToStageMap[status] ?? 3;
          setStages((prev) =>
            prev.map((s, idx) => ({
              ...s,
              status:
                idx < activeIdx
                  ? "complete"
                  : idx === activeIdx
                  ? "active"
                  : ("pending" as PipelineStage["status"]),
            }))
          );
        },
        180000,
        1000
      );

      setStages(mockPipelineStages.map(s => ({ ...s, status: "complete" })));
      setInvestigation(result);
      setLiveLogs(result.trace_summary || ["Processing complete."]);

    } catch (err) {
      setError(err instanceof Error ? err.message : "Investigation failed");
      setStages((prev) => prev.map((s) => ({ ...s, status: "error" as const })));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (initialQuery) {
      handleInvestigate(initialQuery);
    }
  }, [initialQuery]);

  return (
    <div className="max-w-[1400px] mx-auto px-6 py-8">
      <div className="mb-8">
        <ClaimComposer onSubmit={handleInvestigate} loading={loading} />
      </div>

      {error && (
        <div className="max-w-3xl mx-auto mb-6 p-4 rounded-xl bg-verdict-contradicted/5 border border-verdict-contradicted/20 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-verdict-contradicted flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-verdict-contradicted">
              Investigation Failed
            </p>
            <p className="text-sm text-slate-400 mt-1">{error}</p>
          </div>
        </div>
      )}

      {(loading || investigation) && (
        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6 animate-fade-in">
          
          {/* Left Sidebar — Pipeline Status */}
          <div className="lg:sticky lg:top-20 lg:self-start">
            <div className="p-4 rounded-2xl glass-surface">
              <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-4">
                Investigation Pipeline
              </h3>
              <EvidenceTimeline stages={stages} />

              {(investigation || loading) && (
                <div className="mt-6 pt-4 border-t border-ink-700/15 space-y-3">
                  {currentStatus && loading && (
                    <div className="flex items-center gap-2 text-xs text-accent">
                      <Activity className="w-3.5 h-3.5 animate-pulse" />
                      <span>{currentStatus}</span>
                    </div>
                  )}
                  {investigation && (
                    <>
                      <div className="flex items-center gap-2 text-xs text-slate-500">
                        <Clock className="w-3.5 h-3.5" />
                        <span>{investigation.time_taken || "In progress..."}</span>
                      </div>
                      <div className="flex items-center gap-2 text-xs text-slate-500">
                        <FileSearch className="w-3.5 h-3.5" />
                        <span>{investigation.evidence_count || 0} sources</span>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Center — Real-Time Terminal or Final Verdict */}
          <div>
            {loading && !investigation ? (
              
              /* Live Terminal View */
              <div className="rounded-2xl border border-ink-700/30 bg-ink-900 overflow-hidden shadow-elevated">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-ink-700/30 bg-ink-850">
                  <Terminal className="w-4 h-4 text-slate-400" />
                  <span className="text-xs font-medium text-slate-400 tracking-wider">Live Trace Logs</span>
                  <div className="ml-auto flex gap-1.5">
                    <div className="w-2.5 h-2.5 rounded-full bg-ink-600"></div>
                    <div className="w-2.5 h-2.5 rounded-full bg-ink-600"></div>
                    <div className="w-2.5 h-2.5 rounded-full bg-accent animate-pulse"></div>
                  </div>
                </div>
                
                <div className="p-5 font-mono text-xs text-slate-400 h-[400px] overflow-y-auto space-y-2">
                  {liveLogs.map((log, i) => (
                    <div key={i} className="flex gap-3 items-start animate-slide-up" style={{ animationDuration: "0.2s" }}>
                      <span className="text-ink-600 select-none">{String(i + 1).padStart(2, '0')}</span>
                      <span className={
                        log.includes("error") || log.includes("failed") ? "text-verdict-contradicted" :
                        log.includes("ok") || log.includes("sufficient") ? "text-verdict-supported" :
                        "text-surface-300"
                      }>
                        {log}
                      </span>
                    </div>
                  ))}
                  <div className="flex gap-3 items-start mt-2">
                    <span className="text-ink-600 select-none">--</span>
                    <span className="w-2 h-3.5 bg-accent/70 animate-pulse"></span>
                  </div>
                  <div ref={logsEndRef} />
                </div>
              </div>
              
            ) : investigation?.verdict ? (
              <VerdictDisplay
                verdict={investigation.verdict}
                evidenceCount={investigation.evidence_count}
                timeTaken={investigation.time_taken}
              />
            ) : (
              /* ★ NEW: Fallback Card for INCONCLUSIVE / null verdict */
              <div className="p-8 rounded-2xl border border-ink-700/30 bg-ink-850/60 text-center space-y-4 animate-fade-in">
                <div className="w-12 h-12 rounded-full bg-slate-500/10 border border-slate-500/20 flex items-center justify-center mx-auto text-slate-400">
                  <HelpCircle className="w-6 h-6" />
                </div>
                <h3 className="text-lg font-semibold text-surface-100">
                  Inconclusive Research Outcome
                </h3>
                <p className="text-sm text-slate-400 max-w-md mx-auto leading-relaxed">
                  The system gathered {investigation?.evidence_count || 0} sources, but could not retrieve enough relevant empirical evidence to establish a definitive verdict for this query.
                </p>
                <div className="pt-2 text-2xs text-slate-500 font-mono">
                  Tip: Mock M2 currently contains pre-loaded dataset papers on AI Learning. Connect live M2 search APIs for general web/fasting queries.
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function InvestigatePage() {
  return (
    <Suspense>
      <InvestigateContent />
    </Suspense>
  );
}