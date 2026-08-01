import { AlertTriangle, Inbox, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Button } from "./button";

/**
 * Empty and error states.
 *
 * Both take an action, because a state that tells someone they are stuck
 * without telling them what to do next is only half a design. The error variant
 * shows a trace id when there is one — it is how a reported failure gets found
 * in the structured logs, and asking a user to reproduce it is worse than
 * asking them to quote twelve characters.
 */

export function EmptyState({
  icon: Icon = Inbox,
  title,
  children,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
    >
      <Icon className="size-8 text-fg-faint" aria-hidden />
      <p className="font-medium">{title}</p>
      {children ? <div className="max-w-md text-sm text-fg-muted">{children}</div> : null}
      {action}
    </div>
  );
}

export function ErrorState({
  title,
  children,
  traceId,
  onRetry,
  retryLabel = "Try again",
  className,
}: {
  title: string;
  children?: ReactNode;
  traceId?: string;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn("rounded-lg border border-danger/30 bg-danger-subtle p-5", className)}
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-fg">{title}</p>
          {children ? <div className="mt-1 text-sm text-fg-muted">{children}</div> : null}
          {traceId ? (
            <p className="mt-2 font-mono text-xs text-fg-faint">
              Reference: {traceId}
            </p>
          ) : null}
          {onRetry ? (
            <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
              {retryLabel}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
