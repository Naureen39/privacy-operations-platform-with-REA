import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

// Every color, radius, shadow and type size comes from src/styles/tokens.css.
const color = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "1rem", screens: { "2xl": "1280px" } },
    extend: {
      colors: {
        background: color("background"),
        foreground: color("foreground"),
        muted: { DEFAULT: color("muted"), foreground: color("muted-foreground") },
        card: { DEFAULT: color("card"), foreground: color("card-foreground") },
        border: color("border"),
        input: color("input"),
        ring: color("ring"),
        navy: { DEFAULT: color("navy"), soft: color("navy-soft") },
        primary: { DEFAULT: color("primary"), hover: color("primary-hover"), foreground: color("primary-foreground") },
        accent: { DEFAULT: color("accent"), foreground: color("accent-foreground") },
        success: color("success"),
        warning: color("warning"),
        danger: color("danger"),
        surface: color("surface"),
      },
      borderRadius: { sm: "var(--radius-sm)", md: "var(--radius-md)", lg: "var(--radius-lg)", xl: "var(--radius-xl)" },
      boxShadow: { card: "var(--shadow-card)", pop: "var(--shadow-pop)", header: "var(--shadow-header)" },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"] },
      fontSize: {
        xs: ["0.75rem", { lineHeight: "1rem" }],
        sm: ["0.875rem", { lineHeight: "1.5rem" }],
        base: ["1rem", { lineHeight: "1.75rem" }],
        lg: ["1.125rem", { lineHeight: "1.75rem" }],
        xl: ["1.25rem", { lineHeight: "2rem" }],
        "2xl": ["1.5rem", { lineHeight: "2rem" }],
        "3xl": ["1.875rem", { lineHeight: "2.5rem" }],
        "4xl": ["2.25rem", { lineHeight: "2.5rem", letterSpacing: "-0.02em" }],
        "5xl": ["3rem", { lineHeight: "3.5rem", letterSpacing: "-0.025em" }],
        "6xl": ["3.75rem", { lineHeight: "4rem", letterSpacing: "-0.03em" }],
      },
      maxWidth: { content: "1280px" },
      keyframes: {
        "fade-up": { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
      },
      animation: {
        "fade-up": "fade-up 0.4s ease-out both",
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [animate],
} satisfies Config;
