/**
 * One deal: what it is (price, Skinslink value, profit, note, link, guarantor), when paying is
 * safe, the skins with their actions, the Skinslink offer and its state (specs 2026-10-29-desk,
 * 2026-10-31-desk-v2). Every money step asks first; «Сменить статус» sits at the bottom.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { AddItems } from "./AddItems";
import {
  addItems,
  type Deal,
  type DealPatch,
  DESK_KEY,
  getDeal,
  patchDeal,
  sendDeposit,
} from "./api";
import { DealEditSheet } from "./DealEditSheet";
import { DealSummary } from "./DealSummary";
import { DepositCard, OPEN_DEPOSIT } from "./DepositCard";
import { ItemRow } from "./ItemRow";
import { DEAL_STATUS, deskErrorText, METHOD } from "./labels";
import { DeskError, TAP } from "./Parts";
import { SendBar, SendSheet } from "./SendBar";
import { isHand, StatusSheet } from "./StatusSheet";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";
import { PageHeader } from "@/components/PageHeader";
import { StatusChip } from "@/components/StatusChip";
import { When } from "@/components/When";
import { formatDateTime } from "@/lib/format";

const REFRESH_MS = 5_000;
const LOCKED = new Set(["credited", "sold", "written_off", "reverted"]);
const FINAL = new Set(["closed", "cancelled", "reverted"]);

type Sheet = "send" | "status" | "guarantor" | "edit" | null;

export function DealPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const key = [...DESK_KEY, "deal", id];
  const deal = useQuery({
    queryKey: key,
    queryFn: () => getDeal(id),
    // While Skinslink's offer is on its way, its state changes by itself: keep it fresh.
    refetchInterval: (q) =>
      q.state.data?.deposits.some((x) => OPEN_DEPOSIT.has(x.status)) ? REFRESH_MS : false,
  });
  const [error, setError] = useState<unknown>(null);
  const [sheet, setSheet] = useState<Sheet>(null);
  const fresh = (d: Deal) => {
    qc.setQueryData(key, d);
    // The answer is the fresh deal; refresh the lists and figures, not this page.
    void qc.invalidateQueries({ queryKey: DESK_KEY, predicate: (q) => q.queryKey[2] !== "deal" });
  };
  const act = useMutation({
    mutationFn: (run: () => Promise<Deal>) => run(),
    onSuccess: (d) => {
      setError(null);
      setSheet(null);
      fresh(d);
    },
    onError: (e) => {
      setError(e);
      setSheet(null);
    },
  });
  /** For forms that show their own refusal: saves and refreshes, or rejects. */
  const commit = async (run: () => Promise<Deal>) => {
    fresh(await run());
  };
  const d = deal.data;
  if (!d) {
    return deal.isError ? (
      <DeskError
        error={deal.error}
        back
        onRetry={() => {
          void deal.refetch();
        }}
      />
    ) : (
      <div aria-busy="true" className="bg-surface h-64 animate-pulse rounded-lg" />
    );
  }
  const run = (call: () => Promise<Deal>) => act.mutateAsync(call).catch(() => undefined);
  const safe = d.protected_until !== null && new Date(d.protected_until) <= new Date();
  const removable = !FINAL.has(d.status) && !d.items.some((i) => LOCKED.has(i.state));
  const status = d.status;
  return (
    <section className="space-y-4">
      <PageHeader
        title={d.trader}
        back={{ to: "/desk", label: "Мои сделки" }}
        badges={
          <StatusChip tone={DEAL_STATUS[status].tone}>{DEAL_STATUS[status].label}</StatusChip>
        }
        meta={
          <>
            <When iso={d.created_at} /> · {METHOD[d.method]}
          </>
        }
      />
      {status === "reverted" && (
        <p className="border-danger text-danger rounded-lg border p-3" role="status">
          Трейдер откатил обмен: Skinslink забрал деньги, скины вернулись к трейдеру.
        </p>
      )}
      {d.protected_until && status !== "reverted" && (
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
      <DealSummary
        deal={d}
        busy={act.isPending}
        onSavePrice={(body) => commit(() => patchDeal(d.id, body))}
        onEdit={() => {
          setSheet("edit");
        }}
        onRelease={
          d.method === "guarantor" && d.guarantor_released_at === null
            ? () => {
                if (safe) void run(() => patchDeal(d.id, { guarantor_released: true }));
                else setSheet("guarantor");
              }
            : null
        }
      />
      <ul className="divide-border border-border divide-y rounded-lg border" aria-label="Скины">
        {d.items.map((i) => (
          <ItemRow key={i.id} item={i} act={run} busy={act.isPending} removable={removable} />
        ))}
      </ul>
      {removable && <AddItems deal={d} onAdd={(items) => commit(() => addItems(d.id, items))} />}
      <SendBar
        deal={d}
        busy={act.isPending}
        onOpen={() => {
          setSheet("send");
        }}
        onEdit={() => {
          setSheet("edit");
        }}
      />
      {d.deposits.map((x) => (
        <DepositCard key={x.id} deposit={x} />
      ))}
      {isHand(status) && (
        <Button
          variant="secondary"
          className={TAP}
          onClick={() => {
            setSheet("status");
          }}
        >
          Сменить статус
        </Button>
      )}
      {sheet === "send" && (
        <SendSheet
          deal={d}
          busy={act.isPending}
          onClose={() => {
            setSheet(null);
          }}
          onSend={(ids) => {
            act.mutate(() => (ids ? sendDeposit(d.id, ids) : sendDeposit(d.id)));
          }}
        />
      )}
      {sheet === "edit" && (
        <DealEditSheet
          deal={d}
          onClose={() => {
            setSheet(null);
          }}
          onSave={(body) => commit(() => patchDeal(d.id, body))}
        />
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
                void run(() => patchDeal(d.id, { guarantor_released: true }));
              }}
            >
              Всё равно подтвердить
            </Button>
          </div>
        </ConfirmSheet>
      )}
      {sheet === "status" && isHand(status) && (
        <StatusSheet
          current={status}
          busy={act.isPending}
          onClose={() => {
            setSheet(null);
          }}
          onSave={(next) => {
            void run(() => patchDeal(d.id, { status: next } satisfies DealPatch));
          }}
        />
      )}
    </section>
  );
}
