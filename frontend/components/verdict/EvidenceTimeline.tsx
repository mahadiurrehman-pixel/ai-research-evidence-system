"use client";

import { cn } from "@/lib/utils";
import type { PipelineStage } from "@/lib/types";
import { Check, Loader2, Circle, AlertCircle } from "lucide-react";
import { formatDuration } from "@/lib/utils";

interface EvidenceTimelineProps {
  stages: PipelineStage[];
}

const statusIcons = {
  complete: Check,
  active: Loader2,
  pending: Circle,
  error: AlertCircle,
};

export function EvidenceTimeline({ stages }: EvidenceTimelineProps) {
  return (
    <div className="space-y-0">
      {stages.map((stage, idx) => {
        const Icon = statusIcons[stage.status];
        const isLast = idx === stages.length - 1;

        return (
          <div key={stage.id} className="flex gap-3">
            {/* Timeline line + dot */}
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  "w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 border",
                  stage.status === "complete" &&
                    "bg-accent/10 border-accent/30 text-accent",
                  stage.status === "active" &&
                    "bg-accent/20 border-accent/40 text-accent animate-pulse",
                  stage.status === "pending" &&
                    "bg-ink-800 border-ink-700/30 text-slate-600",
                  stage.status === "error" &&
                    "bg-verdict-contradicted/10 border-verdict-contradicted/30 text-verdict-contradicted"
                )}
              >
                <Icon
                  className={cn(
                    "w-3 h-3",
                    stage.status === "active" && "animate-spin"
                  )}
                />
              </div>
              {!isLast && (
                <div
                  className={cn(
                    "w-px flex-1 min-h-[24px]",
                    stage.status === "complete" ? "bg-accent/20" : "bg-ink-700/20"
                  )}
                />
              )}
            </div>

            {/* Content */}
            <div className={cn("pb-4", isLast && "pb-0")}>
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "text-sm font-medium",
                    stage.status === "complete"
                      ? "text-surface-200"
                      : stage.status === "active"
                      ? "text-accent"
                      : "text-slate-600"
                  )}
                >
                  {stage.label}
                </span>
                {stage.duration !== undefined && stage.duration > 0 && (
                  <span className="text-2xs text-slate-600 font-mono">
                    {formatDuration(stage.duration)}
                  </span>
                )}
              </div>
              {stage.detail && (
                <p className="text-xs text-slate-500 mt-0.5">{stage.detail}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}