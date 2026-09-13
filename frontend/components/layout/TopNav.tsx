"use client";

import { Logo } from "@/components/icons/Logo";
import { Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useState } from "react";

const navItems = [
  { href: "/", label: "Dashboard" },
  { href: "/investigate", label: "Investigate" },
  { href: "/history", label: "History" },
];

export function TopNav() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="fixed top-0 left-0 right-0 z-50 min-h-16 glass border-b border-ink-700/70">
      <div className="min-h-16 max-w-[1600px] mx-auto px-4 sm:px-6 flex items-center justify-between gap-4">
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
                  "px-3 py-2 rounded-lg text-sm transition-all duration-200",
                  pathname === item.href
                    ? "text-accent-dark bg-accent/10"
                    : "text-slate-400 hover:text-surface-100 hover:bg-ink-800/70"
                )}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <button
            aria-label={menuOpen ? "Close navigation" : "Open navigation"}
            onClick={() => setMenuOpen(!menuOpen)}
            className="md:hidden p-2 rounded-lg text-slate-400 hover:text-surface-100 hover:bg-ink-800/70 transition-colors"
          >
            {menuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>
      {menuOpen && (
        <nav className="md:hidden border-t border-ink-700/70 bg-ink-900 px-4 py-3 space-y-1">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setMenuOpen(false)}
              className={cn(
                "block px-3 py-2.5 rounded-lg text-sm",
                pathname === item.href ? "text-accent-dark bg-accent/10" : "text-slate-400 hover:bg-ink-800/70"
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}