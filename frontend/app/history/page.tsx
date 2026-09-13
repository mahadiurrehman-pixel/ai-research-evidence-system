"use client";

import { Badge } from "@/components/ui/Badge";
import { mockHistory } from "@/lib/mock-data";
import { getVerdictLabel, timeAgo } from "@/lib/utils";
import { FileSearch, Clock, ArrowRight, Trash2 } from "lucide-react";
import Link from "next/link";

export default function HistoryPage() {
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
            {mockHistory.length} investigations completed
          </p>
        </div>
      </div>

      <div className="space-y-3">
        {mockHistory.map((inv) => (
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