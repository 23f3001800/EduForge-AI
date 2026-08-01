"use client";

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/**
 * The button.
 *
 * `min-h-[2.75rem]` on the default size is 44px — the touch-target floor.
 * The `sm` size drops below it deliberately and is only for controls that sit
 * inside a row a finger is not aiming at (a download in a list, a filter chip).
 *
 * `asChild` lets a link render with button styling without nesting an <a> in a
 * <button>, which is invalid and breaks keyboard behaviour in both.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-fg hover:bg-accent/90",
        secondary: "border border-border bg-raised hover:bg-surface",
        ghost: "hover:bg-surface",
        danger: "bg-danger text-white hover:bg-danger/90",
        link: "text-accent underline-offset-4 hover:underline",
      },
      size: {
        default: "min-h-[2.75rem] px-4 py-2",
        sm: "min-h-[2.25rem] px-3 text-xs",
        lg: "min-h-[3rem] px-6 text-base",
        icon: "size-11",
      },
    },
    defaultVariants: { variant: "primary", size: "default" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, loading, children, disabled, ...props }, ref) => {
    if (asChild) {
      // Slot forwards props onto exactly one child, so nothing may be injected
      // beside it. A link rendered as a button is never "loading" anyway —
      // navigation is the browser's job, not this component's.
      return (
        <Slot
          ref={ref}
          className={cn(buttonVariants({ variant, size }), className)}
          {...props}
        >
          {children}
        </Slot>
      );
    }

    return (
      <button
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        // A spinner is a visual cue only; assistive tech needs to be told the
        // control is busy rather than left to infer it from an icon.
        aria-busy={loading || undefined}
        {...props}
      >
        {loading ? <Loader2 className="animate-spin" aria-hidden /> : null}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
