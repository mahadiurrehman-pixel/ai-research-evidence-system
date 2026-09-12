"use client";

import { cn } from "@/lib/utils";

interface ConfidenceMeterProps {
  percent: number;
  size?: number;
}

export function ConfidenceMeter({ percent, size = 64 }: ConfidenceMeterProps) {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (percent / 100) * circumference;

  const color =
    percent >= 70
      ? "text-verdict-supported"
      : percent >= 45
      ? "text-verdict-partial"
      : "text-verdict-contradicted";

  return (
    <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="transform -rotate-90"
      >
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          className="text-ink-700/30"
        />
        {/* Progress circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          className={cn(color, "transition-all duration-1000 ease-out")}
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className={cn("text-sm font-semibold", color)}>{percent}%</span>
      </div>
    </div>
  );
}