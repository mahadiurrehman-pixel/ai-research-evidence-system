"use client";

import { use } from "react";
import { VerdictDisplay } from "@/components/verdict/VerdictDisplay";
import { EvidenceTimeline } from "@/components/verdict/EvidenceTimeline";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { mockInvestigation, mockPipelineStages } from "@/lib/mock-data";
import {
  ArrowLeft,
  Clock,
  FileSearch,
  Activity,
  Share2,
  Download,
  BookOpen,
} from "lucide-react";
import Link from "next/link";

export default function InvestigationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const inv = mockInvestigation;

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

        <div className="flex items-center gap-2 pl-12 sm:pl-0">
          <Button variant="ghost" size="sm">
            <Share2 className="w-3.5 h-3.5" />
            Share
          </Button>
          <Button variant="secondary" size="sm">
            <Download className="w-3.5 h-3.5" />
            Export
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_260px] gap-6">
        {/* Left — Pipeline */}
        <div className="lg:sticky lg:top-20 lg:self-start">
          <div className="p-4 rounded-2xl glass-surface">
            <h3 className="text-xs font-semibold text-accent-dark tracking-[0.12em] uppercase mb-4">
              Pipeline
            </h3>
            <EvidenceTimeline stages={mockPipelineStages} />
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
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <BookOpen className="w-4 h-4 text-accent" />
              {inv.verdict?.supporting_evidence.length} supporting
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}