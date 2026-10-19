/** «Бизнес»: the period's tiles, profit by day and every breakdown. */
import { useQuery } from "@tanstack/react-query";

import { type Channel, getBusiness } from "./api";
import {
  Buyback,
  Buyers,
  Categories,
  Channels,
  Payments,
  Refunds,
  Sources,
  TopSkins,
} from "./Blocks";
import { DayChart } from "./charts/DayChart";
import { businessKey } from "./keys";
import { Losses } from "./Losses";
import { type Span } from "./period";
import { Tiles } from "./Tiles";

import { Section } from "@/components/Section";
import { ApiError, formatApiError } from "@/lib/api";

export function BusinessTab({ span, channel }: { span: Span; channel: Channel }) {
  const q = useQuery({
    queryKey: businessKey(span.since, span.until, channel),
    queryFn: () => getBusiness(span.since, span.until, channel),
  });
  if (q.isPending) return <p className="text-fg-muted">Загрузка…</p>;
  if (q.isError) {
    return (
      <p role="alert" className="text-danger">
        {q.error instanceof ApiError ? formatApiError(q.error) : "Не удалось загрузить."}
      </p>
    );
  }
  const data = q.data;
  return (
    <div className="space-y-4">
      <Tiles now={data.totals} before={data.previous} />
      <Section title="Прибыль по дням">
        <DayChart days={data.by_day} />
      </Section>
      <div className="grid gap-4 lg:grid-cols-2">
        <Sources data={data} />
        <Channels data={data} />
        <Payments data={data} />
        <Categories data={data} />
        <TopSkins data={data} />
        <Buyers data={data} />
        <Buyback data={data} />
        <Refunds data={data} />
      </div>
      <Losses span={span} channel={channel} />
    </div>
  );
}
