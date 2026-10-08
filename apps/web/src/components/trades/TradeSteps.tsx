import { cn } from "@csmarket/ui";
import { Check } from "lucide-react";

export interface TradeStep {
  label: string;
  /** When it happened, or what to expect («7 дней», «15 окт.»). */
  note?: string | null;
  state: "done" | "now" | "todo";
}

/** A trade's way as three steps on a line: done (green tick), now (ring), still to come. */
export function TradeSteps({ steps }: { steps: TradeStep[] }) {
  return (
    <ol className="grid grid-flow-col gap-0" style={{ gridAutoColumns: "minmax(0, 1fr)" }}>
      {steps.map((s, i) => (
        <li key={s.label} data-state={s.state} className="relative pr-3 pt-8">
          {i < steps.length - 1 ? (
            <span
              aria-hidden
              className={cn(
                "absolute left-2.5 right-0 top-2.5 h-0.5",
                s.state === "done" ? "bg-accent" : "bg-border-strong",
              )}
            />
          ) : null}
          <span
            aria-hidden
            className={cn(
              "absolute left-0 top-0 flex size-5 items-center justify-center rounded-full border-2",
              s.state === "done" && "border-accent bg-accent text-accent-fg",
              s.state === "now" && "border-accent bg-bg ring-accent/15 ring-4",
              s.state === "todo" && "border-border-strong bg-surface-2",
            )}
          >
            {s.state === "done" ? <Check className="size-3" strokeWidth={3.5} /> : null}
          </span>
          <span className={cn("block font-semibold", s.state === "todo" && "text-fg-dim")}>
            {s.label}
          </span>
          {s.note ? <span className="text-fg-dim block text-[13px]">{s.note}</span> : null}
        </li>
      ))}
    </ol>
  );
}
