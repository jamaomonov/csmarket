/** The «Бизнес» breakdown blocks: markets, channels, payments, categories, skins, buyers… */
import { type BusinessOut } from "./api";
import { BarList } from "./charts/BarList";
import {
  CATEGORY_LABELS,
  dollars,
  labelOf,
  PAYMENT_LABELS,
  REASON_LABELS,
  som,
  SOURCE_LABELS,
} from "./labels";

import { Row, Section } from "@/components/Section";
import { SkinThumb } from "@/components/SkinThumb";
import { UserCell } from "@/components/UserCell";

interface B { data: BusinessOut }

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

export function Buyers({ data }: B) {
  const b = data.buyers;
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
        {b.top.map((u) => (
          <li key={u.id} className="flex items-center gap-3 py-1.5">
            <div className="min-w-0 flex-1">
              <UserCell id={u.id} name={u.display_name} avatarUrl={u.avatar_url} />
            </div>
            <span className="text-fg-muted shrink-0 tabular-nums">{u.orders}</span>
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

export function Refunds({ data }: B) {
  const r = data.refunds;
  return (
    <Section title="Возвраты">
      <p className="mb-2 text-sm">
        {r.count} · {som(r.amount_uzs)}
      </p>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <ul>
          {r.by_source.map((k) => (
            <li key={k.key} className="flex justify-between">
              <span>{labelOf(SOURCE_LABELS, k.key)}</span>
              <span className="tabular-nums">{k.count}</span>
            </li>
          ))}
        </ul>
        <ul>
          {r.by_reason.map((k) => (
            <li key={k.key} className="flex justify-between">
              <span className="truncate">{labelOf(REASON_LABELS, k.key)}</span>
              <span className="tabular-nums">{k.count}</span>
            </li>
          ))}
        </ul>
      </div>
    </Section>
  );
}
