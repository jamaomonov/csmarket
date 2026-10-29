/**
 * «Новая сделка»: the trader, their inventory as Skinslink prices it (tick the skins, each to
 * Skinslink or «Себе»), skins added by hand, the price in soʻm or dollars, how it was paid.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  createDeal,
  type Currency,
  DESK_KEY,
  type Destination,
  getRate,
  type InventoryItem,
  loadInventory,
  type Method,
  type NewDeal,
  type NewItem,
} from "./api";
import { deskErrorText, METHOD } from "./labels";
import { cleanAmount, CurrencySwitch } from "./SellForm";

import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { Section } from "@/components/Section";
import { SkinThumb } from "@/components/SkinThumb";
import { findItems } from "@/features/catalogue/api";
import { SkinSearch } from "@/features/catalogue/SkinSearch";

interface Picked {
  item: InventoryItem;
  destination: Destination;
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
  const value = cleanAmount(amount);
  const paidUsd =
    Number(value) > 0
      ? currency === "USD"
        ? Number(value)
        : Number(cleanAmount(shownRate)) > 0
          ? Number(value) / Number(cleanAmount(shownRate))
          : null
      : null;
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
  const ready =
    trader.trim() !== "" &&
    items.length > 0 &&
    (value === "" || (Number(value) > 0 && paidUsd !== null));

  const submit = () => {
    if (!ready) return;
    save.mutate({
      trader: trader.trim(),
      ...(note.trim() && { note: note.trim() }),
      ...(link.trim() && { trade_link: link.trim() }),
      method,
      items,
      ...(value !== "" && {
        paid_amount: value,
        paid_currency: currency,
        ...(currency === "UZS" && { rate: cleanAmount(shownRate) }),
      }),
    });
  };

  const toggle = (it: InventoryItem) => {
    setPicked((cur) => {
      if (cur[it.asset_id]) {
        return Object.fromEntries(Object.entries(cur).filter(([k]) => k !== it.asset_id));
      }
      return { ...cur, [it.asset_id]: { item: it, destination: "skinslink" } };
    });
  };
  const flip = (it: InventoryItem) => {
    setPicked((cur) => {
      const was = cur[it.asset_id];
      const destination: Destination = was?.destination === "stock" ? "skinslink" : "stock";
      return { ...cur, [it.asset_id]: { item: it, destination } };
    });
  };
  const input = "border-border bg-bg h-11 rounded-md border px-3";
  return (
    <section className="space-y-4">
      <PageHeader title="Новая сделка" back={{ to: "/desk", label: "Мои сделки" }} />
      <Section title="Кто продаёт">
        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            Трейдер
            <input
              value={trader}
              onChange={(e) => {
                setTrader(e.target.value);
              }}
              placeholder="Имя или ник в чате"
              className={input}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Заметка
            <input
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
              }}
              placeholder="Где договорились"
              className={input}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm md:col-span-2">
            Трейд-ссылка
            <input
              value={link}
              onChange={(e) => {
                setLink(e.target.value);
              }}
              placeholder="https://steamcommunity.com/tradeoffer/new/?partner=…&token=…"
              className={input}
            />
          </label>
        </div>
        <Button
          className="mt-3"
          variant="secondary"
          disabled={!link.trim() || inventory.isPending}
          onClick={() => {
            inventory.mutate();
          }}
        >
          Загрузить инвентарь
        </Button>
        {inventory.isError && (
          <p role="alert" className="text-danger mt-2">
            {deskErrorText(inventory.error)}
          </p>
        )}
      </Section>
      {inventory.data && (
        <Section title="Скины">
          {inventory.data.items.length === 0 && (
            <p className="text-fg-muted">Skinslink ничего из инвентаря не берёт.</p>
          )}
          <ul aria-label="Инвентарь трейдера" className="divide-border divide-y">
            {inventory.data.items.map((it) => {
              const p = picked[it.asset_id];
              return (
                <li key={it.asset_id} className="flex flex-wrap items-center gap-3 py-2">
                  <input
                    type="checkbox"
                    className="accent-accent size-5"
                    aria-label={it.name}
                    checked={p !== undefined}
                    onChange={() => {
                      toggle(it);
                    }}
                  />
                  <SkinThumb url={it.image_url} />
                  <span className="min-w-0 flex-1 truncate">{it.name}</span>
                  <Money usd={it.price_usd} />
                  <Button
                    size="sm"
                    variant={p?.destination === "stock" ? "primary" : "secondary"}
                    onClick={() => {
                      flip(it);
                    }}
                  >
                    {p?.destination === "stock" ? "В Skinslink" : "Себе"}
                  </Button>
                </li>
              );
            })}
          </ul>
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
              <li key={`${name}-${String(n)}`} className="flex items-center gap-2">
                {name} · себе
                <button
                  type="button"
                  className="text-accent underline"
                  onClick={() => {
                    setManual((m) => m.filter((_, k) => k !== n));
                  }}
                >
                  убрать
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Оплата">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Цена
            <input
              inputMode="decimal"
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value);
              }}
              placeholder="Сколько заплатил"
              className={`${input} w-44`}
            />
          </label>
          <CurrencySwitch value={currency} onChange={setCurrency} />
          {currency === "UZS" && (
            <label className="flex flex-col gap-1 text-sm">
              Курс
              <input
                inputMode="decimal"
                value={shownRate}
                onChange={(e) => {
                  setRate(e.target.value);
                }}
                className={`${input} w-28`}
              />
            </label>
          )}
          <label className="flex flex-col gap-1 text-sm">
            Как платил
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
        {paidUsd !== null && skinslinkSum > 0 && (
          <p className="mt-2 text-sm">
            Прибыль, если Skinslink заплатит как сейчас:{" "}
            <Money usd={(skinslinkSum - paidUsd).toFixed(2)} signed />
          </p>
        )}
        <p className="text-fg-muted mt-1 text-xs">
          Комиссию гаранта включайте в цену. Пустая цена — «договорились», без оплаты.
        </p>
      </Section>
      {save.isError && (
        <p role="alert" className="text-danger">
          {deskErrorText(save.error)}
        </p>
      )}
      <Button disabled={!ready || save.isPending} onClick={submit}>
        Сохранить сделку
      </Button>
    </section>
  );
}
