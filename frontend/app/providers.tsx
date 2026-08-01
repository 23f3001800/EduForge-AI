"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";
import { ApiError } from "@/lib/api";

/**
 * Client-side providers.
 *
 * The QueryClient is created inside state rather than at module scope so a
 * remount gets a fresh cache instead of one shared across every instance the
 * page ever had.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Job state changes on the server while nobody is looking, so a
            // long stale time would show a finished run as still running.
            staleTime: 10_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              // Retrying a 4xx just repeats a request the server already
              // refused for a reason the client controls.
              if (error instanceof ApiError && error.status < 500) return false;
              return failureCount < 2;
            },
          },
        },
      }),
  );

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={client}>
        {children}
        <Toaster
          position="bottom-right"
          // Inherit the app's palette rather than shipping a second one.
          toastOptions={{
            classNames: {
              toast: "bg-raised border border-border text-fg",
              description: "text-fg-muted",
            },
          }}
        />
      </QueryClientProvider>
    </ThemeProvider>
  );
}
