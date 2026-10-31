/**
 * «Отправить обмен»: a bar pinned above the bottom navigation on a phone, with how many skins and
 * what Skinslink gives for them — or why it cannot be sent (no price, no trade link, an offer
 * open). A cancelled deal has no bar. The sheet ticks the skins to send.
 */
import { Button } from "@csmarket/ui";
import { useState } from "react";

import { type Deal, type DeskItem } from "./api";
import { OPEN_DEPOSIT } from "./DepositCard";
import { skins, TAP } from "./Parts";
import { focusPrice } from "./PriceEditor";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";
import { Money } from "@/components/Money";

/** The skins an offer can carry now: bound for Skinslink, open, from the trader's inventory. */
export function sendable(d: Deal): DeskItem[] {
  return d.items.filter((i) => i.destination === "skinslink" && i.state === "open" && i.asset_id);
}

function worth(items: DeskItem[]): string {
  return items.reduce((s, i) => s + Number(i.skinslink_usd ?? 0), 0).toFixed(2);
}

interface SendBarProps {
  deal: Deal;
  busy: boolean;
  onOpen: () => void;
  /** No trade link: open «Изменить». */
  onEdit: () => void;
}

export function SendBar({ deal: d, busy, onOpen, onEdit }: SendBarProps) {
  const items = sendable(d);
  if (items.length === 0 || d.status === "cancelled") return null;
  const open = d.deposits.some((x) => OPEN_DEPOSIT.has(x.status));
  return (
    <div
      role="region"
      aria-label="Отправка"
      className="bg-bg/95 border-border bottom-(--bottom-nav) sticky z-20 -mx-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-t px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:rounded-lg sm:border sm:px-3"
    >
      <span className="text-sm">
        {skins(items.length)} · ≈ <Money usd={worth(items)} />
      </span>
      {d.paid_usd === null ? (
        <>
          <span className="text-warning text-sm">Сначала укажите, сколько заплатили.</span>
          <Button variant="secondary" className={`ml-auto ${TAP}`} onClick={focusPrice}>
            Указать цену
          </Button>
        </>
      ) : d.trade_link === null ? (
        <>
          <span className="text-warning text-sm">Нет трейд-ссылки — обмен не отправить.</span>
          <Button variant="secondary" className={`ml-auto ${TAP}`} onClick={onEdit}>
            Указать ссылку
          </Button>
        </>
      ) : open ? (
        <span className="text-fg-muted text-sm">
          Обмен уже идёт — следующий можно отправить, когда он закончится.
        </span>
      ) : (
        <Button className={`ml-auto w-full sm:w-auto ${TAP}`} disabled={busy} onClick={onOpen}>
          Отправить обмен
        </Button>
      )}
    </div>
  );
}

interface SendSheetProps {
  deal: Deal;
  busy: boolean;
  onClose: () => void;
  /** `undefined`: every sendable skin. */
  onSend: (itemIds?: string[]) => void;
}

export function SendSheet({ deal: d, busy, onClose, onSend }: SendSheetProps) {
  const items = sendable(d);
  const [ticked, setTicked] = useState<ReadonlySet<string>>(() => new Set(items.map((i) => i.id)));
  const chosen = items.filter((i) => ticked.has(i.id));
  const toggle = (id: string) => {
    const next = new Set(ticked);
    if (!next.delete(id)) next.add(id);
    setTicked(next);
  };
  return (
    <ConfirmSheet title="Отправить обмен трейдеру?" busy={busy} onClose={onClose}>
      <ul className="divide-border divide-y text-sm" aria-label="Скины в обмен">
        {items.map((i) => (
          <li key={i.id}>
            <label className="flex min-h-11 cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                className="accent-accent size-5 shrink-0"
                aria-label={i.name}
                checked={ticked.has(i.id)}
                onChange={() => {
                  toggle(i.id);
                }}
              />
              <span className="min-w-0 flex-1 truncate">{i.name}</span>
              {i.skinslink_usd && <Money usd={i.skinslink_usd} />}
            </label>
          </li>
        ))}
      </ul>
      <p className="text-sm">
        {skins(chosen.length)} · ≈ <Money usd={worth(chosen)} /> по ценам Skinslink. Цены Skinslink
        обновятся перед отправкой. Бот Skinslink пришлёт трейдеру обмен.
      </p>
      <div className={CONFIRM_BUTTONS}>
        <Button variant="secondary" className={TAP} disabled={busy} onClick={onClose}>
          Отмена
        </Button>
        <Button
          className={TAP}
          disabled={busy || chosen.length === 0}
          onClick={() => {
            onSend(chosen.length === items.length ? undefined : chosen.map((i) => i.id));
          }}
        >
          {busy ? "Отправляем…" : "Отправить"}
        </Button>
      </div>
    </ConfirmSheet>
  );
}
