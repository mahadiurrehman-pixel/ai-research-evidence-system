export function Logo({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <div className="relative w-7 h-7">
        <div className="absolute inset-0 rounded-lg bg-accent/15 rotate-45" />
        <div className="absolute inset-1 rounded-md bg-accent rotate-45 shadow-sm" />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-[10px] font-bold text-white rotate-0">
            RC
          </span>
        </div>
      </div>
      <div className="flex flex-col -space-y-0.5">
        <span className="text-sm font-semibold text-surface-100 tracking-tight">
          Reality Checker
        </span>
        <span className="text-2xs text-slate-500 tracking-[0.16em] uppercase">
          Research workspace
        </span>
      </div>
    </div>
  );
}