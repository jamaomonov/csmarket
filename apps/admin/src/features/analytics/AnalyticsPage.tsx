/**
 * «Аналитика» (spec 2026-10-19-analytics): gross profit by day and period, in soʻm and USD.
 * The period and the channel live in the URL (`?p=30`, `?m=2026-10`, `?from=…&to=…`, `?ch=api`).
 */
import { Button } from "@csmarket/ui";

import { type Channel } from "./api";
import { BusinessTab } from "./BusinessTab";
import { CalendarTab } from "./CalendarTab";
import {
  fromParams,
  monthOf,
  type Period,
  type Span,
  tashkentToday,
  toParams,
  windowOf,
} from "./period";

import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

const CHANNELS: readonly Channel[] = ["all", "site", "api"];
const CHANNEL_LABELS: Record<Channel, string> = { all: "Всё", site: "Сайт", api: "API" };

type Preset = "7" | "30" | "90" | "month" | "custom";
type Tab = "business" | "calendar";
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

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
    url.setAll({ ...toParams(p), back: "" });
  };
  const preset = presetOf(period, today);
  const tab: Tab = url.get("tab") === "calendar" ? "calendar" : "business";
  const calendarMonth = MONTH.test(url.get("cm")) ? url.get("cm") : monthOf(today);
  const openSpan = (s: Span) => {
    url.setAll({
      ...toParams({ kind: "range", since: s.since, until: s.until }),
      tab: "",
      back: "1",
    });
  };
  const channelTabs = (
    <Tabs<Channel>
      label="Канал"
      variant="segmented"
      value={channel}
      onChange={(k) => {
        url.set("ch", k === "all" ? "" : k);
      }}
      items={CHANNELS.map((c) => ({ key: c, label: CHANNEL_LABELS[c] }))}
    />
  );
  return (
    <section className="space-y-4">
      <PageHeader title="Аналитика" />
      <Tabs<Tab>
        label="Разделы аналитики"
        value={tab}
        onChange={(k) => {
          url.setAll({ tab: k === "calendar" ? "calendar" : "", back: "" });
        }}
        items={[
          { key: "business", label: "Бизнес" },
          { key: "calendar", label: "Календарь" },
        ]}
      />
      {tab === "calendar" ? (
        <>
          {channelTabs}
          <CalendarTab
            month={calendarMonth}
            channel={channel}
            onMonth={(m) => {
              url.set("cm", m);
            }}
            onOpen={openSpan}
          />
        </>
      ) : (
        <>
          {url.get("back") === "1" && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                url.setAll({ tab: "calendar", back: "" });
              }}
            >
              ← к календарю
            </Button>
          )}
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
            {channelTabs}
          </div>
          <BusinessTab span={span} channel={channel} />
        </>
      )}
    </section>
  );
}
