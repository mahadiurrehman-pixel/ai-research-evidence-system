"use client";

import { ClaimComposer } from "@/components/investigate/ClaimComposer";
import { Badge } from "@/components/ui/Badge";
import { getHistory } from "@/lib/api";
import type { Investigation } from "@/lib/types";
import {
  getVerdictLabel,
  timeAgo,
} from "@/lib/utils";
import { FileSearch, Shield } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export default function DashboardPage() {
  const router = useRouter();
  const [history, setHistory] = useState<Investigation[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);

  useEffect(() => {
    getHistory()
      .then(setHistory)
      .catch((err) => setHistoryError(err instanceof Error ? err.message : "Unable to load history."))
      .finally(() => setHistoryLoading(false));
  }, []);

  const handleInvestigate = (question: string) => {
    router.push(`/investigate?q=${encodeURIComponent(question)}`);
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] flex flex-col">
      {/* Hero area */}
      <div className="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 py-14 sm:py-20">
        <div className="w-full max-w-4xl text-center mb-10 animate-fade-in">
          <div className="inline-flex items-center gap-2 mb-5 px-3 py-1.5 rounded-full border border-accent/20 bg-accent/5">
            <span className="w-1.5 h-1.5 rounded-full bg-accent" />
            <span className="text-xs font-medium text-accent-dark tracking-wide">
              Research, made legible
            </span>
          </div>

          <h1 className="font-display text-4xl sm:text-5xl md:text-6xl font-semibold tracking-tight text-surface-100 mb-5 leading-[1.05]">
            Turn difficult claims into{" "}
            <span className="accent-gradient">clear evidence.</span>
          </h1>

          <p className="text-base sm:text-lg text-slate-400 max-w-2xl mx-auto leading-relaxed">
            Investigate claims against peer-reviewed research, compare what the evidence says, and leave with a verdict you can explain.
          </p>
        </div>

        <div className="w-full animate-slide-up" style={{ animationDelay: "0.1s" }}>
          <ClaimComposer onSubmit={handleInvestigate} />
        </div>
      </div>

      {/* Recent investigations */}
      <div className="border-t border-ink-700/15 bg-ink-950">
        <div className="max-w-[1200px] mx-auto px-4 sm:px-6 py-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-surface-200">Recent investigations</h2>
            <Link
              href="/history"
              className="text-xs text-slate-500 hover:text-accent transition-colors"
            >
              View all →
            </Link>
          </div>

          {historyLoading && <p className="text-sm text-slate-500">Loading your research history...</p>}
          {historyError && <p className="text-sm text-verdict-contradicted">{historyError}</p>}
          {!historyLoading && !historyError && history.length === 0 && (
            <div className="rounded-xl border border-dashed border-ink-700 px-4 py-8 text-center">
              <FileSearch className="mx-auto mb-3 h-5 w-5 text-slate-500" />
              <p className="text-sm text-surface-200">No investigations yet.</p>
              <p className="mt-1 text-xs text-slate-500">Start with a claim above to build your research trail.</p>
            </div>
          )}
          <div className="space-y-2">
            {history.slice(0, 5).map((inv) => (
              <Link
                key={inv.investigation_id}
                href={`/investigation/${inv.investigation_id}`}
                className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 p-3 rounded-xl hover:bg-ink-800/70 border border-transparent hover:border-ink-700 transition-all duration-200 group"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <Shield className="w-4 h-4 text-slate-600 group-hover:text-accent transition-colors flex-shrink-0" />
                  <span className="text-sm text-surface-200 truncate">
                    {inv.question}
                  </span>
                </div>

                <div className="flex items-center gap-3 sm:ml-4 pl-7 sm:pl-0 flex-shrink-0">
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
                    >
                      {getVerdictLabel(inv.verdict.verdict)}
                    </Badge>
                  )}
                  <span className="text-2xs text-slate-600">
                    {timeAgo(inv.created_at)}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}