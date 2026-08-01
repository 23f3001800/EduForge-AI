import type { Metadata } from "next";
import type { ReactNode } from "react";
import { SiteHeader } from "@/components/layout/site-header";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "EduForge AI — chapter in, classroom package out",
    template: "%s · EduForge AI",
  },
  description:
    "Turn a chapter into a multi-period lesson plan, teacher scripts, activities, an " +
    "assessment bank with answer keys, and a learning-gap analysis — with a citation on " +
    "every factual claim.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // suppressHydrationWarning: next-themes sets the class on <html> before
    // React hydrates, which is deliberate (it avoids a flash of the wrong
    // theme) and would otherwise be reported as a mismatch.
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-accent focus:px-4 focus:py-2 focus:text-accent-fg"
          >
            Skip to main content
          </a>
          <div className="flex min-h-dvh flex-col">
            <SiteHeader />
            <main id="main" className="container flex-1 py-8">
              {children}
            </main>
            <footer className="border-t border-border py-6">
              <div className="container flex flex-col gap-2 text-xs text-fg-faint sm:flex-row sm:items-center sm:justify-between">
                <p>EduForge AI — a document becomes a classroom-ready teaching package.</p>
                <p className="flex gap-4">
                  <a className="hover:text-fg" href="/api/v1/docs">
                    API
                  </a>
                  <a className="hover:text-fg" href="/healthz">
                    Health
                  </a>
                </p>
              </div>
            </footer>
          </div>
        </Providers>
      </body>
    </html>
  );
}
