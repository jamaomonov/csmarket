/** The «Бизнес» breakdown blocks: markets, channels, payments, categories, skins, buyers… */
import { type ReactNode } from "react";

import { type BusinessOut, type KeyCount } from "./api";
import { BarList } from "./charts/BarList";
import { CATEGORY_LABELS, dollars, labelOf, PAYMENT_LABELS, som, SOURCE_LABELS } from "./labels";

import { Row, Section } from "@/components/Section";
import { SkinThumb } from "@/components/SkinThumb";
import { Reason } from "@/components/Status";
import { UserCell } from "@/components/UserCell";

interface B {
  data: BusinessOut;
}

export function Sources({ data }: B) {
  return (
    <Section title="Площадки">
      <BarList rows={data.sources} label={(k) => labelOf(SOURCE_LABELS, k)} />
    </Section>
  );
}

export function Channels({ data }: B) {
  return (
    <Section title="Каналы">
      <BarList rows={data.channels} label={(k) => k} />
    </Section>
  );
}

export function Payments({ data }: B) {
  return (
    <Section title="Оплата">
      <BarList rows={data.payments} label={(k) => labelOf(PAYMENT_LABELS, k)} />
      {data.kassa_fees.length > 0 && (
        <div className="border-border mt-3 border-t pt-3 text-sm">
          <div className="text-fg-muted mb-1 text-xs">
            Комиссии касс (платит покупатель, в прибыль не входят)
          </div>
          {data.kassa_fees.map((f) => (
            <div key={f.provider} className="flex justify-between tabular-nums">
              <span>
                {labelOf(PAYMENT_LABELS, f.provider)} · {f.payments}
              </span>
              <span>{som(f.fee_uzs)}</span>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

export function Categories({ data }: B) {
  return (
    <Section title="Категории">
      <BarList rows={data.categories} label={(k) => labelOf(CATEGORY_LABELS, k)} />
    </Section>
  );
}

export function TopSkins({ data }: B) {
  return (
    <Section title="Топ-10 скинов по прибыли">
      {data.top_skins.length === 0 ? (
        <p className="text-fg-muted text-sm">Нет заказов.</p>
      ) : (
        <ul className="divide-border divide-y text-sm">
          {data.top_skins.map((s) => (
            <li key={s.name} className="flex items-center gap-3 py-1.5">
              <SkinThumb url={s.image_url} />
              <span className="min-w-0 flex-1 truncate">{s.name}</span>
              <span className="text-fg-muted shrink-0 tabular-nums">{s.orders}</span>
              <span
                className={`w-28 shrink-0 text-right tabular-nums ${Number(s.profit_uzs) < 0 ? "text-danger" : ""}`}
              >
                {som(s.profit_uzs)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

const ORDERS = new Intl.PluralRules("ru");
const ORDER_WORD: Record<string, string> = { one: "заказ", few: "заказа", many: "заказов" };

/** «3 заказа». */
function ordersText(n: number): string {
  return `${String(n)} ${ORDER_WORD[ORDERS.select(n)] ?? "заказа"}`;
}

/**
 * «Покупатели»: a numbered list, each name a link to the card with its orders under it. Two
 * buyers with one name («Mail») also show the end of their account id, never a Steam ID.
 */
export function Buyers({ data }: B) {
  const b = data.buyers;
  const names = b.top.map((u) => u.display_name ?? "");
  const twin = (name: string | null): boolean => names.filter((n) => n === (name ?? "")).length > 1;
  return (
    <Section title="Покупатели">
      <dl className="mb-3">
        <Row label="Новые">
          {b.new.count} · {som(b.new.revenue_uzs)}
        </Row>
        <Row label="Повторные">
          {b.returning.count} · {som(b.returning.revenue_uzs)}
        </Row>
      </dl>
      <ul className="divide-border divide-y text-sm">
        {b.top.map((u, i) => (
          <li key={u.id} className="flex items-center gap-3 py-1.5">
            <span className="text-fg-dim w-5 shrink-0 text-right tabular-nums">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <UserCell
                id={u.id}
                name={u.display_name}
                avatarUrl={u.avatar_url}
                sub={
                  twin(u.display_name)
                    ? `${ordersText(u.orders)} · id …${u.id.slice(-4)}`
                    : ordersText(u.orders)
                }
              />
            </div>
            <span className="w-28 shrink-0 text-right tabular-nums">{som(u.revenue_uzs)}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function Buyback({ data }: B) {
  const bb = data.buyback;
  return (
    <Section title="Выкуп">
      <dl>
        <Row label="Продаж">{bb.count}</Row>
        <Row label="Зачислил Skinslink">{dollars(bb.income_usd)}</Row>
        <Row label="Выплачено на карты">{som(bb.to_cards_uzs)}</Row>
        <Row label="На баланс">{som(bb.to_balances_uzs)}</Row>
        <Row label="К выплате">{som(bb.to_pay_uzs)}</Row>
        <Row label="Прибыль">
          {som(bb.profit_uzs)} · {dollars(bb.profit_usd)}
        </Row>
      </dl>
    </Section>
  );
}

/**
 * A refunds breakdown. One group that holds them all gets no count (it would only repeat the
 * total above): «все: обмен не принят».
 */
function Breakdown({
  label,
  rows,
  total,
  name,
}: {
  label: string;
  rows: KeyCount[];
  total: number;
  name: (key: string) => ReactNode;
}) {
  const only = rows.length === 1 && rows[0]?.count === total;
  return (
    <ul aria-label={label} className="min-w-0">
      {rows.map((k) => (
        <li key={k.key} className="flex justify-between gap-2">
          <span className="min-w-0 truncate">
            {only && <span className="text-fg-muted">все: </span>}
            {name(k.key)}
          </span>
          {!only && <span className="tabular-nums">{k.count}</span>}
        </li>
      ))}
    </ul>
  );
}

export function Refunds({ data }: B) {
  const r = data.refunds;
  return (
    <Section title="Возвраты">
      <p className="mb-2 text-sm">
        {r.count} · {som(r.amount_uzs)}
      </p>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <Breakdown
          label="По площадкам"
          rows={r.by_source}
          total={r.count}
          name={(key) => labelOf(SOURCE_LABELS, key)}
        />
        <Breakdown
          label="По причинам"
          rows={r.by_reason}
          total={r.count}
          name={(key) => <Reason of="return" code={key} />}
        />
      </div>
    </Section>
  );
}
