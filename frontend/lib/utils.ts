import { clsx, type ClassValue } from "clsx";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function formatDuration(seconds: number): string {
  if (seconds < 1) return "<1s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}

export function getVerdictColor(verdict: string): string {
  const map: Record<string, string> = {
    SUPPORTED: "text-verdict-supported",
    PARTIALLY_SUPPORTED: "text-verdict-partial",
    CONTRADICTED: "text-verdict-contradicted",
    NOT_SUPPORTED: "text-verdict-contradicted",
    INCONCLUSIVE: "text-verdict-inconclusive",
  };
  return map[verdict] || "text-slate-400";
}

export function getVerdictBg(verdict: string): string {
  const map: Record<string, string> = {
    SUPPORTED: "bg-verdict-supported/10 border-verdict-supported/20",
    PARTIALLY_SUPPORTED: "bg-verdict-partial/10 border-verdict-partial/20",
    CONTRADICTED: "bg-verdict-contradicted/10 border-verdict-contradicted/20",
    NOT_SUPPORTED: "bg-verdict-contradicted/10 border-verdict-contradicted/20",
    INCONCLUSIVE: "bg-slate-500/10 border-slate-500/20",
  };
  return map[verdict] || "bg-slate-500/10 border-slate-500/20";
}

export function getVerdictLabel(verdict: string): string {
  const map: Record<string, string> = {
    SUPPORTED: "Supported",
    PARTIALLY_SUPPORTED: "Partially Supported",
    CONTRADICTED: "Contradicted",
    NOT_SUPPORTED: "Not Supported",
    INCONCLUSIVE: "Inconclusive",
  };
  return map[verdict] || verdict;
}

export function getConfidencePercent(conf: string): number {
  const map: Record<string, number> = {
    HIGH: 85,
    MEDIUM: 60,
    LOW: 35,
  };
  return map[conf] || 50;
}

export function timeAgo(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}