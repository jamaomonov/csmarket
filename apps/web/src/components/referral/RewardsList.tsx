"use client";

import { Button, cn } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { getRewards, type PartnerReward, type PartnerRewards, REWARDS_KEY } from "@/lib/referrals";

/** The partner's rewards, newest first, behind «Показать ещё»: amounts and dates only. */
export function RewardsList({ locale }: { locale: string }) {
  const t = useTranslations("web.referral");
  const common = useTranslations("common");
  const rewards = useInfiniteQuery<
    PartnerRewards,
    Error,
    InfiniteData<PartnerRewards, string | null>,
    typeof REWARDS_KEY,
    string | null
  >({
    queryKey: REWARDS_KEY,
    queryFn: ({ pageParam }) => getRewards(pageParam ?? undefined),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  let body;
  if (rewards.isPending) {
    body = <div aria-busy className="bg-surface h-24 animate-pulse rounded-md" />;
  } else if (rewards.isError) {
    body = <p className="text-fg-muted text-sm">{common("errors.generic")}</p>;
  } else {
    const items = rewards.data.pages.flatMap((page) => page.items);
    body =
      items.length === 0 ? (
        <p className="text-fg-muted text-sm">{t("rewardsEmpty")}</p>
      ) : (
        <ul className="divide-border divide-y">
          {items.map((r) => (
            <Row
              key={`${r.delivered_at}-${r.amount_uzs}-${r.base_uzs}`}
              reward={r}
              locale={locale}
            />
          ))}
        </ul>
      );
  }
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lead font-semibold">{t("rewards")}</h2>
      {body}
      {rewards.hasNextPage ? (
        <Button
          variant="secondary"
          className="self-start"
          disabled={rewards.isFetchingNextPage}
          onClick={() => {
            void rewards.fetchNextPage();
          }}
        >
          {t("more")}
        </Button>
      ) : null}
    </section>
  );
}

function Row({ reward, locale }: { reward: PartnerReward; locale: string }) {
  const t = useTranslations("web.referral");
  const day = new Intl.DateTimeFormat(locale, { dateStyle: "medium" });
  const status =
    reward.status === "held"
      ? t("status.held", { date: day.format(new Date(reward.available_at)) })
      : t(`status.${reward.status}`);
  return (
    <li className="flex items-center justify-between gap-4 py-3">
      <div className="min-w-0">
        <p className="font-semibold">
          {t("purchase", { sum: formatUzs(locale, reward.base_uzs) })}
        </p>
        <p className="text-fg-dim text-xs">
          <time dateTime={reward.delivered_at}>{day.format(new Date(reward.delivered_at))}</time>
          {" · "}
          <span className={cn(reward.status === "cancelled" && "text-danger")}>{status}</span>
        </p>
      </div>
      <p
        className={cn(
          "shrink-0 font-semibold tabular-nums",
          reward.status === "cancelled" ? "text-fg-dim line-through" : "text-success",
        )}
      >
        +{formatUzs(locale, reward.amount_uzs)}
      </p>
    </li>
  );
}
