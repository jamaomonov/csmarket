/** «P2P»: balance top-ups by card transfer — the journal, requests, cards and settings
 * (spec 2026-10-19-p2p-topup; runbook docs/runbooks/p2p.md). */
import { CardsTab } from "./CardsTab";
import { JournalTab } from "./JournalTab";
import { RequestsTab } from "./RequestsTab";
import { SettingsTab } from "./SettingsTab";

import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { pick } from "@/lib/url-guards";
import { useUrlParams } from "@/lib/useUrlParams";

type Tab = "journal" | "requests" | "cards" | "settings";
const TABS: readonly Tab[] = ["journal", "requests", "cards", "settings"];

export function P2PPage() {
  const url = useUrlParams();
  const tab = pick(TABS, url.get("tab")) ?? "journal";
  return (
    <section className="space-y-4">
      <PageHeader
        title="P2P-пополнения"
        meta="Переводы на карту, зачисляются по уведомлению HUMO"
      />
      <Tabs<Tab>
        label="Разделы P2P"
        value={tab}
        onChange={(next) => {
          url.set("tab", next === "journal" ? "" : next);
        }}
        items={[
          { key: "journal", label: "Журнал" },
          { key: "requests", label: "Заявки" },
          { key: "cards", label: "Карты" },
          { key: "settings", label: "Подключение и лимиты" },
        ]}
      />
      {tab === "journal" && <JournalTab />}
      {tab === "requests" && <RequestsTab />}
      {tab === "cards" && <CardsTab />}
      {tab === "settings" && <SettingsTab />}
    </section>
  );
}
