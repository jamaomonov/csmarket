/**
 * «Покупка Skinslink»: a Skinslink order's purchase — status, Steam offer, money; the ids to
 * search Skinslink's dashboard by are folded under «Подробнее».
 */
import { type AdminSkinslinkPurchaseOut } from "./api";

import { More, Row, Section } from "@/components/Section";
import { Reason, Status } from "@/components/Status";
import { LINK } from "@/components/TextLink";
import { formatDateTime } from "@/lib/format";

function when(iso: string | null): string {
  return iso === null ? "—" : formatDateTime(iso);
}

interface SkinslinkBlockProps {
  purchase: AdminSkinslinkPurchaseOut;
}

export function SkinslinkBlock({ purchase: p }: SkinslinkBlockProps) {
  return (
    <Section title="Покупка Skinslink">
      <dl>
        <Row label="Статус">
          {p.status === null ? "—" : <Status of="supplier" code={p.status} />}
        </Row>
        <Row label="Предложение">
          {p.offer_url !== null && p.offer_id !== null ? (
            <a href={p.offer_url} target="_blank" rel="noreferrer" className={LINK}>
              {p.offer_id}
            </a>
          ) : (
            "—"
          )}
        </Row>
        <Row label="Списано">{p.amount_usd === null ? "—" : `$${p.amount_usd}`}</Row>
        {p.fail_reason !== null && (
          <Row label="Причина">
            <Reason of="supplier" code={p.fail_reason} />
          </Row>
        )}
        {p.hold_end_date !== null && <Row label="Холд до">{when(p.hold_end_date)}</Row>}
        {p.buy_pending && <Row label="Покупка">ждёт попытки</Row>}
        {p.buy_unconfirmed_at !== null && (
          <Row label="Ответ потерян">{when(p.buy_unconfirmed_at)}</Row>
        )}
        {p.attention_reason !== null && (
          <Row label="Внимание">
            <Reason of="orderAttention" code={p.attention_reason} />
            {p.resolved_at !== null && ` · разобрано ${when(p.resolved_at)}`}
          </Row>
        )}
      </dl>
      <More>
        <Row label="Purchase id">{p.purchase_id ?? "—"}</Row>
        <Row label="merchant_tx_id">
          <span className="break-all">{p.merchant_tx_id}</span>
        </Row>
        <Row label="Asset id">{p.asset_id}</Row>
      </More>
    </Section>
  );
}
