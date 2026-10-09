/** One line of the «Обмены» table and its expandable details. */
import { ChevronDown } from "lucide-react";
import { type MouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { type AdminTradeRow } from "./api";
import { SOURCE_LABELS, STATE_CHIP, STATE_LABELS } from "./labels";
import { ago, clockTime, shortDate, shortDateTime, timeLeft } from "./time";
import { TradeExpand } from "./TradeExpand";
import { ATTENTION_LABELS, FAILURE_LABELS } from "../orders/labels";
import { AttentionBadge } from "../orders/StatusChip";

import { providerLabel } from "@/features/users/labels";
import { formatSum } from "@/lib/format";

/** Columns of the table, the chevron's included (the details row spans them all). */
export const COLUMNS = 9;

/** `"13.580000"` → `$13.58`, `"-1.200000"` → `−$1.20` (display only: the digits are cut). */
export function dollars(value: string): string {
  const negative = value.startsWith("-");
  const [whole = "0", cents = ""] = value.replace(/^[+-]/, "").split(".");
  return `${negative ? "−" : ""}$${whole}.${cents.padEnd(2, "0").slice(0, 2)}`;
}

/** What the buyer was debited, in their currency: the USD wallet of an API order, else soʻm. */
function charged(row: AdminTradeRow): string {
  return row.channel === "api" ? dollars(row.price_usd) : formatSum(row.price_uzs);
}

function priceTitle(row: AdminTradeRow): string {
  const pct = row.margin_pct === null ? "" : ` (${row.margin_pct}%)`;
  return [
    `Цена на витрине: ${formatSum(row.price_uzs)}`,
    `Списано: ${charged(row)}`,
    `Заплатили площадке: ${dollars(row.cost_usd)}`,
    `Прибыль: ${dollars(row.margin_usd)}${pct}`,
  ].join("\n");
}

export function SkinCell({ row }: { row: AdminTradeRow }) {
  const { item } = row;
  return (
    <div className="flex min-w-56 items-center gap-2">
      <span
        aria-hidden
        className="bg-border h-10 w-1 shrink-0 rounded"
        style={item.rarity_color === null ? undefined : { backgroundColor: item.rarity_color }}
      />
      {item.image_url !== null && (
        <img src={item.image_url} alt="" className="size-10 shrink-0 object-contain" />
      )}
      <div className="min-w-0">
        <p className="line-clamp-2 max-w-60 leading-tight" title={item.name}>
          {item.name}
        </p>
        <p className="text-fg-muted text-xs tabular-nums">
          {[item.phase, item.float_value === null ? null : `float ${item.float_value}`]
            .filter((x) => x !== null)
            .join(" · ")}
        </p>
      </div>
    </div>
  );
}

export function StateCell({ row }: { row: AdminTradeRow }) {
  const reason =
    row.trade_state === "refunded" && row.failure_reason !== null
      ? ` · ${FAILURE_LABELS[row.failure_reason]}`
      : "";
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1">
        <span
          data-testid="trade-state"
          title={row.source_status === null ? undefined : `Площадка: ${row.source_status}`}
          className={`whitespace-nowrap rounded px-2 py-0.5 text-xs ${STATE_CHIP[row.trade_state]}`}
        >
          {STATE_LABELS[row.trade_state]}
          {reason}
        </span>
        <AttentionBadge reason={row.attention_reason} />
      </div>
      {row.attention_reason !== null && (
        <p className="text-danger whitespace-nowrap text-xs">
          {ATTENTION_LABELS[row.attention_reason]}
        </p>
      )}
      {row.trade_state === "hold" && row.protected_until !== null && (
        <p data-testid="hold-left" className="text-fg-muted whitespace-nowrap text-xs">
          {timeLeft(row.protected_until)} · {shortDate(row.protected_until)}
        </p>
      )}
    </div>
  );
}

interface TradeLineProps {
  row: AdminTradeRow;
  open: boolean;
  onToggle: () => void;
}

