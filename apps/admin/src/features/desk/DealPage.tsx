/**
 * One deal: when paying is safe, the profit, the price, the skins with their actions, the
 * Skinslink offer and its state (spec 2026-10-29-desk). Every money step asks first.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { type Deal, type DealPatch, DESK_KEY, getDeal, patchDeal, sendDeposit } from "./api";
import { ItemRow } from "./ItemRow";
import { DEAL_STATUS, DEPOSIT_STATUS, deskErrorText, METHOD } from "./labels";
import { TAP } from "./Parts";
import { PriceEditor } from "./PriceEditor";
import { StatusSheet } from "./StatusSheet";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { StatusChip } from "@/components/StatusChip";
import { When } from "@/components/When";
import { formatDateTime } from "@/lib/format";

const OPEN_DEPOSIT = new Set(["creating", "new", "pending", "active"]);

type Sheet = "send" | "status" | "guarantor" | null;

export function DealPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const key = [...DESK_KEY, "deal", id];
  const deal = useQuery({ queryKey: key, queryFn: () => getDeal(id) });
  const [error, setError] = useState<unknown>(null);
  const [sheet, setSheet] = useState<Sheet>(null);
  const act = useMutation({
    mutationFn: (run: () => Promise<Deal>) => run(),
    onSuccess: (d) => {
      setError(null);
      setSheet(null);
      qc.setQueryData(key, d);
      // The answer is the fresh deal; refresh the lists and figures, not this page.
      void qc.invalidateQueries({ queryKey: DESK_KEY, predicate: (q) => q.queryKey[2] !== "deal" });
    },
    onError: (e) => {
      setError(e);
      setSheet(null);
    },
  });
  const d = deal.data;
  if (!d) {
    return deal.isError ? (
      <p className="text-danger">{deskErrorText(deal.error)}</p>
    ) : (
      <p className="text-fg-muted">Загружаем…</p>
    );
  }
  const patch = (body: DealPatch) => act.mutateAsync(() => patchDeal(d.id, body));
  const toSend = d.items.filter(
    (i) => i.destination === "skinslink" && i.state === "open" && i.asset_id,
  );
  const sendable =
    d.trade_link !== null &&
    !d.deposits.some((x) => OPEN_DEPOSIT.has(x.status)) &&
    toSend.length > 0;
  const sendSum = toSend.reduce((s, i) => s + Number(i.skinslink_usd ?? 0), 0);
  const safe = d.protected_until !== null && new Date(d.protected_until) <= new Date();
  return (
    <section className="space-y-4">
      <PageHeader
        title={d.trader}
        back={{ to: "/desk", label: "Мои сделки" }}
        badges={
          <StatusChip tone={DEAL_STATUS[d.status].tone}>{DEAL_STATUS[d.status].label}</StatusChip>
        }
        meta={
          <>
            <When iso={d.created_at} /> · {METHOD[d.method]}
          </>
        }
        actions={
          <Button
            variant="secondary"
            className={TAP}
            onClick={() => {
              setSheet("status");
            }}
          >
            Сменить статус
          </Button>
        }
      />
      {d.status === "reverted" && (
        <p className="border-danger text-danger rounded-lg border p-3" role="status">
          Трейдер откатил обмен: Skinslink забрал деньги, скины вернулись к трейдеру.
        </p>
      )}
      {d.protected_until && d.status !== "reverted" && (
        <p
          className={`rounded-lg border p-3 font-medium ${safe ? "border-success text-success" : "border-warning text-warning"}`}
        >
          {safe
            ? "Защита Steam прошла — можно платить"
            : `Платить безопасно с ${formatDateTime(d.protected_until)}`}
        </p>
      )}
      {error !== null && (
        <p role="alert" className="text-danger">
          {deskErrorText(error)}
        </p>
      )}
      <div className="border-border bg-surface flex flex-wrap items-center gap-3 rounded-lg border p-3">
        <span>
          {d.resolved ? "Прибыль:" : "Прибыль пока:"} <Money usd={d.profit_usd} signed />
        </span>
        {d.method === "guarantor" && d.guarantor_released_at === null && (
          <Button
            variant={safe ? "primary" : "secondary"}
            className={`ml-auto ${TAP}`}
            disabled={act.isPending}
            onClick={() => {
              if (safe) void patch({ guarantor_released: true }).catch(() => undefined);
              else setSheet("guarantor");
            }}
          >
            Подтвердить гаранту
          </Button>
        )}
        {d.guarantor_released_at && (
          <span className="text-sm">
            Гаранту подтверждено <When iso={d.guarantor_released_at} />
          </span>
        )}
      </div>
      <PriceEditor
        deal={d}
        onSave={async (body) => {
          // Its own errors show in the form, not on the page.
          const fresh = await patchDeal(d.id, body);
          qc.setQueryData(key, fresh);
          void qc.invalidateQueries({
            queryKey: DESK_KEY,
            predicate: (q) => q.queryKey[2] !== "deal",
          });
        }}
      />
      <ul className="divide-border border-border divide-y rounded-lg border" aria-label="Скины">
        {d.items.map((i) => (
          <ItemRow
            key={i.id}
            item={i}
            act={(run) => {
              act.mutate(run);
            }}
            busy={act.isPending}
          />
        ))}
      </ul>
      {sendable && (
        <Button
          className={TAP}
          disabled={act.isPending}
          onClick={() => {
            setSheet("send");
          }}
        >
          Отправить обмен
        </Button>
      )}
      {d.deposits.map((x) => (
        <div key={x.id} className="border-border rounded-lg border p-3 text-sm">
          <p className="font-medium">Обмен Skinslink: {DEPOSIT_STATUS[x.status] ?? x.status}</p>
          <p className="text-fg-muted">
            {x.trade_offer_id && <>обмен №{x.trade_offer_id} · </>}
            {x.amount_usd &&
              (x.amount_estimated ? (
                <>
                  примерно <Money usd={x.amount_usd} /> — точная сумма в кабинете Skinslink ·{" "}
                </>
              ) : (
                <>
                  Skinslink: <Money usd={x.amount_usd} /> ·{" "}
                </>
              ))}
            {x.fail_reason && <>причина: {x.fail_reason}</>}
          </p>
        </div>
      ))}
      {sheet === "send" && (
        <ConfirmSheet
          title="Отправить обмен трейдеру?"
          busy={act.isPending}
          onClose={() => {
            setSheet(null);
          }}
        >
          <p className="text-sm">
            {toSend.length} {toSend.length === 1 ? "скин" : toSend.length < 5 ? "скина" : "скинов"}{" "}
            в Skinslink, сейчас ≈ <Money usd={sendSum.toFixed(2)} />. Бот Skinslink пришлёт трейдеру
            обмен.
          </p>
          <div className={CONFIRM_BUTTONS}>
            <Button
              variant="secondary"
              className={TAP}
              disabled={act.isPending}
              onClick={() => {
                setSheet(null);
              }}
            >
              Отмена
            </Button>
            <Button
              className={TAP}
              disabled={act.isPending}
              onClick={() => {
                act.mutate(() => sendDeposit(d.id));
              }}
            >
              {act.isPending ? "Отправляем…" : "Отправить"}
            </Button>
          </div>
        </ConfirmSheet>
      )}
      {sheet === "guarantor" && d.protected_until && (
        <ConfirmSheet
          title="Подтвердить гаранту?"
          busy={act.isPending}
          onClose={() => {
            setSheet(null);
          }}
        >
          <p className="text-sm">
            Защита Steam идёт до {formatDateTime(d.protected_until)}. Трейдер ещё может откатить
            обмен, и деньги будут потеряны.
          </p>
          <div className={CONFIRM_BUTTONS}>
            <Button
              variant="secondary"
              className={TAP}
              onClick={() => {
                setSheet(null);
              }}
            >
              Подождать
            </Button>
            <Button
              className={TAP}
              disabled={act.isPending}
              onClick={() => {
                void patch({ guarantor_released: true }).catch(() => undefined);
              }}
            >
              Всё равно подтвердить
            </Button>
          </div>
        </ConfirmSheet>
      )}
      {sheet === "status" && (
        <StatusSheet
          current={d.status}
          busy={act.isPending}
          onClose={() => {
            setSheet(null);
          }}
          onSave={(status) => {
            void patch({ status }).catch(() => undefined);
          }}
        />
      )}
    </section>
  );
}
