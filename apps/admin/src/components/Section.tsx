/**
 * Detail pages (review §4.8, audit §4): titled sections in a two-column grid, label/value rows,
 * technical fields folded under «Подробнее» (`More`), the page's actions in a bar that stays at
 * the bottom of a phone's screen (`ActionBar`), and empty sections folded into one line.
 */
import { ChevronRight } from "lucide-react";
import { type ReactNode } from "react";

import { useNarrow } from "@/lib/useNarrow";

interface DetailGridProps {
  main: ReactNode;
  side?: ReactNode;
  /** On a phone (one column) the side comes first: a card's profile and risk before history. */
  sideFirst?: boolean;
}

export function DetailGrid({ main, side, sideFirst = false }: DetailGridProps) {
  const narrow = useNarrow();
  const mainCol = <div className="min-w-0 space-y-4">{main}</div>;
  const sideCol =
    side === undefined ? null : (
      <div data-testid="detail-side" className="min-w-0 space-y-4">
        {side}
      </div>
    );
  // One column on a phone: the side goes first in the reading order itself, not only visually.
  return (
    <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
      {sideFirst && narrow ? (
        <>
          {sideCol}
          {mainCol}
        </>
      ) : (
        <>
          {mainCol}
          {sideCol}
        </>
      )}
    </div>
  );
}

interface SectionProps {
  title: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  label?: string;
}

export function Section({ title, actions, children, label }: SectionProps) {
  return (
    <section
      aria-label={label ?? (typeof title === "string" ? title : undefined)}
      className="border-border bg-surface rounded-lg border"
    >
      <div className="border-border flex items-center justify-between gap-2 border-b px-4 py-2.5">
        <h2 className="text-lead font-semibold">{title}</h2>
        {actions}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

/** A label/value row: label 140 px muted, value wraps (one column on phones). */
export function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 py-1 text-sm sm:grid-cols-[140px_1fr] sm:gap-3">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

/**
 * Technical fields (ids to search a market's cabinet by, raw codes) folded under «Подробнее»
 * at the end of a section: an operator opens them when matching logs, not on every visit.
 */
export function More({ children, label = "Подробнее" }: { children: ReactNode; label?: string }) {
  return (
    <details className="border-border group mt-2 border-t pt-2">
      <summary className="text-fg-muted hover:text-fg flex min-h-11 cursor-pointer select-none list-none items-center gap-1 text-sm sm:min-h-0 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-4 transition-transform group-open:rotate-90" aria-hidden />
        {label}
      </summary>
      <dl className="mt-1">{children}</dl>
    </details>
  );
}

/**
 * A page's actions: inline under the header on a wide screen; on a phone a bar pinned to the
 * bottom of the screen above the bottom navigation, its buttons sharing the width.
 */
export function ActionBar({
  children,
  label,
  testId,
}: {
  children: ReactNode;
  label: string;
  testId?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      data-testid={testId}
      className="bg-bg/95 border-border bottom-(--bottom-nav) sticky z-20 -mx-4 flex flex-wrap gap-2 border-t px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none [&>button]:flex-1 sm:[&>button]:flex-none"
    >
      {children}
    </div>
  );
}

/**
 * Sections with nothing in them, folded into one muted line («Пока пусто: Заказы, Продажи»), so
 * a phone reaches the sections that have something without scrolling past empty cards.
 */
export function EmptySections({ names }: { names: string[] }) {
  if (names.length === 0) return null;
  return (
    <p
      data-testid="empty-sections"
      className="border-border text-fg-muted rounded-lg border border-dashed px-4 py-3 text-sm"
    >
      Пока пусто: {names.join(", ")}.
    </p>
  );
}

/** A red banner at the top of a detail page (an open attention, a ban). */
export function Banner({
  children,
  tone = "danger",
}: {
  children: ReactNode;
  tone?: "danger" | "info";
}) {
  return (
    <div
      role="status"
      className={`rounded-lg border px-4 py-3 text-sm ${
        tone === "danger"
          ? "border-danger/40 bg-danger/10 text-danger"
          : "border-info/40 bg-info/10 text-info"
      }`}
    >
      {children}
    </div>
  );
}
