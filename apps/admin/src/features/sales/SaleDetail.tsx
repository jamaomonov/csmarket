/** «Продажа»: statuses, Skinslink's amount, our payout and margin, the items, the payout. */
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { getSale } from "./api";
import { saleKey } from "./keys";
import { ATTENTION_LABELS, cardLabel, PAYOUT_LABELS, SALE_LABELS } from "./labels";
import { ItemList } from "./Parts";

import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { Banner, DetailGrid, Row, Section } from "@/components/Section";
import { StatusChip } from "@/components/StatusChip";
import { errorText } from "@/features/users/labels";
import { formatDateTime } from "@/lib/format";

const at = (iso: string | null): string => (iso ? formatDateTime(iso) : "—");

export function SaleDetail() {
  const { number = "" } = useParams();
  const sale = useQuery({ queryKey: saleKey(number), queryFn: () => getSale(number) });
  if (sale.isError) {
    return (
      <p role="alert" className="text-danger">
        {errorText(sale.error)}
      </p>
    );
  }
  if (!sale.data) return <p className="text-fg-muted">Загрузка…</p>;
  const s = sale.data;
  return (
    <div className="space-y-4">
      <PageHeader
        back={{ to: "/sales", label: "Продажи" }}
        title={<span className="font-mono">{s.number}</span>}
        badges={
          <StatusChip tone={s.attention_reason ? "danger" : "neutral"}>
            {SALE_LABELS[s.status]}
          </StatusChip>
        }
      />
      {s.attention_reason ? (
        <Banner>
          Требует внимания: {ATTENTION_LABELS[s.attention_reason] ?? s.attention_reason}
        </Banner>
      ) : null}
      <DetailGrid
        main={
          <>
            <Section title="Продажа">
              <dl>
                <Row label="Пользователь">
                  <Link to={`/users/${s.user.id}`} className="hover:underline">
                    {s.user.display_name ?? "Без имени"}
                  </Link>
                </Row>
                <Row label="Куда">
                  {s.payout_to === "card" ? cardLabel(s.card_type, s.card_masked) : "баланс"}
                </Row>
                {s.payout ? (
                  <Row label="Выплата на карту">
                    <Link to={`/payouts/${s.payout.id}`} className="hover:underline">
                      {PAYOUT_LABELS[s.payout.status]}
                    </Link>
                  </Row>
                ) : null}
                <Row label="Обмен Skinslink">{s.trade_id ?? "—"}</Row>
                <Row label="Оффер Steam">{s.trade_offer_id ?? "—"}</Row>
                <Row label="Бот">{s.bot_name ?? "—"}</Row>
                <Row label="Причина закрытия">{s.fail_reason ?? "—"}</Row>
              </dl>
            </Section>
            <ItemList items={s.items} />
          </>
        }
        side={
          <>
            <Section title="Деньги">
              <dl>
                <Row label="Skinslink: котировка">
                  <Money usd={s.quoted_usd} />
                </Row>
                <Row label="Skinslink: зачисляет">
                  {s.amount_usd !== null ? <Money usd={s.amount_usd} /> : "—"}
                </Row>
                <Row label="Курс">{s.rate}</Row>
                <Row label="Предметы">
                  <Money uzs={s.items_uzs} />
                </Row>
                {s.payout_to === "card" ? (
                  <Row label="Комиссия карты">
                    <Money uzs={`-${s.fee_uzs}`} />
                  </Row>
                ) : (
                  <Row label="Бонус за баланс">
                    <Money uzs={s.bonus_uzs} signed />
                  </Row>
                )}
                <Row label="Выплата">
                  <Money uzs={s.payout_uzs} className="font-semibold" />
                </Row>
                <Row label="Наша маржа">
                  <Money usd={s.margin_usd} />
                </Row>
              </dl>
            </Section>
            <Section title="Время">
              <dl>
                <Row label="Создана">{at(s.created_at)}</Row>
                <Row label="Холд до">{at(s.hold_end_at)}</Row>
                <Row label="Зачислено">{at(s.credited_at)}</Row>
              </dl>
            </Section>
          </>
        }
      />
    </div>
  );
}
