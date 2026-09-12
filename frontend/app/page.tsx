"use client";

import { ClaimComposer } from "@/components/investigate/ClaimComposer";
import { Badge } from "@/components/ui/Badge";
import { mockHistory } from "@/lib/mock-data";
import {
  getVerdictColor,
  getVerdictLabel,
  timeAgo,
} from "@/lib/utils";
import {
  Activity,
  BookOpen,
  FileSearch,
  Shield,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

const stats = [
  { label: "Investigations", value: "247", icon: FileSearch },
  { label: "Sources Analyzed", value: "4.2K", icon: BookOpen },
  { label: "Avg. Speed", value: "19s", icon: Zap },
  { label: "Accuracy", value: "94%", icon: TrendingUp },
];

export default function DashboardPage() {
  const router = useRouter();

  const handleInvestigate = (question: string) => {
    router.push(`/investigate?q=${encodeURIComponent(question)}`);
  };

  return (
    <div className="min-h-[calc(100vh-3.5rem)] flex flex-col">
      {/* Hero area */}
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-16">
        <div className="text-center mb-10 animate-fade-in">
          <div className="inline-flex items-center gap-2 mb-6">
            <Sparkles className="w-4 h-4 text-accent" />
            <span className="text-xs font-medium text-accent tracking-wide uppercase">
              Evidence Intelligence Platform
            </span>
          </div>

          <h1 className="text-4xl md:text-5xl font-bold tracking-tight text-surface-100 mb-3">
            Verify what's{" "}
            <span className="accent-gradient">actually true</span>
          </h1>

          <p className="text-base text-slate-500 max-w-lg mx-auto leading-relaxed">
            Investigate claims against real research evidence. Get calibrated
            verdicts backed by peer-reviewed sources, meta-analyses, and RCTs.
          </p>
        </div>

        <div className="w-full animate-slide-up" style={{ animationDelay: "0.1s" }}>
          <ClaimComposer onSubmit={handleInvestigate} />
        </div>
      </div>

      {/* Stats bar */}
      <div className="border-t border-ink-700/15 bg-ink-900/40">
        <div className="max-w-[1200px] mx-auto px-6 py-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            {stats.map((stat) => {
              const Icon = stat.icon;
              return (
                <div key={stat.label} className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-ink-800/60 border border-ink-700/20">
                    <Icon className="w-4 h-4 text-accent" />
                  </div>
                  <div>
                    <div className="text-lg font-semibold text-surface-100">
                      {stat.value}
                    </div>
                    <div className="text-2xs text-slate-600">{stat.label}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Recent investigations */}
      <div className="border-t border-ink-700/15 bg-ink-950">
        <div className="max-w-[1200px] mx-auto px-6 py-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-surface-200">
              Recent Investigations
            </h2>
            <Link
              href="/history"
              className="text-xs text-slate-500 hover:text-accent transition-colors"
            >
              View all →
            </Link>
          </div>

          <div className="space-y-2">
            {mockHistory.map((inv) => (
              <Link
                key={inv.investigation_id}
                href={`/investigation/${inv.investigation_id}`}
                className="flex items-center justify-between p-3 rounded-xl hover:bg-ink-800/30 border border-transparent hover:border-ink-700/15 transition-all duration-200 group"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <Shield className="w-4 h-4 text-slate-600 group-hover:text-accent transition-colors flex-shrink-0" />
                  <span className="text-sm text-surface-200 truncate">
                    {inv.question}
                  </span>
                </div>

                <div className="flex items-center gap-3 ml-4 flex-shrink-0">
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