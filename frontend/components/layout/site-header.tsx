"use client";

import { BarChart3, FileStack, Menu, Moon, Sun, Upload, X } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/upload", label: "New package", icon: Upload },
  { href: "/samples", label: "Samples", icon: FileStack },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // The server-rendered markup cannot know the user's theme, so rendering the
  // real icon before hydration guarantees a mismatch. A fixed-size placeholder
  // keeps the header from shifting when the real control appears.
  useEffect(() => setMounted(true), []);
  if (!mounted) return <div className="size-11" aria-hidden />;

  const dark = resolvedTheme === "dark";
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(dark ? "light" : "dark")}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
    >
      {dark ? <Sun /> : <Moon />}
    </Button>
  );
}

export function SiteHeader() {
  const pathname = usePathname() ?? "/";
  const [open, setOpen] = useState(false);

  // A route change must close the mobile sheet; leaving it open over the new
  // page is the classic hand-rolled-nav bug.
  useEffect(() => setOpen(false), [pathname]);

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-bg/80 backdrop-blur">
      <div className="container flex min-h-16 flex-wrap items-center gap-3 py-2">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <span className="grid size-7 place-items-center rounded-md bg-accent text-accent-fg text-xs font-bold">
            EF
          </span>
          <span>
            EduForge <span className="text-accent">AI</span>
          </span>
        </Link>

        <nav className="ml-auto hidden items-center gap-1 md:flex" aria-label="Primary">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={pathname.startsWith(href) ? "page" : undefined}
              className={cn(
                "inline-flex min-h-11 items-center gap-2 rounded-md px-3 text-sm font-medium transition-colors",
                pathname.startsWith(href)
                  ? "bg-accent-subtle text-accent"
                  : "text-fg-muted hover:bg-surface hover:text-fg",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1 md:ml-0">
          <ThemeToggle />
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls="mobile-nav"
            aria-label={open ? "Close menu" : "Open menu"}
          >
            {open ? <X /> : <Menu />}
          </Button>
        </div>
      </div>

      {open ? (
        <nav
          id="mobile-nav"
          aria-label="Primary"
          className="container flex flex-col gap-1 border-t border-border py-2 md:hidden"
        >
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={pathname.startsWith(href) ? "page" : undefined}
              className={cn(
                "inline-flex min-h-11 items-center gap-2 rounded-md px-3 text-sm font-medium",
                pathname.startsWith(href)
                  ? "bg-accent-subtle text-accent"
                  : "text-fg-muted hover:bg-surface",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          ))}
        </nav>
      ) : null}
    </header>
  );
}
