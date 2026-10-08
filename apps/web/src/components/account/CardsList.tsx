"use client";

import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CreditCard } from "lucide-react";
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
  if (cards.isPending) {
    body = <div aria-busy className="bg-surface-2 mt-3 h-14 animate-pulse rounded-lg" />;
  } else if (cards.isError) {
    body = <p className="text-fg-muted mt-1 text-sm">{t("loadFailed")}</p>;
  } else if (cards.data.items.length === 0) {
    body = <p className="text-fg-muted mt-1 text-sm">{t("empty")}</p>;
  } else {
    body = (
      <div className="mt-3 flex flex-col gap-2">
        {forget.isError ? (
          <p role="alert" className="text-danger text-sm">
            {t("deleteFailed")}
          </p>
        ) : null}
        <ul className="flex flex-col gap-2">
          {cards.data.items.map((c) => {
            const name = `${CARD_BRANDS[c.type]} •••• ${c.last4}`;
            return (
              <li
                key={c.id}
                className="bg-surface-2 flex items-center gap-3 rounded-lg py-2 pl-2 pr-3"
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- static brand logos from /public */}
                <img
                  src={CARD_LOGOS[c.type]}
                  alt=""
                  width={60}
                  height={36}
                  className="h-9 w-auto shrink-0 rounded"
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold">{CARD_BRANDS[c.type]}</span>
                  <span className="num text-fg-muted block text-sm">•••• {c.last4}</span>
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  aria-label={t("delete", { name })}
                  disabled={forget.isPending}
                  onClick={() => {
                    forget.mutate(c.id);
                  }}
                >
                  {t("deleteShort")}
                </Button>
              </li>
            );
          })}
        </ul>
      </div>
    );
  }
  return (
    <SettingsCard icon={CreditCard} title={t("title")}>
      {body}
    </SettingsCard>
  );
}
