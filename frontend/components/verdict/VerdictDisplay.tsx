"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, HelpCircle, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { ConfidenceMeter } from "./ConfidenceMeter";
import type { EvidenceCitation, VerdictResult } from "@/lib/types";
import {
  cn,
  getConfidencePercent,
  getVerdictBg,
  getVerdictColor,
  getVerdictLabel,
} from "@/lib/utils";

const verdictIcons = {
  SUPPORTED: CheckCircle2,
  PARTIALLY_SUPPORTED: AlertTriangle,
  CONTRADICTED: XCircle,
  NOT_SUPPORTED: XCircle,
  INCONCLUSIVE: HelpCircle,
} as const;

interface VerdictDisplayProps {
  verdict: VerdictResult;
  evidenceCount: number;
  timeTaken: string;
}

function EvidenceCard({
  evidence,
  tone,
}: {
  evidence: EvidenceCitation;
  tone: "supporting" | "contradicting";
}) {
  const isSupporting = tone === "supporting";
  const Icon = isSupporting ? CheckCircle2 : XCircle;

  return (
    <details
      className={cn(
        "group rounded-xl border p-4 transition-colors",
        isSupporting
          ? "border-verdict-supported/20 bg-verdict-supported/5 hover:border-verdict-supported/35"
          : "border-verdict-contradicted/20 bg-verdict-contradicted/5 hover:border-verdict-contradicted/35"
      )}
    >
      <summary className="flex cursor-pointer list-none items-start gap-3">
        <Icon
          className={cn(
            "mt-0.5 h-4 w-4 shrink-0",
            isSupporting ? "text-verdict-supported" : "text-verdict-contradicted"
          )}
        />
        <span className="min-w-0 flex-1">
          <span className="block text-2xs font-mono text-slate-500">{evidence.source_id}</span>
          <span className="mt-1 block text-sm font-medium leading-snug text-surface-100">
            {evidence.title || "Untitled source"}
          </span>
          <span className="mt-2 block text-sm leading-relaxed text-surface-300">
            {evidence.claim}
          </span>
        </span>
        <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-slate-500 transition-transform group-open:rotate-180" />
      </summary>
      <div className="ml-7 mt-3 border-t border-ink-700/50 pt-3">
        <p className="text-2xs font-semibold uppercase tracking-[0.12em] text-slate-500">Why it matters</p>
        <p className="mt-1 text-sm leading-relaxed text-surface-300">
          {evidence.reason || "No additional source rationale was provided."}
        </p>
      </div>
    </details>
  );
}

function Metric({
  label,
  value,
  detail,
  tone = "default",
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "default" | "supporting" | "contradicting" | "neutral";
}) {
  return (
    <div className="rounded-xl border border-ink-700/70 bg-ink-850/70 p-4">
      <p className="text-2xs font-semibold uppercase tracking-[0.1em] text-slate-500">{label}</p>
      <p
        className={cn(
          "mt-2 text-2xl font-semibold tracking-tight",
          tone === "supporting" && "text-verdict-supported",
          tone === "contradicting" && "text-verdict-contradicted",
          tone === "neutral" && "text-verdict-partial",
          tone === "default" && "text-surface-100"
        )}
      >
        {value}
      </p>
      {detail && <p className="mt-1 text-xs leading-relaxed text-slate-500">{detail}</p>}
    </div>
  );
}

