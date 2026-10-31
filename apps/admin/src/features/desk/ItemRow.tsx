/**
 * One skin of a deal: where it goes, its state, cost and (sold) profit, and what can be done with
 * it. Rare or dangerous steps — «Убрать из сделки», «Списать…» — sit behind «⋯»; every one that
 * changes money asks first.
 */
import { Button } from "@csmarket/ui";
import { useState } from "react";

import { type Deal, type DeskItem, moveItem, removeItem, undoItem, writeOff } from "./api";
import { itemState } from "./labels";
import { DestinationSwitch, TAP } from "./Parts";
import { SellSheet } from "./SellSheet";

import { CONFIRM_BUTTONS, ConfirmSheet, DANGER_OUTLINE } from "@/components/ConfirmSheet";
import { Money } from "@/components/Money";
import { type MoreAction, MoreMenu } from "@/components/MoreMenu";
import { SkinThumb } from "@/components/SkinThumb";

interface ItemRowProps {
  item: DeskItem;
  /** Runs a change; settles either way (the page shows a refusal). */
  act: (run: () => Promise<Deal>) => Promise<unknown>;
  busy: boolean;
  /** «Убрать» is offered while the deal's price can still be split again. */
  removable: boolean;
  /** The deal is cancelled: no action on its skins. */
  frozen?: boolean;
}

type Mode = "sell" | "off" | "remove" | "undo" | null;

const UNDO: Partial<Record<DeskItem["state"], string>> = {
  sold: "Отменить продажу",
  written_off: "Отменить списание",
};

function Line({ item }: { item: DeskItem }) {
  const profit =
    item.state === "sold" && item.sold_usd !== null && item.cost_usd !== null
      ? (Number(item.sold_usd) - Number(item.cost_usd)).toFixed(2)
      : null;
  return (
    <span className="text-fg-muted text-xs">
      {itemState(item.state, item.destination)}
      {item.skinslink_usd && (
        <>
          {" "}
          · Skinslink <Money usd={item.skinslink_usd} />
        </>
      )}
      {item.sold_where && <> · {item.sold_where}</>}
      {profit !== null && (
        <>
          {" "}
          · <Money usd={profit} signed />
        </>
      )}
      {item.state === "written_off" && item.note && <> · {item.note}</>}
    </span>
  );
}

export function ItemRow({ item, act, busy, removable, frozen = false }: ItemRowProps) {
  const [mode, setMode] = useState<Mode>(null);
  const [note, setNote] = useState("");
  const close = () => {
    setMode(null);
  };
  const run = (call: () => Promise<Deal>) => {
    void act(call).finally(close);
  };
  const open = item.state === "open" && !frozen;
  const undo = UNDO[item.state];
  const menu: MoreAction[] = [
    ...(removable
      ? [
          {
            key: "remove",
            label: "Убрать из сделки",
            onSelect: () => {
              setMode("remove");
            },
          },
        ]
      : []),
    {
      key: "off",
      label: "Списать…",
      danger: true,
      onSelect: () => {
        setMode("off");
      },
    },
  ];
  return (
    <li className="px-3 py-3">
      <div className="flex items-center gap-3">
        <SkinThumb url={item.image_url} />
        <span className="min-w-0 flex-1">
          <span className="block truncate">{item.name}</span>
          <Line item={item} />
        </span>
        <span className="text-sm" title="Себестоимость">
          {item.cost_usd ? <Money usd={item.cost_usd} /> : "—"}
        </span>
      </div>
      {open && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {item.asset_id !== null || item.destination === "skinslink" ? (
            <DestinationSwitch
              label={item.name}
              value={item.destination}
              disabled={busy}
              onChange={(d) => {
                run(() => moveItem(item.id, d));
              }}
            />
          ) : (
            <span className="text-fg-muted text-xs">не из инвентаря — только себе</span>
          )}
          {item.destination === "stock" && (
            <Button
              variant="secondary"
              className={TAP}
              onClick={() => {
                setMode("sell");
              }}
            >
              Продал
            </Button>
          )}
          <span className="ml-auto">
            <MoreMenu actions={menu} label={`Ещё: ${item.name}`} size="size-11 sm:size-10" />
          </span>
        </div>
      )}
      {undo !== undefined && (
        <Button
          variant="secondary"
          className={`mt-2 ${TAP}`}
          onClick={() => {
            setMode("undo");
          }}
        >
          {undo}
        </Button>
      )}
      {mode === "sell" && <SellSheet item={item} onDone={close} />}
      {mode === "remove" && (
        <ConfirmSheet title="Убрать скин из сделки?" busy={busy} onClose={close}>
          <p className="text-sm">
            {item.name} уйдёт из сделки, цена сделки заново разделится на остальные скины.
          </p>
          <div className={CONFIRM_BUTTONS}>
            <Button variant="secondary" className={TAP} disabled={busy} onClick={close}>
              Отмена
            </Button>
            <Button
              className={TAP}
              disabled={busy}
              onClick={() => {
                run(() => removeItem(item.id));
              }}
            >
              Убрать
            </Button>
          </div>
        </ConfirmSheet>
      )}
      {mode === "undo" && undo !== undefined && (
        <ConfirmSheet title={`${undo}?`} busy={busy} onClose={close}>
          <p className="text-sm">
            Запись уйдёт из прибыли, скин снова будет{" "}
            {item.destination === "stock" ? "на складе" : "ждать отправки"}.
          </p>
          <div className={CONFIRM_BUTTONS}>
            <Button variant="secondary" className={TAP} disabled={busy} onClick={close}>
              Не отменять
            </Button>
            <Button
              className={TAP}
              disabled={busy}
              onClick={() => {
                run(() => undoItem(item.id));
              }}
            >
              {undo}
            </Button>
          </div>
        </ConfirmSheet>
      )}
      {mode === "off" && (
        <ConfirmSheet title="Списать скин" busy={busy} onClose={close}>
          <label className="flex flex-col gap-1 text-sm">
            Почему списываете
            <input
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
              }}
              placeholder="Потерян, отдан бесплатно…"
              className="border-border bg-bg h-11 rounded-md border px-3"
            />
          </label>
          <div className={CONFIRM_BUTTONS}>
            <Button variant="secondary" className={TAP} disabled={busy} onClick={close}>
              Отмена
            </Button>
            <Button
              variant="secondary"
              className={`${TAP} ${DANGER_OUTLINE}`}
              disabled={!note.trim() || busy}
              onClick={() => {
                run(() => writeOff(item.id, note.trim()));
              }}
            >
              Списать
            </Button>
          </div>
        </ConfirmSheet>
      )}
    </li>
  );
}
