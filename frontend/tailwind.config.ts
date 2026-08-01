import type { Config } from "tailwindcss";

/**
 * The design system, expressed as Tailwind theme extensions.
 *
 * Colours are CSS custom properties rather than literal hex values, defined
 * once in `app/globals.css` for light and dark. That is what makes the theme
 * switch a class on <html> instead of a second set of utilities on every
 * element — and it keeps one source of truth for a palette whose contrast
 * ratios were checked (docs/14-design-system.md §4).
 *
 * The scale is deliberately small. A type ramp with eleven sizes and a spacing
 * scale with twenty steps is how a UI drifts into looking unfinished: every
 * screen picks slightly different values and nothing lines up.
 */
const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: { DEFAULT: "1rem", md: "1.5rem", lg: "2rem" },
      screens: { "2xl": "1280px" },
    },
    extend: {
      colors: {
        bg: "hsl(var(--bg))",
        surface: "hsl(var(--surface))",
        raised: "hsl(var(--raised))",
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        fg: {
          DEFAULT: "hsl(var(--fg))",
          muted: "hsl(var(--fg-muted))",
          faint: "hsl(var(--fg-faint))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          fg: "hsl(var(--accent-fg))",
          subtle: "hsl(var(--accent-subtle))",
        },
        // Reserved for evidence and citations — the product's central claim
        // gets one recognisable colour everywhere it appears.
        grounded: {
          DEFAULT: "hsl(var(--grounded))",
          subtle: "hsl(var(--grounded-subtle))",
        },
        success: { DEFAULT: "hsl(var(--success))", subtle: "hsl(var(--success-subtle))" },
        warning: { DEFAULT: "hsl(var(--warning))", subtle: "hsl(var(--warning-subtle))" },
        danger: { DEFAULT: "hsl(var(--danger))", subtle: "hsl(var(--danger-subtle))" },
      },
      borderRadius: {
        lg: "0.75rem",
        md: "0.5rem",
        sm: "0.375rem",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 160ms ease-out",
        "slide-up": "slide-up 200ms cubic-bezier(0.16, 1, 0.3, 1)",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
