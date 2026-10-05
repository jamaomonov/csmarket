import { cn } from "../../lib/cn";

/** The brand mark's outlines: two slanted trade arrows notched around a gem (docs/brand). */
const ARROW_TOP =
  "M6.24 7 L31.24 7 L32.18 3.25 L40.43 10.25 L28.69 17.25 L29.62 13.5 L24.5 13.5 L22.19 11.2 L18.75 13.5 L4.62 13.5 Z";
const ARROW_BOTTOM =
  "M33.76 33 L8.76 33 L7.82 36.75 L-0.43 29.75 L11.31 22.75 L10.38 26.5 L15.5 26.5 L17.81 28.8 L21.25 26.5 L35.38 26.5 Z";
const GEM = "M21.62 13.5 L28.1 20 L18.38 26.5 L11.9 20 Z";

interface LogoMarkProps {
  className?: string;
}

/** The mark alone, in `currentColor` (size and colour from the caller's classes). */
export function LogoMark({ className }: LogoMarkProps) {
  return (
    <svg viewBox="-1.43 -1.43 42.86 42.86" aria-hidden="true" className={className}>
      <path d={ARROW_TOP} fill="currentColor" />
      <path d={ARROW_BOTTOM} fill="currentColor" />
      <path d={GEM} fill="currentColor" />
    </svg>
  );
}

interface LogoProps {
  className?: string;
}

/**
 * The lockup: the green mark and «cs» + green «market», leaning with the arrows (14°) and
 * set tight. Sized by the font size (default 24 px); the caller's link names it.
 */
export function Logo({ className }: LogoProps) {
  return (
    <span className={cn("inline-flex items-center gap-[0.3em] text-[24px] font-bold", className)}>
      <LogoMark className="text-accent size-[1.3em] shrink-0" />
      <span className="inline-block -skew-x-[14deg] tracking-[-0.045em]">
        cs<span className="text-accent">market</span>
      </span>
    </span>
  );
}