export function TradeLine({ row, open, onToggle }: TradeLineProps) {
  const navigate = useNavigate();
  const attention = row.attention_reason !== null;
  const openOrder = (e: MouseEvent<HTMLTableRowElement>) => {
    // A link or button inside the row does its own thing.
    if (e.target instanceof Element && e.target.closest("a,button") !== null) return;
    void navigate(`/orders/${row.number}`);
  };
  return (
    <>
      <tr
        onClick={openOrder}
        className="border-border hover:bg-surface-hover cursor-pointer border-t align-top"
        {...(attention && { "data-attention": "true" })}
      >
        <td
          className={`py-2 pl-3 pr-3 ${
            attention ? "shadow-[inset_3px_0_0_var(--color-danger)]" : ""
          }`}
        >
          <Link to={`/orders/${row.number}`} className="font-mono font-medium hover:underline">
            {row.number}
          </Link>
          <p className="text-fg-muted whitespace-nowrap text-xs">{shortDateTime(row.created_at)}</p>
        </td>
        <td className="py-2 pr-3">
          <SkinCell row={row} />
        </td>
        <td className="py-2 pr-3">
          <span className="bg-surface-2 whitespace-nowrap rounded px-2 py-0.5 text-xs">
            {SOURCE_LABELS[row.source]}
          </span>
          {row.channel === "api" && (
            <p className="text-fg-muted mt-1 whitespace-nowrap text-xs">
              API · {row.api_owner ?? "без имени"}
            </p>
          )}
        </td>
        <td className="whitespace-nowrap py-2 pr-3 tabular-nums" title={priceTitle(row)}>
          <p data-testid="trade-price">
            {formatSum(row.price_uzs)} · {dollars(row.price_usd)}
          </p>
          <p className="text-fg-muted text-xs">себест. {dollars(row.cost_usd)}</p>
        </td>
        <td className="whitespace-nowrap py-2 pr-3">
          {row.offer_url === null ? (
            "—"
          ) : (
            <a
              href={row.offer_url}
              target="_blank"
              rel="noreferrer"
              className="font-mono hover:underline"
            >
              {row.steam_offer_id}
            </a>
          )}
        </td>
        <td className="py-2 pr-3">
          <div className="flex items-center gap-2">
            {row.buyer.avatar_url !== null && (
              <img src={row.buyer.avatar_url} alt="" className="size-6 rounded-full" />
            )}
            <Link to={`/users/${row.buyer.id}`} className="whitespace-nowrap hover:underline">
              {row.buyer.display_name ?? "Без имени"}
            </Link>
          </div>
          <p className="text-fg-muted text-xs">{providerLabel(row.paid_with)}</p>
        </td>
        <td className="py-2 pr-3">
          <StateCell row={row} />
        </td>
        <td className="whitespace-nowrap py-2 pr-3">
          <p>{ago(row.created_at)}</p>
          <p className="text-fg-muted text-xs tabular-nums">{clockTime(row.created_at)}</p>
        </td>
        <td className="py-2">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            aria-label={open ? `Свернуть ${row.number}` : `Подробнее о ${row.number}`}
            className="text-fg-muted hover:bg-surface-2 rounded-md p-1"
          >
            <ChevronDown
              className={`size-4 transition-transform ${open ? "rotate-180" : ""}`}
              aria-hidden
            />
          </button>
        </td>
      </tr>
      {open && (
        <tr className="bg-surface">
          <td colSpan={COLUMNS} className="px-3 py-3">
            <TradeExpand row={row} />
          </td>
        </tr>
      )}
    </>
  );
}

/** A trade as a card on a phone: skin, status and price first, the rest one line under. */
export function TradeCard({ row }: { row: AdminTradeRow }) {
  return (
    <div className="space-y-2 text-sm">
      <SkinCell row={row} />
      <div className="flex items-start justify-between gap-2">
        <StateCell row={row} />
        <p className="whitespace-nowrap tabular-nums" title={priceTitle(row)}>
          {charged(row)}
        </p>
      </div>
      <p className="text-fg-muted flex flex-wrap gap-x-2 text-xs">
        <Link to={`/orders/${row.number}`} className="font-mono hover:underline">
          {row.number}
        </Link>
        <span>{SOURCE_LABELS[row.source]}</span>
        <span>{row.buyer.display_name ?? "Без имени"}</span>
        <span>{ago(row.created_at)}</span>
      </p>
    </div>
  );
}
