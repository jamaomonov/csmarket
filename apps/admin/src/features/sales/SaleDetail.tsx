/**
 * «Продажа»: statuses, Skinslink's amount, our payout and margin, the items, the payout. A sale
 * with an open attention shows «Проверено» (an optional note; audited) and, once checked, who
 * checked it and when.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { type AdminSale, getSale, resolveSale } from "./api";
import { SALES_LIST_KEY, saleKey } from "./keys";
import { ATTENTION_LABELS, cardLabel, PAYOUT_LABELS, payoutErrorText, SALE_LABELS } from "./labels";
import { ItemList } from "./Parts";

import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { Banner, DetailGrid, Row, Section } from "@/components/Section";
import { StatusChip } from "@/components/StatusChip";
import { DASHBOARD_KEY } from "@/features/dashboard/keys";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime } from "@/lib/format";

const at = (iso: string | null): string => (iso ? formatDateTime(iso) : "—");

function Attention({ sale }: { sale: AdminSale }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const key = useIdempotencyKey("admin-sale-resolve");
  const resolve = useMutation({
    mutationFn: () => {
      const value = note.trim() || null;
      return resolveSale(sale.number, value, key.keyFor(JSON.stringify({ n: sale.number, value })));
    },
    onSuccess: (next) => {
      key.reset();
      qc.setQueryData(saleKey(sale.number), next);
      void qc.invalidateQueries({ queryKey: SALES_LIST_KEY });
      void qc.invalidateQueries({ queryKey: DASHBOARD_KEY });
    },
  });
  if (sale.attention_reason === null) return null;
  const label = ATTENTION_LABELS[sale.attention_reason];
  if (!sale.attention_open) {
    return (
      <Banner tone="info">
        Проверено: {label}. {sale.resolved_by?.display_name ?? "—"}, {at(sale.resolved_at)}
        {sale.resolved_note ? ` — ${sale.resolved_note}` : ""}
      </Banner>
    );
  }
  return (
    <Banner>
      <div className="space-y-2">
        <p>Требует внимания: {label}</p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-fg flex flex-col gap-1 text-sm">
            Что сделали (необязательно)
            <input
              value={note}
              maxLength={500}
              onChange={(e) => {
                setNote(e.target.value);
              }}
              className="border-border bg-bg w-full rounded-md border px-3 py-1.5 sm:w-80"
            />
          </label>
          <Button
            disabled={resolve.isPending}
            onClick={() => {
              resolve.mutate();
            }}
          >
            Проверено
          </Button>
        </div>
        {resolve.isError ? <p role="alert">{payoutErrorText(resolve.error)}</p> : null}
      </div>
    </Banner>
  );
}

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
          <StatusChip tone={s.attention_open ? "danger" : "neutral"}>
            {SALE_LABELS[s.status]}
          </StatusChip>
        }
      />
      <Attention sale={s} />
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
