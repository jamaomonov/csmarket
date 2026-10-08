"use client";

import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CreditCard, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { SettingsCard } from "./SettingsCard";

import { CARD_BRANDS, CARD_LOGOS } from "@/components/sell/PayoutPicker";
import { useAuth } from "@/lib/auth";
import { CARDS_KEY, deleteCard, listCards, mintCardKey } from "@/lib/sales";

interface CardsListProps {
  locale: string;
}

/** «Мои карты» on the profile: saved payout cards by brand logo and last four; a card is added with a sale. */
export function CardsList({ locale }: CardsListProps) {
  const t = useTranslations("web.cards");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const qc = useQueryClient();
  const cards = useQuery({ queryKey: CARDS_KEY, queryFn: listCards, enabled: signedIn });
  const forget = useMutation({
    mutationFn: (id: string) => deleteCard(id, mintCardKey()),
    onSuccess: () => qc.invalidateQueries({ queryKey: CARDS_KEY }),
  });
  if (!signedIn) {
    return status === "loading" ? (
      <div aria-busy className="bg-surface h-24 animate-pulse rounded-lg" />
    ) : (
      <a
        href={signInHref(locale)}
        className="bg-accent text-accent-fg w-fit rounded-md px-5 py-3 font-semibold"
      >
        {nav("signIn")}
      </a>
    );
  }
  let body;
  let hint: string | undefined;
  if (cards.isPending) {
    body = <div aria-busy className="bg-surface-2 mt-3 h-16 animate-pulse rounded-lg" />;
  } else if (cards.isError) {
    hint = t("loadFailed");
  } else if (cards.data.items.length === 0) {
    hint = t("empty");
  } else {
    hint = t("count", { count: cards.data.items.length });
    body = (
      <>
        {forget.isError ? (
          <p role="alert" className="text-danger mt-3 text-sm">
            {t("deleteFailed")}
          </p>
        ) : null}
        <ul className="mt-3 grid gap-2 sm:grid-cols-2">
          {cards.data.items.map((c) => {
            const name = `${CARD_BRANDS[c.type]} •••• ${c.last4}`;
            return (
              <li
                key={c.id}
                className="border-border bg-bg/40 flex items-center gap-3 rounded-lg border py-2 pl-2 pr-1.5"
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- static brand logos from /public */}
                <img
                  src={CARD_LOGOS[c.type]}
                  alt=""
                  width={60}
                  height={36}
                  className="h-9 w-auto shrink-0 rounded-md"
                />
                <span className="min-w-0 flex-1 leading-tight">
                  <span className="block text-sm font-semibold">{CARD_BRANDS[c.type]}</span>
                  <span className="num text-fg-muted mt-0.5 block text-[13px]">•••• {c.last4}</span>
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={t("delete", { name })}
                  title={t("deleteShort")}
                  disabled={forget.isPending}
                  className="hover:text-danger size-9 px-0"
                  onClick={() => {
                    forget.mutate(c.id);
                  }}
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </li>
            );
          })}
        </ul>
      </>
    );
  }
  return (
    <SettingsCard icon={CreditCard} title={t("title")} hint={hint}>
      {body}
    </SettingsCard>
  );
}
