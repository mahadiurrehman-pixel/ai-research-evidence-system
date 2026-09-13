"use client";

import { Badge } from "@/components/ui/Badge";
import { getHistory } from "@/lib/api";
import type { Investigation } from "@/lib/types";
import { getVerdictLabel, timeAgo } from "@/lib/utils";
import { FileSearch, Clock, ArrowRight, AlertCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

export default function HistoryPage() {
  const [history, setHistory] = useState<Investigation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHistory()
      .then(setHistory)
      .catch((err) => setError(err instanceof Error ? err.message : "Unable to load history."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="max-w-[1000px] mx-auto px-4 sm:px-6 py-8 sm:py-10">
      <div className="flex items-start justify-between gap-4 mb-8">
        <div>
          <p className="text-xs font-semibold text-accent-dark tracking-[0.14em] uppercase mb-2">
            Your research trail
          </p>
          <h1 className="font-display text-3xl font-semibold text-surface-100 tracking-tight">
            Investigation History
          </h1>
          <p className="text-sm text-slate-400 mt-2">
            {history.length} investigations recorded
          </p>
        </div>
      </div>

      {loading && <p className="text-sm text-slate-500">Loading your research history...</p>}
      {error && (
        <div className="flex items-start gap-3 rounded-xl border border-verdict-contradicted/20 bg-verdict-contradicted/5 p-4 text-sm text-verdict-contradicted">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {!loading && !error && history.length === 0 && (
        <div className="rounded-xl border border-dashed border-ink-700 px-4 py-12 text-center">
          <FileSearch className="mx-auto mb-3 h-5 w-5 text-slate-500" />
          <p className="text-sm text-surface-200">Your research history is empty.</p>
          <Link href="/investigate" className="mt-3 inline-block text-xs font-medium text-accent hover:text-accent-light">
            Start an investigation
          </Link>
        </div>
      )}
      <div className="space-y-3">
        {history.map((inv) => (
          <Link
            key={inv.investigation_id}
            href={`/investigation/${inv.investigation_id}`}
            className="block p-4 sm:p-5 rounded-xl glass-surface hover:bg-ink-800 transition-all duration-200 group"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3 min-w-0">
                <FileSearch className="w-5 h-5 text-accent/70 group-hover:text-accent transition-colors mt-0.5 flex-shrink-0" />
                <div className="min-w-0">
                  <h3 className="text-sm font-medium text-surface-200 group-hover:text-surface-100 transition-colors">
                    {inv.question}
                  </h3>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-2xs text-slate-500">
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {timeAgo(inv.created_at)}
                    </span>
                    <span>{inv.evidence_count} sources</span>
                    <span>{inv.time_taken}</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3 flex-shrink-0 pl-8 sm:pl-0">
                {inv.verdict && (
                  <Badge
                    variant={
                      inv.verdict.verdict === "SUPPORTED"
                        ? "success"
                        : inv.verdict.verdict === "PARTIALLY_SUPPORTED"
                        ? "warning"
                        : inv.verdict.verdict === "CONTRADICTED"
                        ? "error"
                        : "muted"
                    }
                    size="md"
                  >
                    {getVerdictLabel(inv.verdict.verdict)}
                  </Badge>
                )}
                <ArrowRight className="w-4 h-4 text-slate-600 group-hover:text-accent transition-colors" />
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}