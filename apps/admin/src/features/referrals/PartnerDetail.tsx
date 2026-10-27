/** A partner's page: its terms (editable), months and rewards with their orders. */
import { Button } from "@csmarket/ui";
import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import {
  type AdminReward,
  getPartner,
  type PartnerDetail,
  type PartnerMonth,
  PARTNERS_KEY,
} from "./api";
import { percentText, REWARD_STATUS, termText } from "./labels";
import { PartnerForm } from "./PartnerForm";

import { type Column, DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { DetailGrid, Section } from "@/components/Section";
import { LINK } from "@/components/TextLink";
import { When } from "@/components/When";
import { formatSum } from "@/lib/format";

const MONTH = new Intl.DateTimeFormat("ru", { month: "long", year: "numeric" });

const MONTHS: Column<PartnerMonth>[] = [
  { key: "m", header: "Месяц", cell: (m) => MONTH.format(new Date(`${m.month}T00:00:00`)) },
  { key: "v", header: "Переходы", align: "right", cell: (m) => m.visits },
  { key: "a", header: "Аккаунты", align: "right", cell: (m) => m.accounts },
  { key: "p", header: "Покупки", align: "right", cell: (m) => m.purchases },
  { key: "r", header: "Выручка", align: "right", cell: (m) => formatSum(m.revenue_uzs) },
  { key: "e", header: "Заработано", align: "right", cell: (m) => formatSum(m.earned_uzs) },
];

const REWARDS: Column<AdminReward>[] = [
  {
    key: "order",
    header: "Заказ",
    cell: (r) => (
      <Link to={`/orders/${r.order_number}`} className={LINK}>
        {r.order_number}
      </Link>
    ),
  },
  { key: "at", header: "Доставлен", cell: (r) => <When iso={r.delivered_at} /> },
  { key: "base", header: "Покупка", align: "right", cell: (r) => formatSum(r.base_uzs) },
  {
    key: "amount",
    header: "Начисление",
    align: "right",
    cell: (r) => `${formatSum(r.amount_uzs)} · ${percentText(r.percent)}`,
  },
  {
    key: "status",
    header: "Статус",
    cell: (r) => (
      <span className={r.status === "cancelled" ? "text-danger" : undefined}>
        {REWARD_STATUS[r.status]}
        {r.status === "held" ? (
          <span className="text-fg-muted">
            {" до "}
            <When iso={r.available_at} />
          </span>
        ) : null}
      </span>
    ),
  },
];

/** The route: `/partners/:userId`. */
export function PartnerDetailRoute() {
  const { userId = "" } = useParams();
  return <PartnerDetailPage userId={userId} />;
}

export function PartnerDetailPage({ userId }: { userId: string }) {
  const q = useInfiniteQuery<
    PartnerDetail,
    Error,
    InfiniteData<PartnerDetail, string | null>,
    readonly string[],
    string | null
  >({
    queryKey: [...PARTNERS_KEY, "detail", userId],
    queryFn: ({ pageParam }) => getPartner(userId, pageParam),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const first = q.data?.pages[0];
  if (q.isError) return <p className="text-danger">Не удалось загрузить партнёра.</p>;
  if (first === undefined)
    return <div aria-busy className="bg-surface h-40 animate-pulse rounded-lg" />;
  const p = first.partner;
  const rewards = q.data?.pages.flatMap((page) => page.rewards);
  const main = (
    <>
      <Section title="По месяцам">
        <DataTable
          label="По месяцам"
          columns={MONTHS}
          rows={first.months}
          rowKey={(m) => m.month}
          empty="Пока ничего."
        />
      </Section>
      <Section title="Начисления">
        <DataTable
          label="Начисления"
          columns={REWARDS}
          rows={rewards}
          rowKey={(r) => r.order_number}
          empty="Начислений пока нет."
        />
        {q.hasNextPage ? (
          <Button
            variant="secondary"
            size="sm"
            className="self-start"
            disabled={q.isFetchingNextPage}
            onClick={() => {
              void q.fetchNextPage();
            }}
          >
            Показать ещё
          </Button>
        ) : null}
      </Section>
    </>
  );
  const side = (
    <Section title="Условия">
      <PartnerForm
        key={`${p.code}-${p.percent}-${String(p.term_months)}-${String(p.active)}`}
        partner={p}
        onDone={() => {
          void q.refetch();
        }}
      />
    </Section>
  );
  return (
    <div className="space-y-6">
      <PageHeader
        title={p.display_name ?? "Без имени"}
        back={{ to: "/partners", label: "Партнёры" }}
        meta={
          <>
            <Link to={`/users/${p.user_id}`} className={LINK}>
              Карточка пользователя
            </Link>
            {` · csmarket.uz/?ref=${p.code} · ${percentText(p.percent)} · ${termText(p.term_months)}`}
          </>
        }
      />
      <DetailGrid main={main} side={side} />
    </div>
  );
}
