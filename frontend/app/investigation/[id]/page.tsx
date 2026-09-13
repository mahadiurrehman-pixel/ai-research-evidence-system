"use client";

import { VerdictDisplay } from "@/components/verdict/VerdictDisplay";
import { EvidenceTimeline } from "@/components/verdict/EvidenceTimeline";
import { Badge } from "@/components/ui/Badge";
import { getInvestigation } from "@/lib/api";
import type { Investigation, PipelineStage } from "@/lib/types";
import {
  ArrowLeft,
  Clock,
  FileSearch,
  AlertCircle,
  Activity,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

const stageLabels = [
  ["routing", "Claim analysis"],
  ["planning", "Research planning"],
  ["searching", "Evidence retrieval"],
  ["verifying", "Analysis and verification"],
  ["verdict", "Final result"],
] as const;

function stagesForStatus(status: string): PipelineStage[] {
  const statusIndex = { CREATED: 0, ROUTING: 0, PLANNING: 1, SEARCHING: 2, VERIFYING: 3, COMPLETED: 5, INCONCLUSIVE: 5, FAILED: 5 }[status] ?? 0;
  return stageLabels.map(([id, label], index) => ({
    id,
    label,
    status: status === "FAILED" && index === statusIndex ? "error" : index < statusIndex ? "complete" : index === statusIndex ? "active" : "pending",
  }));
}

export default async function InvestigationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [inv, setInv] = useState<Investigation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getInvestigation(id)
      .then(setInv)
      .catch((err) => setError(err instanceof Error ? err.message : "Unable to load this investigation."))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return <div className="mx-auto max-w-3xl px-4 py-16 text-center text-sm text-slate-500">Loading investigation...</div>;
  }

  if (error || !inv) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 text-center">
        <AlertCircle className="mx-auto mb-3 h-6 w-6 text-verdict-contradicted" />
        <p className="text-sm text-verdict-contradicted">{error || "Investigation not found."}</p>
        <Link href="/history" className="mt-4 inline-block text-sm text-accent hover:text-accent-light">Back to history</Link>
      </div>
    );
  }

  return (
    <div className="max-w-[1400px] mx-auto px-4 sm:px-6 py-8 sm:py-10">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-5 mb-8">
        <div className="flex items-start gap-4">
          <Link
            href="/history"
            className="p-2 rounded-lg text-slate-500 hover:text-surface-200 hover:bg-ink-800/40 transition-colors mt-0.5"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Badge variant="muted" size="sm">
                {id}
              </Badge>
              {inv.route_metadata && (
                <Badge variant="accent" size="sm">
                  {inv.route_metadata.domain}
                </Badge>
              )}
            </div>
            <h1 className="font-display text-xl sm:text-2xl font-semibold text-surface-100 tracking-tight max-w-2xl leading-tight">
              {inv.question}
            </h1>
          </div>
        </div>

      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_260px] gap-6">
        {/* Left — Pipeline */}
        <div className="lg:sticky lg:top-20 lg:self-start">
          <div className="p-4 rounded-2xl glass-surface">
            <h3 className="text-xs font-semibold text-accent-dark tracking-[0.12em] uppercase mb-4">
              Pipeline
            </h3>
            <EvidenceTimeline stages={stagesForStatus(inv.status)} />
          </div>
        </div>

        {/* Center — Verdict */}
        <div>
          {inv.verdict && (
            <VerdictDisplay
              verdict={inv.verdict}
              evidenceCount={inv.evidence_count}
              timeTaken={inv.time_taken}
            />
          )}
          {!inv.verdict && (
            <div className="rounded-2xl border border-dashed border-ink-700 bg-ink-850/70 p-8 text-center">
              <AlertCircle className="mx-auto mb-3 h-6 w-6 text-verdict-partial" />
              <h2 className="text-lg font-semibold text-surface-100">No final verdict returned</h2>
              <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-slate-500">
                This investigation finished as {inv.status.toLowerCase().replaceAll("_", " ")}. The API returned {inv.evidence_count} analyzed source{inv.evidence_count === 1 ? "" : "s"}, but no conclusion was available.
              </p>
            </div>
          )}
        </div>

        {/* Right — Metadata */}
        <div className="lg:sticky lg:top-20 lg:self-start space-y-4">
          <div className="p-4 rounded-2xl glass-surface space-y-4">
            <h3 className="text-xs font-semibold text-accent-dark tracking-[0.12em] uppercase">
              Metadata
            </h3>

            <div className="space-y-3">
              <div>
                <span className="text-2xs text-slate-600">Intent</span>
                <p className="text-sm text-surface-200">
                  {inv.route_metadata?.intent}
                </p>
              </div>
              <div>
                <span className="text-2xs text-slate-600">Complexity</span>
                <p className="text-sm text-surface-200">
                  {inv.route_metadata?.complexity}
                </p>
              </div>
              <div>
                <span className="text-2xs text-slate-600">Depth</span>
                <p className="text-sm text-surface-200">
                  {inv.route_metadata?.investigation_level}
                </p>
              </div>
            </div>
          </div>

          <div className="p-4 rounded-2xl glass-surface space-y-3">
            <h3 className="text-xs font-semibold text-accent-dark tracking-[0.12em] uppercase">
              Statistics
            </h3>
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <FileSearch className="w-4 h-4 text-accent" />
              {inv.evidence_count} sources
            </div>
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <Activity className="w-4 h-4 text-accent" />
              {inv.rounds_used} round(s)
            </div>
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <Clock className="w-4 h-4 text-accent" />
              {inv.time_taken}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}