/**
 * «Новая сделка»: who sells, their inventory as Skinslink prices it (tick skins, each to
 * Skinslink or «Себе»), skins added by hand, what was paid and how. The total and the expected
 * profit stay pinned to the bottom with «Сохранить сделку».
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
import { deskErrorText, METHOD } from "./labels";
import { cleanAmount, TAP } from "./Parts";
import { CurrencySwitch, RateField, toUsd } from "./SellForm";

import { Money } from "@/components/Money";
import { MoneyInput } from "@/components/MoneyInput";
import { PageHeader } from "@/components/PageHeader";
import { Section } from "@/components/Section";
import { findItems } from "@/features/catalogue/api";
import { SkinSearch } from "@/features/catalogue/SkinSearch";

const STEAM_LINK_HELP = "https://steamcommunity.com/my/tradeoffers/privacy#trade_offer_access_url";

function skins(n: number): string {
  const last = n % 10;
  if (last === 1 && n % 100 !== 11) return `${String(n)} скин`;
  if (last >= 2 && last <= 4 && (n % 100 < 12 || n % 100 > 14)) return `${String(n)} скина`;
  return `${String(n)} скинов`;
}

export function NewDealPage() {
  const navigate = useNavigate();
  const [trader, setTrader] = useState("");
  const [note, setNote] = useState("");
  const [link, setLink] = useState("");
  const [picked, setPicked] = useState<Record<string, Picked>>({});
  const [manual, setManual] = useState<string[]>([]);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState<Currency>("UZS");
  const [rate, setRate] = useState<string | null>(null);
  const [method, setMethod] = useState<Method>("direct");
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
  const skinslinkSum = chosen.reduce((s, p) => s + Number(p.item.price_usd), 0);
  const items: NewItem[] = [
    ...chosen.map((p) => ({
      name: p.item.name,
      asset_id: p.item.asset_id,
      skinslink_usd: p.item.price_usd,
      destination: p.destination,
    })),
    ...manual.map((name) => ({ name, destination: "stock" as const })),
  ];
  const ready = trader.trim() !== "" && items.length > 0 && (amount === "" || paidUsd !== null);

  const submit = () => {
    if (!ready) return;
    save.mutate({
      trader: trader.trim(),
      ...(note.trim() && { note: note.trim() }),
      ...(link.trim() && { trade_link: link.trim() }),
      method,
      items,
      ...(amount !== "" && {
        paid_amount: cleanAmount(amount),
        paid_currency: currency,
        ...(currency === "UZS" && { rate: cleanAmount(shownRate) }),
      }),
    });
  };
  const input = "border-border bg-bg h-11 rounded-md border px-3";
  const field = (label: string, value: string, set: (v: string) => void, hint: string) => (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <input
        value={value}
        onChange={(e) => {
          set(e.target.value);
        }}
        placeholder={hint}
        className={input}
      />
    </label>
  );
  return (
    <section className="space-y-4 pb-28">
      <PageHeader title="Новая сделка" back={{ to: "/desk", label: "Мои сделки" }} />
      <Section title="Кто продаёт">
        <div className="grid gap-3 md:grid-cols-2">
          {field("Трейдер", trader, setTrader, "Имя или ник в чате")}
          {field("Заметка", note, setNote, "Где договорились")}
          <div className="md:col-span-2">
            {field("Трейд-ссылка", link, setLink, "steamcommunity.com/tradeoffer/new/…")}
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
        </div>
        <Button
          className={`mt-3 ${TAP}`}
          variant="secondary"
          disabled={!link.trim() || inventory.isPending}
          onClick={() => {
            inventory.mutate();
          }}
        >
          {inventory.isPending ? "Загружаем…" : "Загрузить инвентарь"}
        </Button>
        {inventory.isError && (
          <p role="alert" className="text-danger mt-2">
            {deskErrorText(inventory.error)}
          </p>
        )}
      </Section>
      {inventory.data && (
        <Section title="Скины трейдера">
          <InventoryPicker items={inventory.data.items} picked={picked} onChange={setPicked} />
          <p className="mt-2 text-sm">
            Skinslink сейчас даст за отмеченное: <Money usd={skinslinkSum} />
          </p>
        </Section>
      )}
      <Section title="Скины без инвентаря">
        <SkinSearch
          label="Добавить скин себе"
          find={(q) => findItems({ q })}
          onPick={(i) => {
            setManual((m) => [...m, i.name]);
          }}
        />
        {manual.length > 0 && (
          <ul className="mt-2 text-sm">
            {manual.map((name, n) => (
              <li key={`${name}-${String(n)}`} className="flex min-h-11 items-center gap-2">
                <span className="flex-1">{name} · себе</span>
                <Button
                  variant="secondary"
                  className={TAP}
                  onClick={() => {
                    setManual((m) => m.filter((_, k) => k !== n));
                  }}
                >
                  Убрать
                </Button>
              </li>
            ))}
          </ul>
        )}
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
          <label className="flex flex-col gap-1 text-sm">
            Способ оплаты
            <select
              value={method}
              onChange={(e) => {
                setMethod(e.target.value === "guarantor" ? "guarantor" : "direct");
              }}
              className={input}
            >
              <option value="direct">{METHOD.direct}</option>
              <option value="guarantor">{METHOD.guarantor}</option>
            </select>
          </label>
        </div>
        <p className="text-fg-muted mt-2 text-xs">
          Комиссию гаранта включите в цену. Ещё не заплатили — оставьте цену пустой.
        </p>
      </Section>
      {save.isError && (
        <p role="alert" className="text-danger">
          {deskErrorText(save.error)}
        </p>
      )}
      <div
        role="region"
        aria-label="Итог сделки"
        className="border-border bg-bg/95 bottom-(--bottom-nav) fixed inset-x-0 z-30 border-t px-4 py-3 backdrop-blur md:px-6 lg:bottom-0"
      >
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3">
          <span className="text-sm">
            {skins(items.length)}
            {paidUsd !== null && (
              <>
                {" "}
                · <Money usd={(-paidUsd).toFixed(2)} />
              </>
            )}
          </span>
          {paidUsd !== null && skinslinkSum > 0 && (
            <p className="text-sm">
              Прибыль, если Skinslink заплатит как сейчас:{" "}
              <Money usd={(skinslinkSum - paidUsd).toFixed(2)} signed />
            </p>
          )}
          <Button className={`ml-auto ${TAP}`} disabled={!ready || save.isPending} onClick={submit}>
            {save.isPending ? "Сохраняем…" : "Сохранить сделку"}
          </Button>
        </div>
      </div>
    </section>
  );
}
