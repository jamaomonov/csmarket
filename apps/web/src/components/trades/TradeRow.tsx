import { cn } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { ItemThumb } from "./ItemThumb";
import { StatusBadge } from "./StatusBadge";

import type { OrderOut } from "@/lib/orders";
import type { SaleOut } from "@/lib/sales";

import { Link } from "@/i18n/navigation";
import { formatUsd } from "@/lib/orders";
import { orderPath, salePath } from "@/lib/paths";
import { orderBadge, saleBadge, type Badge } from "@/lib/trade-status";

interface RowProps {
  locale: string;
  /** The date format, built once per list. */
  when: Intl.DateTimeFormat;
}

/** One purchase on «Обмены»: what was paid, leaving the balance as «−». */
export function OrderRow({ order, locale, when }: RowProps & { order: OrderOut }) {
  const t = useTranslations("web.trades");
  const badge = orderBadge(order);
  const refunded = order.refunded_to === "balance";
  const spent = order.paid_at !== null && !refunded;
  const viaApi = order.channel === "api";
  // API orders are paid in dollars: `price_uzs` is "0", `price_usd` what the wallet was charged.
  const price = viaApi ? formatUsd(order.price_usd) : formatUzs(locale, order.price_uzs);
  return (
    <Row
      href={orderPath(order.number)}
      testId="order-card"
      state={order.status}
      thumb={<ItemThumb imageUrl={order.image_url} rarityColor={order.rarity_color} />}
      name={order.name}
      kind={viaApi ? t("api") : t("purchase")}
      badge={badge}
      meta={`#${order.number} · ${when.format(new Date(order.created_at))}`}
      amount={spent ? `−${price}` : price}
      amountClass={spent ? undefined : "text-fg-dim"}
      note={orderNote(t, order, refunded)}
    />
  );
}

function orderNote(
  t: ReturnType<typeof useTranslations<"web.trades">>,
  order: OrderOut,
  refunded: boolean,
): string | null {
  if (refunded) return t(order.channel === "api" ? "returnedUsdWallet" : "returned");
  if (order.paid_with === "usd_wallet") return t("paidUsdWallet");
  return order.paid_with === "wallet" ? t("paidBalance") : null;
}

/** One sale on «Обмены»: the first item («+N» more) and the money coming in as «+». */
export function SaleRow({ sale, locale, when }: RowProps & { sale: SaleOut }) {
  const t = useTranslations("web.trades");
  const [first] = sale.items;
  const failed = sale.status === "closed" || sale.status === "reverted";
  const payout = formatUzs(locale, sale.payout_uzs);
  return (
    <Row
      href={salePath(sale.number)}
      testId="sale-card"
      state={sale.status}
      thumb={
        <ItemThumb
          imageUrl={first?.image_url ?? null}
          rarityColor={first?.rarity_color ?? null}
          more={sale.items.length - 1}
        />
      }
      name={first?.name ?? ""}
      kind={t("sale")}
      badge={saleBadge(sale)}
      meta={`#${sale.number} · ${when.format(new Date(sale.created_at))}`}
      amount={failed ? payout : `+${payout}`}
      amountClass={failed ? "text-fg-dim" : "text-accent"}
      note={failed ? null : t(sale.payout_to === "card" ? "toCard" : "toBalance")}
    />
  );
}

interface RowFrameProps {
  href: string;
  testId: string;
  state: string;
  thumb: React.ReactNode;
  name: string;
  kind: string;
  badge: Badge;
  meta: string;
  amount: string;
  amountClass: string | undefined;
  note: string | null;
}

function Row(p: RowFrameProps) {
  return (
    <Link
      href={p.href}
      data-testid={p.testId}
      data-state={p.state}
      className="bg-surface hover:bg-surface-hover hover:border-border-strong group grid grid-cols-[auto_1fr_auto] items-center gap-x-4 gap-y-2 rounded-xl border border-transparent p-3 transition-colors sm:grid-cols-[auto_1fr_auto_auto] sm:px-4"
    >
      {p.thumb}
      <span className="min-w-0">
        <span className="block truncate font-semibold">{p.name}</span>
        <span className="text-fg-dim mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px]">
          <span className="border-border-strong text-fg-muted rounded-md border px-1.5 py-px text-[11px] font-semibold uppercase tracking-wide">
            {p.kind}
          </span>
          <StatusBadge badge={p.badge} />
          <span className="whitespace-nowrap">{p.meta}</span>
        </span>
      </span>
      <span className="text-right">
        <span className={cn("num block whitespace-nowrap font-bold", p.amountClass)}>
          {p.amount}
        </span>
        {p.note ? <span className="text-fg-dim block text-[12px]">{p.note}</span> : null}
      </span>
      <ChevronRight
        aria-hidden
        className="text-fg-dim group-hover:text-fg hidden size-5 transition-colors sm:block"
      />
    </Link>
  );
}