export function VerdictDisplay({ verdict, evidenceCount, timeTaken }: VerdictDisplayProps) {
  const [showReasoning, setShowReasoning] = useState(false);
  const supporting = verdict.supporting_evidence ?? [];
  const contradicting = verdict.contradicting_evidence ?? [];
  const supportScore = evidenceCount > 0
    ? Math.round((supporting.length / evidenceCount) * 100)
    : null;
  const Icon = verdictIcons[verdict.verdict] || HelpCircle;

  return (
    <div className="space-y-6 animate-fade-in">
      <section className={cn("rounded-2xl border p-5 sm:p-6", getVerdictBg(verdict.verdict))}>
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
          <div className="flex min-w-0 flex-1 items-start gap-4">
            <div className="rounded-xl bg-white/60 p-3">
              <Icon className={cn("h-6 w-6", getVerdictColor(verdict.verdict))} />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className={cn("text-xl font-semibold tracking-tight", getVerdictColor(verdict.verdict))}>
                  {getVerdictLabel(verdict.verdict)}
                </h2>
                <Badge variant={verdict.confidence === "HIGH" ? "success" : verdict.confidence === "MEDIUM" ? "warning" : "muted"}>
                  {verdict.confidence} confidence
                </Badge>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-surface-300">{verdict.summary}</p>
            </div>
          </div>
          <ConfidenceMeter percent={getConfidencePercent(verdict.confidence)} size={76} />
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-end justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-surface-100">Evidence overview</h3>
            <p className="mt-1 text-xs text-slate-500">
              {evidenceCount} sources analyzed{timeTaken ? ` in ${timeTaken}` : ""}
            </p>
          </div>
          <span className="text-right text-xs text-slate-500">Counts from the analyzed evidence set</span>
        </div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Metric
            label="Evidence Support Score"
            value={supportScore === null ? "—" : `${supportScore}%`}
            detail="Supporting sources / analyzed sources"
            tone="supporting"
          />
          <Metric label="Sources analyzed" value={`${evidenceCount}`} detail="Returned by the research API" />
          <Metric label="Supporting evidence" value={`${supporting.length}`} tone="supporting" />
          <Metric label="Contradicting evidence" value={`${contradicting.length}`} tone="contradicting" />
        </div>
        <div className="mt-3 rounded-xl border border-verdict-partial/20 bg-verdict-partial/5 p-4">
          <div className="flex items-start gap-3">
            <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-verdict-partial" />
            <div>
              <p className="text-sm font-medium text-surface-100">Neutral / Insufficient Evidence</p>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">
                The API does not return a structured neutral count or individual neutral source details. Sources outside the supporting and contradicting citation lists are therefore not itemized here.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="space-y-5">
        <div>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-surface-100">Supporting evidence</h3>
            <Badge variant="success">{supporting.length} sources</Badge>
          </div>
          {supporting.length > 0 ? (
            <div className="space-y-2">
              {supporting.map((evidence) => <EvidenceCard key={evidence.source_id} evidence={evidence} tone="supporting" />)}
            </div>
          ) : (
            <p className="rounded-xl border border-dashed border-ink-700 p-4 text-sm text-slate-500">No supporting citations were returned.</p>
          )}
        </div>

        <div>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-surface-100">Contradicting evidence</h3>
            <Badge variant="error">{contradicting.length} sources</Badge>
          </div>
          {contradicting.length > 0 ? (
            <div className="space-y-2">
              {contradicting.map((evidence) => <EvidenceCard key={evidence.source_id} evidence={evidence} tone="contradicting" />)}
            </div>
          ) : (
            <p className="rounded-xl border border-dashed border-ink-700 p-4 text-sm text-slate-500">No contradicting citations were returned.</p>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-ink-700/70 bg-ink-850/70">
        <button
          type="button"
          onClick={() => setShowReasoning((visible) => !visible)}
          className="flex w-full items-center justify-between gap-3 p-4 text-left"
          aria-expanded={showReasoning}
        >
          <span>
            <span className="block text-sm font-semibold text-surface-100">Detailed reasoning</span>
            <span className="mt-1 block text-xs text-slate-500">How the conclusion was formed from the evidence</span>
          </span>
          <ChevronDown className={cn("h-4 w-4 text-slate-500 transition-transform", showReasoning && "rotate-180")} />
        </button>
        {showReasoning && (
          <div className="border-t border-ink-700/70 px-4 pb-4 pt-3">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-surface-300">{verdict.detailed_reasoning}</p>
          </div>
        )}
      </section>

      {verdict.limitations?.length > 0 && (
        <section>
          <h3 className="mb-3 text-sm font-semibold text-surface-100">Limitations</h3>
          <div className="space-y-2">
            {verdict.limitations.map((limitation, index) => (
              <div key={`${limitation}-${index}`} className="flex items-start gap-3 rounded-lg border border-ink-700/50 px-3 py-2.5 text-sm text-surface-300">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-verdict-partial" />
                <span>{limitation}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
