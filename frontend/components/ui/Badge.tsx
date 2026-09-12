import { cn } from "@/lib/utils";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "accent" | "success" | "warning" | "error" | "muted";
  size?: "sm" | "md";
  className?: string;
}

const variants = {
  default: "bg-ink-700/40 text-surface-200 border-ink-600/30",
  accent: "bg-accent/10 text-accent border-accent/20",
  success: "bg-verdict-supported/10 text-verdict-supported border-verdict-supported/20",
  warning: "bg-verdict-partial/10 text-verdict-partial border-verdict-partial/20",
  error: "bg-verdict-contradicted/10 text-verdict-contradicted border-verdict-contradicted/20",
  muted: "bg-ink-800/40 text-slate-400 border-ink-700/20",
};

export function Badge({
  children,
  variant = "default",
  size = "sm",
  className,
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center border rounded-full font-medium",
        size === "sm" ? "px-2 py-0.5 text-2xs" : "px-2.5 py-1 text-xs",
        variants[variant],
        className
      )}
    >
      {children}
    </span>
  );
}