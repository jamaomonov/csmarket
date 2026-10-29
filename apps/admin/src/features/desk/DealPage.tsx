/**
 * One deal: its status, price, items with their actions, the Skinslink offer and its state,
 * «защита до», the profit so far (spec 2026-10-29-desk).
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  type Deal,
  type DealStatus,
  DESK_KEY,
  type DeskItem,
  getDeal,
  moveItem,
  patchDeal,
  sendDeposit,
  writeOff,
} from "./api";
import { DEAL_STATUS, DEPOSIT_STATUS, deskErrorText, ITEM_STATE, METHOD } from "./labels";
import { PriceEditor } from "./PriceEditor";
import { SellForm } from "./SellForm";

import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { SkinThumb } from "@/components/SkinThumb";
import { StatusChip } from "@/components/StatusChip";
import { When } from "@/components/When";

const OPEN_DEPOSIT = new Set(["creating", "new", "pending", "active"]);

export function DealPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const key = [...DESK_KEY, "deal", id];
  const deal = useQuery({ queryKey: key, queryFn: () => getDeal(id) });
  const [error, setError] = useState<unknown>(null);
  const act = useMutation({
    mutationFn: (run: () => Promise<Deal>) => run(),
    onSuccess: (d) => {
      setError(null);
      qc.setQueryData(key, d);
      // The answer is the fresh deal; refresh the lists and figures, not this page.
      void qc.invalidateQueries({ queryKey: DESK_KEY, predicate: (q) => q.queryKey[2] !== "deal" });
    },
    onError: setError,
  });
  const d = deal.data;
  if (!d) return deal.isError ? <p className="text-danger">{deskErrorText(deal.error)}</p> : null;

  const sendable =
    d.trade_link !== null &&
    !d.deposits.some((x) => OPEN_DEPOSIT.has(x.status)) &&
    d.items.some((i) => i.destination === "skinslink" && i.state === "open" && i.asset_id);
  const protectedPast = d.protected_until !== null && new Date(d.protected_until) < new Date();
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
      />
      {d.status === "reverted" && (
        <p className="border-danger text-danger rounded-lg border p-3" role="status">
          Трейдер откатил обмен: Skinslink забрал деньги, скины вернулись к трейдеру.
        </p>
      )}
      {error !== null && (
        <p role="alert" className="text-danger">
          {deskErrorText(error)}
        </p>
      )}
      <div className="border-border bg-surface flex flex-wrap items-center gap-4 rounded-lg border p-3">
        <span>
          Прибыль {d.resolved ? "" : "пока"}: <Money usd={d.profit_usd} signed />
        </span>
        {d.protected_until && (
          <span className="text-fg-muted text-sm">
            защита до <When iso={d.protected_until} />
          </span>
        )}
        {d.method === "guarantor" && d.guarantor_released_at === null && (
          <Button
            size="sm"
            variant={protectedPast ? "primary" : "secondary"}
            onClick={() => {
              act.mutate(() => patchDeal(d.id, { guarantor_released: true }));
            }}
          >
            Подтвердил гаранту
          </Button>
        )}
        {d.guarantor_released_at && (
          <span className="text-sm">
            гаранту подтверждено <When iso={d.guarantor_released_at} />
          </span>
        )}
        <label className="ml-auto flex items-center gap-2 text-sm">
          Статус
          <select
            value={d.status}
            onChange={(e) => {
              const status = e.target.value as DealStatus; // one of the options below
              act.mutate(() => patchDeal(d.id, { status }));
            }}
            className="border-border bg-bg h-10 rounded-md border px-2"
          >
            {(Object.keys(DEAL_STATUS) as DealStatus[]).map((s) => (
              <option key={s} value={s}>
                {DEAL_STATUS[s].label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <PriceEditor
        deal={d}
        onSave={(body) => {
          act.mutate(() => patchDeal(d.id, body));
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
          />
        ))}
      </ul>
      {sendable && (
        <Button
          disabled={act.isPending}
          onClick={() => {
            act.mutate(() => sendDeposit(d.id));
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
            {x.amount_usd && (
              <>
                Skinslink: {x.amount_estimated ? "≈ " : ""}
                <Money usd={x.amount_usd} /> ·{" "}
              </>
            )}
            {x.fail_reason && <>причина: {x.fail_reason}</>}
          </p>
        </div>
      ))}
    </section>
  );
}

function ItemRow({ item, act }: { item: DeskItem; act: (run: () => Promise<Deal>) => void }) {
  const [mode, setMode] = useState<"sell" | "off" | null>(null);
  const [note, setNote] = useState("");
  const open = item.state === "open";
  return (
    <li className="px-3 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <SkinThumb url={item.image_url} />
        <span className="min-w-0 flex-1">
          <span className="block truncate">{item.name}</span>
          <span className="text-fg-muted text-xs">
            {item.destination === "stock" ? "себе" : "в Skinslink"} · {ITEM_STATE[item.state]}
            {item.skinslink_usd && <> · Skinslink ${item.skinslink_usd}</>}
            {item.sold_where && <> · {item.sold_where}</>}
          </span>
        </span>
        <span className="text-sm">{item.cost_usd ? <Money usd={item.cost_usd} /> : "—"}</span>
        {open && (
          <span className="flex flex-wrap gap-1">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                act(() => moveItem(item.id, item.destination === "stock" ? "skinslink" : "stock"));
              }}
            >
              {item.destination === "stock" ? "В Skinslink" : "Себе"}
            </Button>
            {item.destination === "stock" && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  setMode("sell");
                }}
              >
                Продал…
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setMode("off");
              }}
            >
              Списать
            </Button>
          </span>
        )}
      </div>
      {mode === "sell" && (
        <SellForm
          itemId={item.id}
          onDone={() => {
            setMode(null);
          }}
        />
      )}
      {mode === "off" && (
        <form
          className="mt-2 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (note.trim()) act(() => writeOff(item.id, note.trim()));
          }}
        >
          <input
            aria-label="Почему списать"
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
            }}
            className="border-border bg-bg h-10 flex-1 rounded-md border px-2"
          />
          <Button type="submit" size="sm" disabled={!note.trim()}>
            Списать
          </Button>
        </form>
      )}
    </li>
  );
}
