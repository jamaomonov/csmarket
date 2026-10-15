"use client";

import { SessionApiError } from "@csmarket/api-client";
import { Button, cn } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";

import { CARD_BRANDS, PayoutPicker } from "./PayoutPicker";
import { SellSteps } from "./SellSteps";

import { PayConsent } from "@/components/legal/PayConsent";
import { useRouter } from "@/i18n/navigation";
import { track } from "@/lib/analytics";
import { salePath } from "@/lib/paths";
import { CARDS_KEY, listCards, type SavedCard } from "@/lib/sales";
import {
  cardDigits,
  cardFits,
  createSale,
  formatCard,
  hasPrefix,
  luhnOk,
  mintSellKey,
  payoutCardType,
  sellBody,
  sellError,
  sellSummary,
  type Inventory,
  type Payout,
  type SellBody,
  type SellConfig,
  type SellErrorCode,
  type SellItem,
} from "@/lib/sell";

interface SellCartProps {
  locale: string;
  config: SellConfig;
  inventory: Inventory;
  chosen: SellItem[];
  onRemove: (assetId: string) => void;
  payout: Payout;
  onPayout: (p: Payout) => void;
  /** The API said the prices moved: read the inventory again. */
  onPricesChanged: () => void;
}

interface RowProps {
  label: string;
  value: string;
  strong?: boolean;
}

/** What the cart says went wrong: an API refusal (with its details), a saved card gone, or
 * anything else. */
interface CartError {
  code: SellErrorCode | "card_gone" | "generic";
  reason: string | null;
  minSum: string | null;
}

const Row = ({ label, value, strong }: RowProps) => (
  <p className={cn("flex items-baseline gap-3", strong ? "text-base font-bold" : "text-sm")}>
    <span className={strong ? "text-fg" : "text-fg-muted"}>{label}</span>
    <span aria-hidden className="border-border flex-1 border-b border-dashed" />
    <span
      className={cn("num", strong && "text-accent")}
      {...(strong ? { "data-testid": "sell-payout" } : {})}
    >
      {value}
    </span>
  </p>
);

