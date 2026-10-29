/**
 * «Цена выкупа»: how much Skinslink pays for skins now and how much we would pay the seller —
 * by market names (one per line) or by a trade link's whole inventory. Reads only.
 */
import { Button } from "@csmarket/ui";
import { useMutation } from "@tanstack/react-query";
import { type ReactNode, type SubmitEvent, useState } from "react";

import { STEAM_REASONS } from "./labels";
import {
  type CardKind,
  checkSalePrices,
  type PriceCheck,
  type PriceCheckIn,
} from "./priceCheckApi";

import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { Section } from "@/components/Section";
import { SkinThumb } from "@/components/SkinThumb";
import { ApiError } from "@/lib/api";

const CARDS: Record<CardKind, string> = { uzcard: "Uzcard", humo: "Humo", uzum_visa: "Uzum Visa" };

export function checkErrorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "Не получилось. Попробуйте ещё раз.";
  if (err.code === "steam_refused") {
    const reason = (err.body as { reason?: string } | undefined)?.reason; // our problem+json body
    return `Steam не даёт обмениваться: ${STEAM_REASONS[reason ?? ""] ?? "аккаунт не может обмениваться"}.`;
  }
  if (err.code === "trade_link_invalid") return "Это не трейд-ссылка Steam.";
  if (err.code === "rate_unavailable") return "Нет свежего курса ЦБ — цену в сумах не посчитать.";
  if (err.status === 503) return "Skinslink сейчас не отвечает. Попробуйте через минуту.";
  if (err.status === 422) return "Проверьте ввод: до 200 названий или одна трейд-ссылка.";
  return "Не получилось. Попробуйте ещё раз.";
}

export function PriceCheckPage() {
  const [names, setNames] = useState("");
  const [link, setLink] = useState("");
  const check = useMutation({ mutationFn: (body: PriceCheckIn) => checkSalePrices(body) });

  function submitNames(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const list = names
      .split("\n")
      .map((n) => n.trim())
      .filter(Boolean);
    if (list.length > 0) check.mutate({ names: list });
  }
  function submitLink(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (link.trim()) check.mutate({ trade_link: link.trim() });
  }

  const input = "border-border bg-bg rounded-md border px-3";
  return (
    <section className="space-y-4">
      <PageHeader
        title="Цена выкупа"
        meta="Сколько платит Skinslink и сколько заплатим мы. Ничего не создаёт."
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="По названию">
          <form className="flex flex-col gap-3" onSubmit={submitNames}>
            <label className="flex flex-col gap-1 text-sm">
              Market hash name, по одному в строке
              <textarea
                rows={5}
                value={names}
                onChange={(e) => {
                  setNames(e.target.value);
                }}
                placeholder={"AK-47 | Redline (Field-Tested)\n★ Karambit | Doppler (Factory New)"}
                className={`${input} py-2 font-mono text-sm`}
              />
            </label>
            <Button type="submit" disabled={check.isPending || !names.trim()}>
              Проверить
            </Button>
          </form>
        </Section>
        <Section title="По трейд-ссылке">
          <form className="flex flex-col gap-3" onSubmit={submitLink}>
            <label className="flex flex-col gap-1 text-sm">
              Трейд-ссылка Steam
              <input
                value={link}
                onChange={(e) => {
                  setLink(e.target.value);
                }}
                placeholder="https://steamcommunity.com/tradeoffer/new/?partner=…&token=…"
                className={`${input} h-11`}
              />
            </label>
            <p className="text-fg-muted text-sm">
              Покажет скины, которые Skinslink берёт и которые можно передать сейчас.
            </p>
            <Button type="submit" disabled={check.isPending || !link.trim()}>
              Загрузить инвентарь
            </Button>
          </form>
        </Section>
      </div>
      {check.isPending && <p className="text-fg-muted">Спрашиваю Skinslink…</p>}
      {check.isError && (
        <p role="alert" className="text-danger">
          {checkErrorText(check.error)}
        </p>
      )}
      {check.data && <Result data={check.data} />}
    </section>
  );
}

function Result({ data }: { data: PriceCheck }) {
  const t = data.totals;
  return (
    <div className="space-y-4">
      {data.items.length === 0 ? (
        <p className="text-fg-muted">Skinslink ничего из этого сейчас не берёт.</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5" aria-label="Итоги">
            <Total title="Платит Skinslink">
              <Money usd={t.skinslink_usd} />{" "}
              <span className="text-fg-muted text-sm font-normal">
                (<Money uzs={t.skinslink_uzs} />)
              </span>
            </Total>
            <Total title="Наша маржа">
              <Money usd={t.margin_usd} />
            </Total>
            <Total title="Клиенту за скины">
              <Money uzs={t.items_uzs} />
            </Total>
            <Total title="На баланс (с бонусом)">
              <Money uzs={t.balance_uzs} />
            </Total>
            <Total title="На карту">
              <span className="flex flex-col text-sm">
                {(Object.keys(CARDS) as CardKind[]).map((k) => (
                  <span key={k}>
                    {CARDS[k]}: <Money uzs={t.card_uzs[k]} />
                  </span>
                ))}
              </span>
            </Total>
          </div>
          <div className="border-border overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="text-fg-muted text-left">
                <tr>
                  <th className="px-3 py-2">Скин</th>
                  <th className="px-3 py-2 text-right">Skinslink</th>
                  <th className="px-3 py-2 text-right">Клиенту</th>
                  <th className="px-3 py-2 text-right">Маржа</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((i, n) => (
                  <tr key={`${i.name}-${String(n)}`} className="border-border border-t">
                    <td className="px-3 py-2">
                      <span className="flex items-center gap-3">
                        <SkinThumb url={i.image_url} />
                        {i.name}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Money usd={i.skinslink_usd} />
                      <span className="text-fg-muted block text-xs">
                        (<Money uzs={i.skinslink_uzs} />)
                      </span>
                      {i.original_usd && i.original_usd !== i.skinslink_usd && (
                        <span className="text-fg-muted block text-xs">
                          без множителей <Money usd={i.original_usd} />
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Money uzs={i.price_uzs} />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Money usd={i.margin_usd} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-fg-muted text-xs">
            Сумы в скобках — по курсу ЦБ {data.cbu_rate}. Курс выкупа {data.rate} сум за $1 (ЦБ
            минус срез из настроек выкупа). «Клиенту» — до бонуса за баланс и комиссии карты.
          </p>
        </>
      )}
      {data.missing.length > 0 && (
        <div className="text-sm">
          <p className="text-fg-muted">Skinslink сейчас не берёт:</p>
          <ul className="list-inside list-disc">
            {data.missing.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Total({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border-border bg-surface rounded-lg border p-3">
      <p className="text-fg-muted text-xs">{title}</p>
      <div className="mt-1 font-semibold">{children}</div>
    </div>
  );
}
