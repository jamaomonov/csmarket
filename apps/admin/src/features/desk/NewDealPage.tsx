/**
 * «Новая сделка», in the order a deal is made: the trader (a known one fills his last trade
 * link), the trade link and his inventory as Skinslink prices it, skins from our catalogue,
 * the payment and how, the note. «Заплачено · Skinslink · прибыль» stays pinned to the bottom.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  createDeal,
  type Currency,
  DESK_KEY,
  getRate,
  loadInventory,
  type Method,
  type NewDeal,
  type NewItem,
} from "./api";
import { InventoryPicker, type Picked } from "./InventoryPicker";
import { deskErrorText } from "./labels";
import { type ManualSkin, manualItems, ManualSkins, manualSum } from "./ManualSkins";
import { NewDealBar } from "./NewDealBar";
import { cleanAmount, MethodSwitch, TAP } from "./Parts";
import { CurrencySwitch, RateField, toUsd } from "./SellSheet";
import { TraderField } from "./TraderField";

import { MoneyInput } from "@/components/MoneyInput";
import { PageHeader } from "@/components/PageHeader";
import { Section } from "@/components/Section";

const STEAM_LINK_HELP = "https://steamcommunity.com/my/tradeoffers/privacy#trade_offer_access_url";
const INPUT = "border-border bg-bg h-11 rounded-md border px-3";

export function NewDealPage() {
  const navigate = useNavigate();
  const [trader, setTrader] = useState("");
  const [note, setNote] = useState("");
  const [link, setLink] = useState("");
  const [picked, setPicked] = useState<Record<string, Picked>>({});
  const [manual, setManual] = useState<ManualSkin[]>([]);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState<Currency>("UZS");
  const [rate, setRate] = useState<string | null>(null);
  const [method, setMethod] = useState<Method>("direct");
  const [guarantor, setGuarantor] = useState("");
  const cbu = useQuery({ queryKey: [...DESK_KEY, "rate"], queryFn: getRate });
  const inventory = useMutation({ mutationFn: () => loadInventory(link.trim()) });
  const save = useMutation({
    mutationFn: (body: NewDeal) => createDeal(body),
    onSuccess: (d) => {
      void navigate(`/desk/deals/${d.id}`);
    },
  });

  const shownRate = rate ?? cbu.data?.usd_uzs ?? "";
  const paidUsd = toUsd(amount, currency, shownRate);
  const chosen = Object.values(picked);
  const skinslinkSum = chosen.reduce((s, p) => s + Number(p.item.price_usd), 0) + manualSum(manual);
  const items: NewItem[] = [
    ...chosen.map((p) => ({
      name: p.item.name,
      asset_id: p.item.asset_id,
      ...(p.item.image_url ? { image_url: p.item.image_url } : {}),
      skinslink_usd: p.item.price_usd,
      destination: p.destination,
    })),
    ...manualItems(manual),
  ];
  const ready = trader.trim() !== "" && items.length > 0 && (amount === "" || paidUsd !== null);

  const submit = () => {
    if (!ready) return;
    save.mutate({
      trader: trader.trim(),
      ...(link.trim() && { trade_link: link.trim() }),
      method,
      ...(method === "guarantor" && guarantor.trim() && { guarantor: guarantor.trim() }),
      ...(note.trim() && { note: note.trim() }),
      items,
      ...(amount !== "" && {
        paid_amount: cleanAmount(amount),
        paid_currency: currency,
        ...(currency === "UZS" && { rate: cleanAmount(shownRate) }),
      }),
    });
  };
  return (
    <section className="space-y-4 pb-28">
      <PageHeader title="Новая сделка" back={{ to: "/desk", label: "Мои сделки" }} />
      <Section title="Кто продаёт">
        <div className="space-y-3">
          <TraderField
            value={trader}
            onChange={setTrader}
            onPick={(t) => {
              setTrader(t.trader);
              if (t.last_trade_link) setLink(t.last_trade_link);
            }}
          />
          <div>
            <label className="flex flex-col gap-1 text-sm">
              Трейд-ссылка
              <input
                value={link}
                onChange={(e) => {
                  setLink(e.target.value);
                }}
                placeholder="steamcommunity.com/tradeoffer/new/…"
                className={INPUT}
              />
            </label>
            <a
              href={STEAM_LINK_HELP}
              target="_blank"
              rel="noreferrer"
              className="text-accent text-xs underline"
            >
              где найти?
            </a>{" "}
            <span className="text-fg-muted text-xs">
              Трейдер присылает её сам; нужна для обмена через Skinslink.
            </span>
          </div>
          <Button
            className={TAP}
            variant="secondary"
            disabled={!link.trim() || inventory.isPending}
            onClick={() => {
              inventory.mutate();
            }}
          >
            {inventory.isPending ? "Загружаем…" : "Загрузить инвентарь"}
          </Button>
          {inventory.isError && (
            <p role="alert" className="text-danger">
              {deskErrorText(inventory.error)}
            </p>
          )}
        </div>
      </Section>
      {inventory.data && (
        <Section title="Скины трейдера">
          <InventoryPicker
            items={inventory.data.items}
            picked={picked}
            onChange={setPicked}
            rate={cbu.data?.usd_uzs ?? null}
          />
        </Section>
      )}
      <Section title="Скины из каталога">
        <ManualSkins value={manual} onChange={setManual} />
      </Section>
      <Section title="Оплата">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Сколько заплачено
            <MoneyInput
              label="Сколько заплачено"
              unit={currency === "UZS" ? "сум" : "$"}
              decimal={currency === "USD"}
              value={amount}
              onChange={setAmount}
              className="w-48"
            />
          </label>
          <CurrencySwitch value={currency} onChange={setCurrency} />
          {currency === "UZS" && <RateField value={shownRate} onChange={setRate} />}
        </div>
        <div className="mt-3 space-y-3">
          <MethodSwitch value={method} onChange={setMethod} />
          {method === "guarantor" && (
            <label className="flex max-w-sm flex-col gap-1 text-sm">
              Гарант
              <input
                value={guarantor}
                maxLength={120}
                onChange={(e) => {
                  setGuarantor(e.target.value);
                }}
                placeholder="Ник гаранта"
                className={INPUT}
              />
            </label>
          )}
        </div>
        <p className="text-fg-muted mt-2 text-xs">
          Комиссию гаранта включите в цену. Ещё не заплатили — оставьте цену пустой.
        </p>
      </Section>
      <Section title="Заметка" label="Заметка к сделке">
        <textarea
          aria-label="Заметка"
          value={note}
          rows={2}
          onChange={(e) => {
            setNote(e.target.value);
          }}
          placeholder="Где договорились"
          className="border-border bg-bg w-full rounded-md border px-3 py-2 text-sm"
        />
      </Section>
      {save.isError && (
        <p role="alert" className="text-danger">
          {deskErrorText(save.error)}
        </p>
      )}
      <NewDealBar
        paidUsd={paidUsd}
        skinslinkUsd={skinslinkSum}
        ready={ready}
        busy={save.isPending}
        onSave={submit}
      />
    </section>
  );
}