/** The chosen skins, where the money goes, what reaches the seller, and «Продать». */
export function SellCart(p: SellCartProps) {
  const t = useTranslations("web.sell");
  const router = useRouter();
  const steam = useTranslations("web.sell.steam");
  const qc = useQueryClient();
  const cardId = useId();
  const cardHint = useId();
  const cards = useQuery({ queryKey: CARDS_KEY, queryFn: listCards });
  const [error, setError] = useState<CartError | null>(null);
  const key = useRef<{ body: string; key: string } | null>(null);
  const sum = sellSummary(
    p.chosen.map((x) => Number(x.price_uzs)),
    p.payout,
    p.config,
  );
  const uzs = (n: number) => formatUzs(p.locale, n);
  const min = Number(p.inventory.min_sum_uzs);
  const cardMin = Number(p.config.card_min_uzs);
  const cardType = payoutCardType(p.payout);
  const toCard = cardType !== null;
  const newCard = p.payout.to === "new" ? p.payout : null;
  // A number is another type's once its first digits leave the type's prefix; a full one of
  // this type that fails Luhn is a typo.
  const otherType =
    newCard !== null && newCard.digits.length >= 4 && !hasPrefix(newCard.type, newCard.digits);
  const typo =
    newCard !== null && !otherType && newCard.digits.length === 16 && !luhnOk(newCard.digits);
  const wrongCard = otherType || typo;
  // `min` is ONE item priced once; each chosen item was rounded down to 100 on its own, so up
  // to 100 per extra item may be lost. The API's 409 `below_minimum` stays the authority.
  const minItems = min - 100 * Math.max(p.chosen.length - 1, 0);
  const belowMin = p.chosen.length > 0 && sum.items < minItems;
  const belowCardMin = toCard && sum.payout > 0 && sum.payout < cardMin;
  const sell = useMutation({
    // The variables hold the typed card number: do not keep them in the mutation cache.
    gcTime: 0,
    mutationFn: (body: SellBody) => {
      const text = JSON.stringify(body);
      if (key.current?.body !== text) key.current = { body: text, key: mintSellKey() };
      return createSale(body, key.current.key);
    },
    onSuccess: (sale) => {
      key.current = null;
      track({
        name: "sell",
        params: { transaction_id: sale.number, currency: "UZS", value: Number(sale.payout_uzs) },
      });
      void qc.invalidateQueries({ queryKey: CARDS_KEY });
      router.push(salePath(sale.number));
    },
    onError: async (err, body) => {
      const refusal = sellError(err);
      const gone = err instanceof SessionApiError && err.status === 404 && "card_id" in body.payout;
      // A refusal closes the sale on the API: the next try is a new one, with a new key. A lost
      // answer (no refusal) keeps the key, so the retry replays the same sale.
      if (refusal || gone) key.current = null;
      setError({
        code: gone ? "card_gone" : (refusal?.code ?? "generic"),
        reason: refusal?.reason ?? null,
        minSum: refusal?.minSumUzs ?? null,
      });
      if (refusal?.code === "prices_changed") p.onPricesChanged();
      if (gone) p.onPayout({ to: "balance" });
      // A typed card may be saved by now (a sale refused after it was stored): pay to that one.
      await qc.invalidateQueries({ queryKey: CARDS_KEY });
      const typed = "new_card" in body.payout ? body.payout.new_card : null;
      const saved = typed
        ? qc
            .getQueryData<{ items: SavedCard[] }>(CARDS_KEY)
            ?.items.find((c) => c.type === typed.type && c.last4 === typed.number.slice(-4))
        : undefined;
      if (saved) p.onPayout({ to: "saved", cardId: saved.id, type: saved.type });
    },
  });
  const errorText = (e: CartError): string => {
    if (e.code === "steam_refused" && e.reason && steam.has(e.reason)) return steam(e.reason);
    return t(`errors.${e.code}`, {
      count: p.config.max_cards,
      sum: uzs(Number(e.minSum ?? p.inventory.min_sum_uzs)),
    });
  };
  const blocked =
    p.chosen.length === 0 ||
    belowMin ||
    belowCardMin ||
    (newCard !== null && !cardFits(newCard.type, newCard.digits)) ||
    sell.isPending;
  const title = t("cart.title", { count: p.chosen.length });
  return (
    <aside aria-label={title} className="bg-surface flex flex-col gap-5 rounded-xl p-5">
      <h2 className="text-lg font-bold">
        {title}
        {p.chosen.length > 0 ? <span className="text-accent num"> · {uzs(sum.items)}</span> : null}
      </h2>
      {p.chosen.length === 0 ? (
        <p className="text-fg-muted text-sm">{t("cart.hint")}</p>
      ) : (
        <ul className="-mr-2 flex max-h-56 flex-col gap-1.5 overflow-y-auto pr-2">
          {p.chosen.map((x) => (
            <li key={x.asset_id} className="bg-surface-2 flex items-center gap-3 rounded-lg p-2">
              {x.image_url ? (
                // eslint-disable-next-line @next/next/no-img-element -- Steam CDN images
                <img src={x.image_url} alt="" className="h-8 w-12 shrink-0 object-contain" />
              ) : null}
              <span className="text-small min-w-0 flex-1 truncate">{x.name}</span>
              <span className="num text-small shrink-0 font-semibold">
                {uzs(Number(x.price_uzs))}
              </span>
              <button
                type="button"
                aria-label={t("cart.remove", { name: x.name })}
                onClick={() => {
                  p.onRemove(x.asset_id);
                }}
                className="text-fg-dim hover:text-fg rounded p-0.5"
              >
                <X className="size-4" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      <PayoutPicker
        config={p.config}
        cards={cards.data?.items ?? []}
        value={p.payout}
        onPick={(next) => {
          setError(null);
          p.onPayout(next);
        }}
      />
      {newCard !== null ? (
        <div>
          <label htmlFor={cardId} className="text-fg-muted mb-2 block text-sm font-semibold">
            {t("card.label", { method: CARD_BRANDS[newCard.type] })}
          </label>
          <input
            id={cardId}
            name="cardnumber"
            inputMode="numeric"
            autoComplete="cc-number"
            placeholder="0000 0000 0000 0000"
            value={formatCard(newCard.digits)}
            onChange={(e) => {
              p.onPayout({ ...newCard, digits: cardDigits(e.target.value) });
            }}
            aria-invalid={wrongCard}
            {...(wrongCard ? { "aria-describedby": cardHint } : {})}
            className={cn(
              "bg-bg num h-12 w-full rounded-lg border px-4 text-lg tracking-wider outline-none",
              wrongCard ? "border-danger" : "border-border focus:border-accent",
            )}
          />
          {wrongCard ? (
            <p id={cardHint} className="text-danger mt-2 text-sm">
              {typo
                ? t("errors.card_invalid")
                : t("card.wrong", { method: CARD_BRANDS[newCard.type] })}
            </p>
          ) : null}
        </div>
      ) : null}
      {belowCardMin ? (
        <p className="text-danger text-sm">{t("card.min", { sum: uzs(cardMin) })}</p>
      ) : null}
      <div className="flex flex-col gap-2">
        <Row label={t("summary.items")} value={uzs(sum.items)} />
        {cardType !== null ? (
          <Row
            label={t("summary.fee", { percent: p.config.card_fee_pct[cardType] })}
            value={`−${uzs(sum.fee)}`}
          />
        ) : (
          <Row
            label={t("summary.bonus", { percent: p.config.balance_bonus_pct })}
            value={`+${uzs(sum.bonus)}`}
          />
        )}
        <Row label={t("summary.payout")} value={uzs(sum.payout)} strong />
      </div>
      <SellSteps toCard={toCard} />
      {error ? (
        <p role="alert" className="text-danger text-sm">
          {errorText(error)}
        </p>
      ) : null}
      <Button
        size="lg"
        disabled={blocked}
        onClick={() => {
          setError(null);
          sell.mutate(
            sellBody(
              p.chosen.map((x) => x.asset_id),
              p.payout,
              sum.payout,
            ),
          );
        }}
      >
        {sell.isPending
          ? t("sending")
          : belowMin
            ? t("addMore", { sum: uzs(minItems - sum.items) })
            : t("submit", { sum: uzs(sum.payout) })}
      </Button>
      <PayConsent doc="sell" />
    </aside>
  );
}
