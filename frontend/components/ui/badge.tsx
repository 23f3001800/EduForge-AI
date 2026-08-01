import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/**
 * A status chip.
 *
 * Colour is never the only signal — every badge renders its label as text, so
 * severity survives greyscale, colour blindness, and a printed page.
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "border-border bg-surface text-fg-muted",
        accent: "border-accent/25 bg-accent-subtle text-accent",
        grounded: "border-grounded/25 bg-grounded-subtle text-grounded",
        success: "border-success/25 bg-success-subtle text-success",
        warning: "border-warning/25 bg-warning-subtle text-warning",
        danger: "border-danger/25 bg-danger-subtle text-danger",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
