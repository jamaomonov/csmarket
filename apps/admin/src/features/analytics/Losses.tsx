/** «Продано в минус»: delivered orders sold below what the market charged (normally none). */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { type Channel, getLosses } from "./api";
import { lossesKey } from "./keys";
import { labelOf, som, SOURCE_LABELS } from "./labels";
import { type Span } from "./period";

import { Section } from "@/components/Section";
import { formatDateTime } from "@/lib/format";

export function Losses({ span, channel }: { span: Span; channel: Channel }) {
  const q = useQuery({
    queryKey: lossesKey(span.since, span.until, channel),
    queryFn: () => getLosses(span.since, span.until, channel),
  });
  const items = q.data?.items ?? [];
  return (
    <Section title="Продано в минус">
      {q.isPending ? (
        <p className="text-fg-muted text-sm">Загрузка…</p>
      ) : q.isError ? (
        <p role="alert" className="text-danger text-sm">
          Не удалось загрузить — обновите страницу.
        </p>
      ) : items.length === 0 ? (
        <p className="text-fg-muted text-sm">Нет — так и должно быть.</p>
      ) : (
        <ul className="divide-border divide-y text-sm">
          {items.map((l) => (
            <li key={l.number} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 py-1.5">
              <Link to={`/orders/${l.number}`} className="font-mono hover:underline">
                {l.number}
              </Link>
              <span className="min-w-0 flex-1 truncate">{l.name}</span>
              <span className="text-fg-muted">{labelOf(SOURCE_LABELS, l.source)}</span>
              <span className="text-fg-muted text-xs">{formatDateTime(l.paid_at)}</span>
              <span className="text-danger w-28 text-right tabular-nums">{som(l.profit_uzs)}</span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
