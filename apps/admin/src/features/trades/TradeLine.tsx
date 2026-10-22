/** One line of the «Обмены» table and its expandable details. */
import { ChevronDown } from "lucide-react";
import { type MouseEvent } from "react";
import { useNavigate } from "react-router-dom";

import { type AdminTradeRow } from "./api";
import { SOURCE_LABELS } from "./labels";
import { shortDate, timeLeft } from "./time";
import { TradeExpand } from "./TradeExpand";
import { AttentionBadge } from "../orders/AttentionBadge";

import { Reason, Status } from "@/components/Status";
import { TextLink } from "@/components/TextLink";
import { When } from "@/components/When";
import { providerLabel } from "@/features/users/labels";
import { statusText } from "@/lib/dictionary";
import { formatSum } from "@/lib/format";

/** Columns of the table, the chevron's included (the details row spans them all). */
export const COLUMNS = 8;

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
      {/* Rarity is a dot on the picture: the row's left edge is only for «needs attention». */}
      <span className="relative shrink-0">
        {item.image_url !== null ? (
          <img src={item.image_url} alt="" className="size-10 object-contain" />
        ) : (
          <span aria-hidden className="bg-surface-2 block size-10 rounded" />
        )}
        {item.rarity_color !== null && (
          <span
            aria-hidden
            data-testid="rarity-dot"
            className="ring-surface absolute -left-0.5 -top-0.5 size-2.5 rounded-full ring-2"
            style={{ backgroundColor: item.rarity_color }}
          />
        )}
      </span>
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

/** The source's own status word for a tooltip: Waxpeer's code is digits, the rest a word. */
export function sourceStatusText(status: string): string {
  return statusText(/^\d+$/.test(status) ? "waxpeer" : "market", status);
}

export function StateCell({ row }: { row: AdminTradeRow }) {
  const hold =
    row.trade_state === "hold" && row.protected_until !== null ? row.protected_until : null;
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1">
        <Status
          of="trade"
          code={row.trade_state}
          testId="trade-state"
          title={
            row.source_status === null
              ? undefined
              : `Площадка: ${sourceStatusText(row.source_status)}`
          }
        />
        <AttentionBadge reason={row.attention_reason} />
      </div>
      {row.trade_state === "refunded" && row.failure_reason !== null && (
        <Reason of="failure" code={row.failure_reason} className="text-fg-muted block text-xs" />
      )}
      {row.attention_reason !== null && (
        <Reason
          of="orderAttention"
          code={row.attention_reason}
          className="text-danger block whitespace-nowrap text-xs"
        />
      )}
      {hold !== null && (
        <p data-testid="hold-left" className="text-fg-muted whitespace-nowrap text-xs">
          защита до {row.protected_estimated ? "≈ " : ""}
          {shortDate(hold)} · {timeLeft(hold)}
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
          <TextLink to={`/orders/${row.number}`} number>
            {row.number}
          </TextLink>
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
        <td className="py-2 pr-3">
          <div className="flex items-center gap-2">
            {row.buyer.avatar_url !== null && (
              <img src={row.buyer.avatar_url} alt="" className="size-6 rounded-full" />
            )}
            <TextLink to={`/users/${row.buyer.id}`} className="whitespace-nowrap">
              {row.buyer.display_name ?? "Без имени"}
            </TextLink>
          </div>
          <p className="text-fg-muted text-xs">{providerLabel(row.paid_with)}</p>
        </td>
        <td className="min-w-48 py-2 pr-3">
          <StateCell row={row} />
        </td>
        <td className="whitespace-nowrap py-2 pr-3">
          <When iso={row.created_at} />
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
        <TextLink to={`/orders/${row.number}`} number>
          {row.number}
        </TextLink>
        <span>{SOURCE_LABELS[row.source]}</span>
        <span>{row.buyer.display_name ?? "Без имени"}</span>
        <When iso={row.created_at} />
      </p>
    </div>
  );
}
