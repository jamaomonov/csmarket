/** «Изменить»: trader, trade link, how it was paid, the guarantor and the note; only what changed is sent. */
import { Button } from "@csmarket/ui";
import { useState } from "react";

import { type Deal, type DealPatch, type Method } from "./api";
import { deskErrorText } from "./labels";
import { MethodSwitch, TAP } from "./Parts";
import { TraderField } from "./TraderField";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";

interface DealEditSheetProps {
  deal: Deal;
  onClose: () => void;
  /** Resolves when saved; a rejection keeps the sheet open with its reason. */
  onSave: (body: DealPatch) => Promise<unknown>;
}

/** The fields that differ from the deal; a cleared note, link or guarantor is `null`. */
export function changes(
  d: Deal,
  v: { trader: string; link: string; method: Method; guarantor: string; note: string },
): DealPatch {
  const body: DealPatch = {};
  if (v.trader.trim() !== d.trader) body.trader = v.trader.trim();
  const link = v.link.trim() || null;
  if (link !== d.trade_link) body.trade_link = link;
  if (v.method !== d.method) body.method = v.method;
  const guarantor = v.method === "guarantor" ? v.guarantor.trim() || null : d.guarantor;
  if (guarantor !== d.guarantor) body.guarantor = guarantor;
  const note = v.note.trim() || null;
  if (note !== d.note) body.note = note;
  return body;
}

export function DealEditSheet({ deal: d, onClose, onSave }: DealEditSheetProps) {
  const [trader, setTrader] = useState(d.trader);
  const [link, setLink] = useState(d.trade_link ?? "");
  const [method, setMethod] = useState<Method>(d.method);
  const [guarantor, setGuarantor] = useState(d.guarantor ?? "");
  const [note, setNote] = useState(d.note ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const input = "border-border bg-bg h-11 rounded-md border px-3";
  const save = () => {
    const body = changes(d, { trader, link, method, guarantor, note });
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    setBusy(true);
    setError(null);
    onSave(body)
      .then(onClose)
      .catch(setError)
      .finally(() => {
        setBusy(false);
      });
  };
  return (
    <ConfirmSheet title="Изменить сделку" busy={busy} onClose={onClose}>
      <TraderField
        value={trader}
        onChange={setTrader}
        onPick={(t) => {
          setTrader(t.trader);
          if (!link.trim() && t.last_trade_link) setLink(t.last_trade_link);
        }}
      />
      <label className="flex flex-col gap-1 text-sm">
        Трейд-ссылка
        <input
          value={link}
          onChange={(e) => {
            setLink(e.target.value);
          }}
          placeholder="steamcommunity.com/tradeoffer/new/…"
          className={input}
        />
      </label>
      <MethodSwitch value={method} onChange={setMethod} />
      {method === "guarantor" && (
        <label className="flex flex-col gap-1 text-sm">
          Гарант
          <input
            value={guarantor}
            maxLength={120}
            onChange={(e) => {
              setGuarantor(e.target.value);
            }}
            placeholder="Ник гаранта"
            className={input}
          />
        </label>
      )}
      <label className="flex flex-col gap-1 text-sm">
        Заметка
        <textarea
          value={note}
          rows={3}
          onChange={(e) => {
            setNote(e.target.value);
          }}
          className="border-border bg-bg rounded-md border px-3 py-2"
        />
      </label>
      {error !== null && (
        <p role="alert" className="text-danger text-sm">
          {deskErrorText(error)}
        </p>
      )}
      <div className={CONFIRM_BUTTONS}>
        <Button variant="secondary" className={TAP} disabled={busy} onClick={onClose}>
          Отмена
        </Button>
        <Button className={TAP} disabled={busy || !trader.trim()} onClick={save}>
          {busy ? "Сохраняем…" : "Сохранить"}
        </Button>
      </div>
    </ConfirmSheet>
  );
}
