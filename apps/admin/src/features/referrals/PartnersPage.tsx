/** «Партнёры»: every partner with its numbers, most revenue first (spec 2026-10-27-referrals). */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { type AdminPartner, getPartners, PARTNERS_KEY } from "./api";
import { percentText, termText } from "./labels";

import { type Column, DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { LINK } from "@/components/TextLink";
import { formatSum } from "@/lib/format";

const COLUMNS: Column<AdminPartner>[] = [
  {
    key: "who",
    header: "Партнёр",
    cell: (p) => (
      <div className="min-w-0">
        <Link to={`/partners/${p.user_id}`} className={`${LINK} truncate`}>
          {p.display_name ?? "Без имени"}
        </Link>
        <div className="text-fg-dim truncate text-xs">{p.code}</div>
      </div>
    ),
  },
  {
    key: "terms",
    header: "Условия",
    cell: (p) => (
      <span className={p.active ? undefined : "text-fg-muted"}>
        {percentText(p.percent)} · {termText(p.term_months)}
        {p.active ? "" : " · отключён"}
      </span>
    ),
  },
  {
    key: "funnel",
    header: "Переходы → аккаунты → покупки",
    align: "right",
    cell: (p) =>
      `${String(p.totals.visits)} → ${String(p.totals.accounts)} → ${String(p.totals.purchases)}`,
  },
  {
    key: "revenue",
    header: "Выручка",
    align: "right",
    cell: (p) => formatSum(p.totals.revenue_uzs),
  },
  { key: "held", header: "В ожидании", align: "right", cell: (p) => formatSum(p.totals.held_uzs) },
  {
    key: "credited",
    header: "Начислено",
    align: "right",
    cell: (p) => formatSum(p.totals.credited_uzs),
  },
];

export function PartnersPage() {
  const q = useQuery({ queryKey: PARTNERS_KEY, queryFn: getPartners });
  return (
    <div className="space-y-6">
      <PageHeader
        title="Партнёры"
        meta="Сделать партнёром — на карточке пользователя. Процент начисляется с покупок приведённых аккаунтов через 8 дней."
      />
      <DataTable
        label="Партнёры"
        columns={COLUMNS}
        rows={q.data?.items}
        loading={q.isPending}
        error={q.isError ? "Не удалось загрузить партнёров." : undefined}
        empty="Партнёров пока нет."
        rowKey={(p) => p.user_id}
      />
    </div>
  );
}
