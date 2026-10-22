/**
 * «Обмен Waxpeer»: the order's Waxpeer trade — status, Steam offer, deadlines, seller; the ids to
 * search Waxpeer's cabinet by are folded under «Подробнее».
 */
import { type AdminTradeOut } from "./api";

import { CopyButton } from "@/components/CopyButton";
import { More, Row, Section } from "@/components/Section";
import { Reason, Status } from "@/components/Status";
import { LINK } from "@/components/TextLink";
import { formatDateTime } from "@/lib/format";

function when(iso: string | null): string {
  return iso === null ? "—" : formatDateTime(iso);
}

/** The seller's public name and level, when the stored object has them as scalars. */
function sellerText(seller: Record<string, unknown>): string {
  const name = typeof seller.name === "string" ? seller.name : null;
  const level = typeof seller.level === "number" ? ` (уровень ${String(seller.level)})` : "";
  return name === null ? "—" : `${name}${level}`;
}

function penaltiesText(penalties: unknown): string {
  if (penalties === null || penalties === undefined) return "нет";
  if (typeof penalties === "object" && Object.keys(penalties).length === 0) return "нет";
  return typeof penalties === "string" ? penalties : JSON.stringify(penalties);
}

function SteamOffer({ trade }: { trade: AdminTradeOut }) {
  if (trade.trade_id === null) return <>—</>;
  if (trade.offer_url === null) return <>{trade.trade_id}</>;
  return (
    <a href={trade.offer_url} target="_blank" rel="noopener noreferrer" className={LINK}>
      {trade.trade_id}
    </a>
  );
}

function Attention({ trade }: { trade: AdminTradeOut }) {
  if (trade.attention_reason === null) return null;
  return (
    <Row label="Внимание">
      <Reason of="orderAttention" code={trade.attention_reason} />
      {trade.resolved_at !== null && (
        <span className="text-fg-muted">
          {" "}
          · разобрано {formatDateTime(trade.resolved_at)}
          {trade.resolved_note !== null && `: ${trade.resolved_note}`}
        </span>
      )}
    </Row>
  );
}

export function TradeBlock({ trade }: { trade: AdminTradeOut | null }) {
  return (
    <Section title="Обмен Waxpeer" label="Обмен">
      {trade === null ? (
        <p className="text-fg-muted text-sm">Покупки в Waxpeer ещё не было.</p>
      ) : (
        <>
          <dl>
            <Row label="Статус">
              {trade.status === null ? "—" : <Status of="waxpeer" code={String(trade.status)} />}
            </Row>
            <Row label="Обмен в Steam">
              <SteamOffer trade={trade} />
            </Row>
            <Row label="Отправить до">{when(trade.send_until)}</Row>
            <Row label="Принят">{when(trade.accepted_at)}</Row>
            <Row label="Защита до">
              {when(trade.release_date)}
              {trade.is_released && <span className="text-fg-muted"> · снята</span>}
            </Row>
            <Row label="Продавец">{sellerText(trade.seller)}</Row>
            {trade.reason !== null && (
              <Row label="Причина">
                <Reason of="market" code={trade.reason} />
              </Row>
            )}
            <Row label="Штрафы">{penaltiesText(trade.penalties)}</Row>
            <Attention trade={trade} />
          </dl>
          <More>
            <Row label="Project id">
              <span className="break-all">{trade.project_id}</span>
              <CopyButton value={trade.project_id} label="Скопировать project id" />
            </Row>
            <Row label="Id Waxpeer">
              {trade.waxpeer_id === null ? (
                "—"
              ) : (
                <>
                  {String(trade.waxpeer_id)}
                  <CopyButton value={String(trade.waxpeer_id)} label="Скопировать id Waxpeer" />
                </>
              )}
            </Row>
          </More>
        </>
      )}
    </Section>
  );
}
