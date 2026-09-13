"use client";

import { cn } from "@/lib/utils";
import {
  getVerdictColor,
  getVerdictBg,
  getVerdictLabel,
  getConfidencePercent,
} from "@/lib/utils";
import { ConfidenceMeter } from "./ConfidenceMeter";
import { Badge } from "@/components/ui/Badge";
import type { VerdictResult } from "@/lib/types";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  HelpCircle,
  ChevronDown,
} from "lucide-react";
import { useState } from "react";

const verdictIcons: Record<string, typeof CheckCircle2> = {
  SUPPORTED: CheckCircle2,
  PARTIALLY_SUPPORTED: AlertTriangle,
  CONTRADICTED: XCircle,
  NOT_SUPPORTED: XCircle,
  INCONCLUSIVE: HelpCircle,
};

interface VerdictDisplayProps {
  verdict: VerdictResult;
  evidenceCount: number;
  timeTaken: string;
}

export function VerdictDisplay({
  verdict,
  evidenceCount,
  timeTaken,
}: VerdictDisplayProps) {
  const [showReasoning, setShowReasoning] = useState(false);
  const Icon = verdictIcons[verdict.verdict] || HelpCircle;
  const confPercent = getConfidencePercent(verdict.confidence);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Main verdict card */}
      <div
        className={cn(
          "relative overflow-hidden rounded-2xl border p-6",
          getVerdictBg(verdict.verdict)
        )}
      >
        {/* Accent line */}
        <div
          className={cn(
            "absolute top-0 left-0 right-0 h-0.5",
            verdict.verdict === "SUPPORTED" && "bg-verdict-supported",
            verdict.verdict === "PARTIALLY_SUPPORTED" && "bg-verdict-partial",
            verdict.verdict === "CONTRADICTED" && "bg-verdict-contradicted",
            verdict.verdict === "INCONCLUSIVE" && "bg-slate-500"
          )}
        />

        <div className="flex flex-col sm:flex-row items-start gap-4 sm:gap-5">
          <div
            className={cn(
              "p-3 rounded-xl",
              verdict.verdict === "SUPPORTED" &&
                "bg-verdict-supported/10",
              verdict.verdict === "PARTIALLY_SUPPORTED" &&
                "bg-verdict-partial/10",
              verdict.verdict === "CONTRADICTED" &&
                "bg-verdict-contradicted/10",
              verdict.verdict === "INCONCLUSIVE" && "bg-slate-500/10"
            )}
          >
            <Icon className={cn("w-6 h-6", getVerdictColor(verdict.verdict))} />
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-3 mb-2">
              <h2
                className={cn(
                  "text-xl font-semibold tracking-tight",
                  getVerdictColor(verdict.verdict)
                )}
              >
                {getVerdictLabel(verdict.verdict)}
              </h2>
              <Badge
                variant={
                  verdict.confidence === "HIGH"
                    ? "success"
                    : verdict.confidence === "MEDIUM"
                    ? "warning"
                    : "muted"
                }
              >
                {verdict.confidence} Confidence
              </Badge>
            </div>

            <p className="text-sm text-surface-300 leading-relaxed">
              {verdict.summary}
            </p>

            {/* Stats row */}
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 mt-4 text-xs text-slate-500">
              <span>
                <strong className="text-surface-200">{evidenceCount}</strong>{" "}
                sources analyzed
              </span>
              <span>
                <strong className="text-surface-200">
                  {verdict.supporting_evidence.length}
                </strong>{" "}
                supporting
              </span>
              <span>
                <strong className="text-surface-200">
                  {verdict.contradicting_evidence.length}
                </strong>{" "}
                contradicting
              </span>
              <span>Completed in {timeTaken}</span>
            </div>
          </div>

          <div className="sm:ml-auto">
            <ConfidenceMeter percent={confPercent} size={72} />
          </div>
        </div>
      </div>

      {/* Supporting Evidence */}
      {verdict.supporting_evidence.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider">
            Supporting Evidence
          </h3>
          <div className="space-y-2">
            {verdict.supporting_evidence.map((ev) => (
              <div
                key={ev.source_id}
                className="flex items-start gap-3 p-3 rounded-xl bg-verdict-supported/5 border border-verdict-supported/10"
              >
                <CheckCircle2 className="w-4 h-4 mt-0.5 text-verdict-supported flex-shrink-0" />
                <div className="min-w-0">
                  <span className="text-xs font-mono text-verdict-supported/70">
                    [{ev.source_id}]
                  </span>
                  <p className="text-sm text-surface-200 mt-0.5 leading-relaxed">
                    {ev.claim}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Contradicting Evidence */}
      {verdict.contradicting_evidence.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider">
            Contradicting Evidence
          </h3>
          <div className="space-y-2">
            {verdict.contradicting_evidence.map((ev) => (
              <div
                key={ev.source_id}
                className="flex items-start gap-3 p-3 rounded-xl bg-verdict-contradicted/5 border border-verdict-contradicted/10"
              >
                <XCircle className="w-4 h-4 mt-0.5 text-verdict-contradicted flex-shrink-0" />
                <div className="min-w-0">
                  <span className="text-xs font-mono text-verdict-contradicted/70">
                    [{ev.source_id}]
                  </span>
                  <p className="text-sm text-surface-200 mt-0.5 leading-relaxed">
                    {ev.claim}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Detailed Reasoning */}
      <div>
        <button
          onClick={() => setShowReasoning(!showReasoning)}
          className="flex items-center gap-2 text-sm text-slate-500 hover:text-surface-200 transition-colors"
        >
          <ChevronDown
            className={cn(
              "w-4 h-4 transition-transform",
              showReasoning && "rotate-180"
            )}
          />
          Detailed Reasoning
        </button>

        {showReasoning && (
          <div className="mt-3 p-4 rounded-xl bg-ink-850/60 border border-ink-700/15 animate-slide-up">
            <pre className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap font-mono">
              {verdict.detailed_reasoning}
            </pre>
          </div>
        )}
      </div>

      {/* Limitations */}
      {verdict.limitations.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider">
            Limitations
          </h3>
          <div className="space-y-1.5">
            {verdict.limitations.map((lim, i) => (
              <div
                key={i}
                className="flex items-start gap-2 text-sm text-slate-400"
              >
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 text-verdict-partial/50 flex-shrink-0" />
                {lim}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}