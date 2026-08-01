import { cn } from "@/lib/cn";

/**
 * A loading placeholder.
 *
 * Sized to the content it stands in for, not a generic grey box — a skeleton
 * whose shape does not match what arrives causes a layout jump, which is the
 * thing skeletons exist to prevent.
 */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden />;
}
