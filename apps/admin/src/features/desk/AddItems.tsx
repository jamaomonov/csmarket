/**
 * «Добавить скин» after the deal was made: from the trader's inventory (when the deal has a trade
 * link) or from our catalogue with an estimate. The deal's price is split again on the server.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type Deal, DESK_KEY, getRate, loadInventory, type NewItem } from "./api";
import { InventoryPicker, type Picked } from "./InventoryPicker";
import { deskErrorText } from "./labels";
import { type ManualSkin, manualItems, ManualSkins } from "./ManualSkins";
import { skins, TAP } from "./Parts";

import { Section } from "@/components/Section";

interface AddItemsProps {
  deal: Deal;
  /** Resolves when added; a rejection keeps the form open with its reason. */
  onAdd: (items: NewItem[]) => Promise<unknown>;
}

function pickedItems(picked: Record<string, Picked>): NewItem[] {
  return Object.values(picked).map((p) => ({
    name: p.item.name,
    asset_id: p.item.asset_id,
    ...(p.item.image_url ? { image_url: p.item.image_url } : {}),
    skinslink_usd: p.item.price_usd,
    destination: p.destination,
  }));
}

export function AddItems({ deal: d, onAdd }: AddItemsProps) {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<Record<string, Picked>>({});
  const [manual, setManual] = useState<ManualSkin[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const link = d.trade_link;
  const cbu = useQuery({ queryKey: [...DESK_KEY, "rate"], queryFn: getRate, enabled: open });
  const inventory = useMutation({ mutationFn: (l: string) => loadInventory(l) });
  if (!open) {
    return (
      <Button
        variant="secondary"
        className={TAP}
        onClick={() => {
          setOpen(true);
        }}
      >
        Добавить скин
      </Button>
    );
  }
  const items = [...pickedItems(picked), ...manualItems(manual)];
  const inDeal = new Set(d.items.flatMap((i) => (i.asset_id ? [i.asset_id] : [])));
  const close = () => {
    setOpen(false);
    setPicked({});
    setManual([]);
    setError(null);
  };
  const add = () => {
    setBusy(true);
    setError(null);
    onAdd(items)
      .then(close)
      .catch(setError)
      .finally(() => {
        setBusy(false);
      });
  };
  return (
    <Section title="Добавить скины">
      <div className="space-y-3">
        {link !== null && (
          <Button
            variant="secondary"
            className={TAP}
            disabled={inventory.isPending}
            onClick={() => {
              inventory.mutate(link);
            }}
          >
            {inventory.isPending ? "Загружаем…" : "Загрузить инвентарь"}
          </Button>
        )}
        {inventory.isError && (
          <p role="alert" className="text-danger text-sm">
            {deskErrorText(inventory.error)}
          </p>
        )}
        {inventory.data && (
          <InventoryPicker
            items={inventory.data.items}
            picked={picked}
            onChange={setPicked}
            rate={cbu.data?.usd_uzs ?? null}
            exclude={inDeal}
          />
        )}
        <ManualSkins value={manual} onChange={setManual} />
        {error !== null && (
          <p role="alert" className="text-danger text-sm">
            {deskErrorText(error)}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" className={TAP} disabled={busy} onClick={close}>
            Отмена
          </Button>
          <Button className={TAP} disabled={busy || items.length === 0} onClick={add}>
            {busy ? "Добавляем…" : `Добавить ${skins(items.length)}`}
          </Button>
        </div>
      </div>
    </Section>
  );
}
