"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import {
  Search,
  Zap,
  ArrowRight,
  Command,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface ClaimComposerProps {
  onSubmit: (question: string) => void;
  loading?: boolean;
}

export function ClaimComposer({ onSubmit, loading }: ClaimComposerProps) {
  const [query, setQuery] = useState("");

  const handleSubmit = () => {
    if (query.trim() && !loading) {
      onSubmit(query.trim());
    }
  };

  return (
    <div className="w-full max-w-3xl mx-auto">
      {/* Input area */}
      <div className="relative group">
        <div
          className={cn(
            "relative rounded-2xl border transition-all duration-300",
            "bg-ink-850/95 shadow-card",
            query
              ? "border-accent/30 shadow-glow"
              : "border-ink-700/20 hover:border-ink-600/30"
          )}
        >
          <div className="flex items-start p-4 sm:p-5">
            <Search
              className={cn(
                "w-5 h-5 mt-0.5 mr-3 flex-shrink-0 transition-colors",
                query ? "text-accent" : "text-slate-500"
              )}
            />

            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              placeholder="Investigate a claim, compare evidence, or verify a statement…"
              rows={2}
              className="flex-1 min-w-0 bg-transparent text-surface-100 placeholder:text-slate-500 text-sm leading-relaxed resize-none focus:outline-none"
            />
          </div>

          {/* Bottom bar */}
          <div className="flex items-center justify-between gap-3 px-4 sm:px-5 pb-4">
            <div className="hidden sm:flex items-center gap-2 text-2xs text-slate-500">
              <kbd className="px-1.5 py-0.5 rounded bg-ink-800 border border-ink-700/30 font-mono">
                <Command className="w-2.5 h-2.5 inline" />
              </kbd>
              <kbd className="px-1.5 py-0.5 rounded bg-ink-800 border border-ink-700/30 font-mono">
                ↵
              </kbd>
              <span>to investigate</span>
            </div>

            <Button
              onClick={handleSubmit}
              disabled={!query.trim()}
              loading={loading}
              size="sm"
              className="gap-1.5"
            >
              <Zap className="w-3.5 h-3.5" />
              Investigate
              <ArrowRight className="w-3 h-3" />
            </Button>
          </div>
        </div>
      </div>

      <p className="mt-4 text-center text-xs text-slate-500">
        Ask a specific, evidence-based question. Research may take up to a few minutes.
      </p>
    </div>
  );
}