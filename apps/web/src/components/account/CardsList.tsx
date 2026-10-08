"use client";

import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { CARD_BRANDS } from "@/components/sell/PayoutPicker";
import { useAuth } from "@/lib/auth";
import { CARDS_KEY, deleteCard, listCards, mintCardKey } from "@/lib/sales";

interface CardsListProps {
  locale: string;
}

/** «Мои карты»: saved payout cards by brand and last four; a card is added with a sale. */
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
  if (cards.isPending)
    return <div aria-busy className="bg-surface h-24 animate-pulse rounded-lg" />;
  if (cards.isError) return <p className="text-fg-muted">{t("loadFailed")}</p>;
  if (cards.data.items.length === 0) return <p className="text-fg-muted">{t("empty")}</p>;
  return (
    <ul className="flex max-w-xl flex-col gap-2">
      {cards.data.items.map((c) => {
        const name = `${CARD_BRANDS[c.type]} •••• ${c.last4}`;
        return (
          <li
            key={c.id}
            className="bg-surface flex items-center justify-between gap-3 rounded-lg p-4"
          >
            <span className="num font-medium">{name}</span>
            <Button
              variant="secondary"
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
  );
}
