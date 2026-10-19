/**
 * «Аналитика» (spec 2026-10-19-analytics): gross profit by day and period, in soʻm and USD.
 * The period and the channel live in the URL (`?p=30`, `?m=2026-10`, `?from=…&to=…`, `?ch=api`).
 */
import { type Channel } from "./api";
import { BusinessTab } from "./BusinessTab";
import { fromParams, monthOf, type Period, tashkentToday, toParams, windowOf } from "./period";

import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

const CHANNELS: readonly Channel[] = ["all", "site", "api"];
const CHANNEL_LABELS: Record<Channel, string> = { all: "Всё", site: "Сайт", api: "API" };

type Preset = "7" | "30" | "90" | "month" | "custom";

function presetOf(p: Period, today: string): Preset {
  if (p.kind === "days") return p.days === 7 ? "7" : p.days === 90 ? "90" : "30";
  if (p.kind === "month" && p.month === monthOf(today)) return "month";
  return "custom";
}

export function AnalyticsPage() {
  const url = useUrlParams();
  const today = tashkentToday();
  const period = fromParams(url.get);
  const channel = pick(CHANNELS, url.get("ch")) ?? "all";
  const span = windowOf(period, today);
  const setPeriod = (p: Period) => {
    for (const [k, v] of Object.entries(toParams(p))) url.set(k, v);
  };
  const preset = presetOf(period, today);
  return (
    <section className="space-y-4">
      <PageHeader title="Аналитика" />
      <div className="flex flex-wrap items-center gap-3">
        <Tabs<Preset>
          label="Период"
          variant="segmented"
          value={preset}
          onChange={(k) => {
            if (k === "custom") return;
            setPeriod(
              k === "month"
                ? { kind: "month", month: monthOf(today) }
                : { kind: "days", days: k === "7" ? 7 : k === "90" ? 90 : 30 },
            );
          }}
          items={[
            { key: "7", label: "7 дней" },
            { key: "30", label: "30 дней" },
            { key: "90", label: "90 дней" },
            { key: "month", label: "Этот месяц" },
            ...(preset === "custom" ? [{ key: "custom" as const, label: "Свой период" }] : []),
          ]}
        />
        <label className="text-fg-muted flex items-center gap-1 text-sm">
          с
          <input
            type="date"
            aria-label="С даты"
            className="border-border bg-surface rounded border px-2 py-1"
            value={span.since}
            max={span.until}
            onChange={(e) => {
              if (e.target.value)
                setPeriod({ kind: "range", since: e.target.value, until: span.until });
            }}
          />
          по
          <input
            type="date"
            aria-label="По дату"
            className="border-border bg-surface rounded border px-2 py-1"
            value={span.until}
            min={span.since}
            onChange={(e) => {
              if (e.target.value)
                setPeriod({ kind: "range", since: span.since, until: e.target.value });
            }}
          />
        </label>
        <Tabs<Channel>
          label="Канал"
          variant="segmented"
          value={channel}
          onChange={(k) => {
            url.set("ch", k === "all" ? "" : k);
          }}
          items={CHANNELS.map((c) => ({ key: c, label: CHANNEL_LABELS[c] }))}
        />
      </div>
      <BusinessTab span={span} channel={channel} />
    </section>
  );
}
