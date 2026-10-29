/** One skin of a deal: where it goes, its state and cost, and what can be done with it. */
import { Button } from "@csmarket/ui";
import { useState } from "react";

import { type Deal, type DeskItem, moveItem, writeOff } from "./api";
import { itemState } from "./labels";
import { DestinationSwitch, TAP } from "./Parts";
import { SellForm } from "./SellForm";

import { DANGER_OUTLINE } from "@/components/ConfirmSheet";
import { Money } from "@/components/Money";
import { SkinThumb } from "@/components/SkinThumb";

interface ItemRowProps {
  item: DeskItem;
  act: (run: () => Promise<Deal>) => void;
  busy: boolean;
}

export function ItemRow({ item, act, busy }: ItemRowProps) {
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
            {itemState(item.state, item.destination)}
            {item.skinslink_usd && (
              <>
                {" "}
                · Skinslink <Money usd={item.skinslink_usd} />
              </>
            )}
            {item.sold_where && <> · {item.sold_where}</>}
          </span>
        </span>
        <span className="text-sm" title="Себестоимость">
          {item.cost_usd ? <Money usd={item.cost_usd} /> : "—"}
        </span>
      </div>
      {open && (
        <div className="mt-2 flex flex-wrap gap-2">
          <DestinationSwitch
            label={item.name}
            value={item.destination}
            disabled={busy}
            onChange={(d) => {
              act(() => moveItem(item.id, d));
            }}
          />
          {item.destination === "stock" && (
            <Button
              variant="secondary"
              className={TAP}
              onClick={() => {
                setMode("sell");
              }}
            >
              Продажа…
            </Button>
          )}
          <Button
            variant="secondary"
            className={`${TAP} ${DANGER_OUTLINE}`}
            onClick={() => {
              setMode("off");
            }}
          >
            Списать…
          </Button>
        </div>
      )}
      {mode === "sell" && (
        <SellForm
          itemId={item.id}
          costUsd={item.cost_usd}
          onDone={() => {
            setMode(null);
          }}
        />
      )}
      {mode === "off" && (
        <form
          className="mt-2 flex flex-wrap items-end gap-2 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            if (note.trim()) act(() => writeOff(item.id, note.trim()));
          }}
        >
          <label className="flex flex-1 flex-col gap-1">
            Почему списываете
            <input
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
              }}
              placeholder="Потерян, откат, отдан бесплатно…"
              className="border-border bg-bg h-11 rounded-md border px-2 sm:h-10"
            />
          </label>
          <Button
            type="button"
            variant="secondary"
            className={TAP}
            onClick={() => {
              setMode(null);
            }}
          >
            Отмена
          </Button>
          <Button
            type="submit"
            variant="secondary"
            className={`${TAP} ${DANGER_OUTLINE}`}
            disabled={!note.trim() || busy}
          >
            Списать
          </Button>
        </form>
      )}
    </li>
  );
}
