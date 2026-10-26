/**
 * «Заявка на выплату», built for paying from a phone: on top what to send and where
 * (`PayBlock`: «Беру в работу», amount, card, sale number), a red banner when the seller is
 * banned or the wallet frozen, the decisions (`PayoutActions`), the receipts of a paid payout
 * (`ProofsBlock`), the risks (`RiskBlock`), then
 * the money breakdown, the items and the seller's other sales and payouts.
 */
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { payoutKey } from "./keys";
import { payoutCode } from "./labels";
import { ItemList } from "./Parts";
import { PayBlock } from "./PayBlock";
import { CANCEL_LABEL, PayoutActions } from "./PayoutActions";
import { getPayout, type PayoutDetail as Detail } from "./payoutsApi";
import { ProofsBlock } from "./ProofsBlock";
import { RiskBlock } from "./RiskBlock";

import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { Banner, DetailGrid, Row, Section } from "@/components/Section";
import { Status } from "@/components/Status";
import { TextLink } from "@/components/TextLink";
import { errorText } from "@/features/users/labels";
import { ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const at = (iso: string | null | undefined): string => (iso ? formatDateTime(iso) : "—");

function MoneySection({ d }: { d: Detail }) {
  const s = d.sale;
  return (
    <Section title="Деньги">
      <dl>
        <Row label="Предметы">
          <Money uzs={s.items_uzs} />
        </Row>
        <Row label="Комиссия карты">
          <Money uzs={`-${s.fee_uzs}`} />
        </Row>
        <Row label="К выплате">
          <Money uzs={d.request.amount_uzs} className="font-semibold" />
        </Row>
        <Row label="Skinslink зачислил">
          {s.amount_usd !== null ? <Money usd={s.amount_usd} /> : "ещё нет"}
        </Row>
        <Row label="Котировка Skinslink">
          <Money usd={s.quoted_usd} />
        </Row>
        <Row label="Наша маржа">
          <Money usd={s.margin_usd} />
        </Row>
        <Row label="Холд до">{at(s.hold_end_at)}</Row>
        <Row label="К выплате с">{at(d.request.to_pay_at)}</Row>
        {d.request.paid_at ? <Row label="Выплачено">{at(d.request.paid_at)}</Row> : null}
        {d.decided_by ? <Row label="Решил">{d.decided_by.display_name ?? "—"}</Row> : null}
        {d.note ? <Row label="Комментарий">{d.note}</Row> : null}
        {d.reject_reason ? <Row label="Причина отказа">{d.reject_reason}</Row> : null}
      </dl>
    </Section>
  );
}

function History({ d }: { d: Detail }) {
  const li = "border-border flex justify-between gap-2 border-t py-1.5 first:border-t-0";
  return (
    <Section title="Другие продажи и выплаты">
      {d.history_sales.length + d.history_payouts.length === 0 ? (
        <p className="text-fg-muted text-sm">Других продаж и выплат нет.</p>
      ) : null}
      {d.history_payouts.length > 0 ? (
        <>
          <h3 className="text-fg-muted mb-1 text-xs uppercase">Выплаты</h3>
          <ul className="mb-3 text-sm">
            {d.history_payouts.map((h) => (
              <li key={h.id} className={li}>
                <TextLink to={`/payouts/${h.id}`} number>
                  {h.sale_number}
                </TextLink>
                <Status of="payout" code={h.status} />
                <Money uzs={h.amount_uzs} />
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {d.history_sales.length > 0 ? (
        <>
          <h3 className="text-fg-muted mb-1 text-xs uppercase">Продажи</h3>
          <ul className="text-sm">
            {d.history_sales.map((h) => (
              <li key={h.number} className={li}>
                <TextLink to={`/sales/${h.number}`} number>
                  {h.number}
                </TextLink>
                <Status of="sale" code={h.status} />
                <Money uzs={h.payout_uzs} />
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </Section>
  );
}

const REFRESH_MS = 15_000;

export function PayoutDetail() {
  const { id = "" } = useParams();
  // Re-read like the queue does: another operator's claim or decision shows within 15 s.
  const detail = useQuery({
    queryKey: payoutKey(id),
    queryFn: () => getPayout(id),
    refetchInterval: REFRESH_MS,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
  const back = { to: "/payouts", label: "Заявки на выплату" };
  if (!detail.data && detail.isError) {
    const missing = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div className="space-y-4">
        <PageHeader back={back} title="Выплата" />
        <p role="alert" className={missing ? "text-fg-muted" : "text-danger"}>
          {missing ? "Заявка не найдена." : errorText(detail.error)}
        </p>
      </div>
    );
  }
  if (!detail.data) {
    return (
      <div className="space-y-4">
        <PageHeader back={back} title="Выплата" />
        <div aria-busy className="bg-surface h-64 animate-pulse rounded-lg" />
      </div>
    );
  }
  const d = detail.data;
  const s = d.sale;
  const refresh = () => void detail.refetch();
  const blocked = d.can_decide && (d.risk?.banned === true || d.risk?.wallet_frozen === true);
  return (
    <div className="space-y-4">
      <PageHeader
        back={back}
        title={
          <>
            Выплата по продаже{" "}
            <TextLink to={`/sales/${s.number}`} number>
              {s.number}
            </TextLink>
          </>
        }
        meta={
          <>
            Продавец:{" "}
            <TextLink to={`/users/${d.request.user.id}`}>
              {d.request.user.display_name ?? "без имени"}
            </TextLink>
          </>
        }
        badges={<Status of="payout" code={payoutCode(d.request.status, d.request.flags)} />}
      />
      {blocked ? (
        <Banner>
          {d.risk?.banned === true ? "Аккаунт заблокирован" : "Кошелёк заморожен"} — не платите.
          «Выплачено» только с причиной.
        </Banner>
      ) : null}
      {d.can_cancel === true ? (
        <Banner>
          Skinslink откатил обмен после того, как заявка стала к выплате. Если деньги ещё не ушли —
          «{CANCEL_LABEL}».
        </Banner>
      ) : null}
      <DetailGrid
        main={
          <>
            <PayBlock key={d.request.id} detail={d} onChanged={refresh} />
            <PayoutActions detail={d} onStale={refresh} />
            <ProofsBlock detail={d} />
            <RiskBlock detail={d} />
            <ItemList items={s.items} />
          </>
        }
        side={
          <>
            <MoneySection d={d} />
            <History d={d} />
          </>
        }
      />
    </div>
  );
}
