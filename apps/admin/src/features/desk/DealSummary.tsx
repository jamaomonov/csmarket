/**
 * What the deal is, under its header: the price (soʻm and dollars at the deal's rate), what
 * Skinslink gives for the skins, the profit so far and expected, the note, the trade link and
 * the guarantor; «Изменить» and the trader's other deals.
 */
import { Button } from "@csmarket/ui";
import { type ReactNode } from "react";
import { Link } from "react-router-dom";

import { type Deal, type DealPatch } from "./api";
import { TAP } from "./Parts";
import { PriceEditor } from "./PriceEditor";

import { CopyButton } from "@/components/CopyButton";
import { Money } from "@/components/Money";
import { Row } from "@/components/Section";
import { When } from "@/components/When";

interface DealSummaryProps {
  deal: Deal;
  onSavePrice: (body: DealPatch) => Promise<unknown>;
  onEdit: () => void;
  /** «Подтвердить гаранту»; `null` hides the button. */
  onRelease: (() => void) | null;
  busy: boolean;
}

/** The deal's skins at Skinslink's prices; `null` when none is priced. */
export function skinslinkValue(d: Deal): number | null {
  const priced = d.items.filter((i) => i.skinslink_usd !== null);
  if (priced.length === 0) return null;
  return priced.reduce((s, i) => s + Number(i.skinslink_usd), 0);
}

function Profit({ d }: { d: Deal }) {
  const value = skinslinkValue(d);
  const booked = d.resolved || Number(d.profit_usd) !== 0;
  const expected =
    !d.resolved && value !== null && d.paid_usd !== null ? value - Number(d.paid_usd) : null;
  const parts: ReactNode[] = [];
  if (booked) {
    parts.push(
      <span key="b">
        <Money usd={d.profit_usd} signed /> {d.resolved ? "итог" : "пока"}
      </span>,
    );
  }
  if (expected !== null) {
    parts.push(
      <span key="e" className={booked ? "text-fg-muted" : ""}>
        ≈ <Money usd={expected.toFixed(2)} signed /> по ценам Skinslink
      </span>,
    );
  }
  if (parts.length === 0) return <span className="text-fg-muted">—</span>;
  return <span className="flex flex-col">{parts}</span>;
}

export function DealSummary({ deal: d, onSavePrice, onEdit, onRelease, busy }: DealSummaryProps) {
  const value = skinslinkValue(d);
  const traderDeals = `/desk?${new URLSearchParams({ q: d.trader }).toString()}`;
  return (
    <section
      aria-label="Сделка"
      className="border-border bg-surface space-y-2 rounded-lg border p-3"
    >
      <PriceEditor deal={d} onSave={onSavePrice} />
      <dl>
        <Row label="Skinslink даёт">{value !== null ? <Money usd={value.toFixed(2)} /> : "—"}</Row>
        <Row label="Прибыль">
          <Profit d={d} />
        </Row>
        {d.note && <Row label="Заметка">{d.note}</Row>}
        <Row label="Трейд-ссылка">
          {d.trade_link ? (
            <span className="flex min-w-0 items-center">
              <span className="truncate">{d.trade_link}</span>
              <CopyButton value={d.trade_link} label="Копировать трейд-ссылку" />
            </span>
          ) : (
            <span className="text-fg-muted">нет</span>
          )}
        </Row>
        {d.method === "guarantor" && (
          <Row label="Гарант">
            <span className="flex flex-wrap items-center gap-2">
              <span>{d.guarantor ?? <span className="text-fg-muted">не указан</span>}</span>
              {d.guarantor_released_at && (
                <span className="text-fg-muted">
                  · подтверждено <When iso={d.guarantor_released_at} />
                </span>
              )}
              {onRelease && (
                <Button variant="secondary" className={TAP} disabled={busy} onClick={onRelease}>
                  Подтвердить гаранту
                </Button>
              )}
            </span>
          </Row>
        )}
      </dl>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="secondary" className={TAP} onClick={onEdit}>
          Изменить
        </Button>
        <Link
          to={traderDeals}
          className="text-accent inline-flex min-h-11 items-center text-sm underline"
        >
          Все сделки с трейдером
        </Link>
      </div>
    </section>
  );
}
