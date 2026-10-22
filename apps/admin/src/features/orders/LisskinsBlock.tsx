/**
 * «Покупка LIS-SKINS»: a LIS-SKINS order's purchase — status, Steam offer, money; the ids to
 * search its purchase history by are folded under «Подробнее».
 */
import { type AdminLisskinsPurchaseOut } from "./api";

import { More, Row, Section } from "@/components/Section";
import { Reason, Status } from "@/components/Status";
import { LINK } from "@/components/TextLink";
import { formatDateTime } from "@/lib/format";

function when(iso: string | null): string {
  return iso === null ? "—" : formatDateTime(iso);
}

interface LisskinsBlockProps {
  purchase: AdminLisskinsPurchaseOut;
}

export function LisskinsBlock({ purchase: p }: LisskinsBlockProps) {
  return (
    <Section title="Покупка LIS-SKINS">
      <dl>
        <Row label="Статус">{p.status === null ? "—" : <Status of="market" code={p.status} />}</Row>
        <Row label="Предложение">
          {p.offer_url !== null && p.offer_id !== null ? (
            <a href={p.offer_url} target="_blank" rel="noreferrer" className={LINK}>
              {p.offer_id}
            </a>
          ) : (
            "—"
          )}
        </Row>
        {p.offer_expiry_at !== null && <Row label="Принять до">{when(p.offer_expiry_at)}</Row>}
        <Row label="Списано">{p.amount_usd === null ? "—" : `$${p.amount_usd}`}</Row>
        {p.return_reason !== null && (
          <Row label="Возврат">
            <Reason of="market" code={p.return_reason} />
            {p.error !== null && <span className="text-fg-muted"> · {p.error}</span>}
          </Row>
        )}
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
        <Row label="custom_id">
          <span className="break-all">{p.custom_id}</span>
        </Row>
        <Row label="Лот">{p.skin_id}</Row>
      </More>
    </Section>
  );
}
