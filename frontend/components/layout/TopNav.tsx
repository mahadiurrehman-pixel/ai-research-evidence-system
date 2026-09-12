"use client";

import { Logo } from "@/components/icons/Logo";
import { Badge } from "@/components/ui/Badge";
import {
  Settings,
  Bell,
  Search,
  ChevronDown,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard" },
  { href: "/investigate", label: "Investigate" },
  { href: "/history", label: "History" },
];

export function TopNav() {
  const pathname = usePathname();

  return (
    <header className="fixed top-0 left-0 right-0 z-50 h-14 glass border-b border-ink-700/15">
      <div className="h-full max-w-[1600px] mx-auto px-6 flex items-center justify-between">
        {/* Left */}
        <div className="flex items-center gap-8">
          <Link href="/">
            <Logo />
          </Link>

          <nav className="hidden md:flex items-center gap-1">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "px-3 py-1.5 rounded-lg text-sm transition-all duration-200",
                  pathname === item.href
                    ? "text-surface-100 bg-ink-800/60"
                    : "text-slate-500 hover:text-surface-200 hover:bg-ink-800/30"
                )}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>

        {/* Right */}
        <div className="flex items-center gap-3">
          <Badge variant="accent" size="sm">
            <span className="w-1.5 h-1.5 rounded-full bg-accent mr-1.5 animate-pulse-slow" />
            System Online
          </Badge>

          <button className="p-2 rounded-lg text-slate-500 hover:text-surface-200 hover:bg-ink-800/40 transition-colors">
            <Search className="w-4 h-4" />
          </button>

          <button className="p-2 rounded-lg text-slate-500 hover:text-surface-200 hover:bg-ink-800/40 transition-colors">
            <Bell className="w-4 h-4" />
          </button>

          <button className="p-2 rounded-lg text-slate-500 hover:text-surface-200 hover:bg-ink-800/40 transition-colors">
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
}