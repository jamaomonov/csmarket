import {
  Accordion,
  Badge,
  Button,
  Checkbox,
  CheckMark,
  Chip,
  Dropdown,
  Input,
  Logo,
  LogoMark,
  Panel,
  Select,
  Switch,
} from "@csmarket/ui";
import { notFound } from "next/navigation";

import type { Metadata } from "next";

export const metadata: Metadata = { title: "UI", robots: { index: false, follow: false } };

const SWATCHES = [
  "bg",
  "surface",
  "surface-2",
  "surface-hover",
  "border",
  "border-strong",
  "fg",
  "fg-muted",
  "fg-dim",
  "accent",
  "accent-soft",
  "accent-subtle",
  "success",
  "danger",
  "warning",
  "info",
  "rarity-consumer",
  "rarity-industrial",
  "rarity-milspec",
  "rarity-restricted",
  "rarity-classified",
  "rarity-covert",
  "rarity-contraband",
  "stattrak",
] as const;

/** Throws Next's 404 in production: the showcase is a dev tool. */
export function assertDevOnly(): void {
  if (process.env.NODE_ENV === "production") notFound();
}

function Section({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-title font-semibold">{name}</h2>
      <div className="flex flex-wrap items-start gap-3">{children}</div>
    </section>
  );
}

export function Showcase() {
  return (
    <main className="mx-auto max-w-[1320px] space-y-10 px-6 py-8">
      <h1 className="text-h2 font-semibold">Design system</h1>
      <Section name="Tokens">
        {SWATCHES.map((s) => (
          <div key={s} className="w-40">
            <div
              className="border-border h-12 rounded-md border"
              style={{ background: `var(--color-${s})` }}
            />
            <p className="text-fg-muted text-label mt-1 font-mono">{`--color-${s}`}</p>
          </div>
        ))}
      </Section>
      <Section name="Button">
        <Button>Войти через Steam</Button>
        <Button variant="secondary">Вторичная</Button>
        <Button variant="ghost">Тихая</Button>
        <Button variant="danger">Опасная</Button>
        <Button size="sm">Малая</Button>
        <Button disabled>Недоступна</Button>
      </Section>
      <Section name="Chip">
        <Chip active>Все</Chip>
        <Chip>Ножи</Chip>
        <Chip>Кейсы</Chip>
      </Section>
      <Section name="Badge">
        <Badge>−19%</Badge>
        <Badge tone="neutral">MW</Badge>
        <Badge tone="danger">Ошибка</Badge>
      </Section>
      <Section name="Input">
        <Input placeholder="От" className="w-40" />
        <Input placeholder="Название скина…" className="w-80" />
      </Section>
      <Section name="Select">
        <Select defaultValue="a" aria-label="Сортировка">
          <option value="a">Сначала дороже</option>
          <option value="b">Сначала дешевле</option>
        </Select>
      </Section>
      <Section name="Checkbox">
        <Checkbox>Только StatTrak™</Checkbox>
        <span className="text-body flex items-center gap-2">
          <CheckMark checked /> CheckMark
        </span>
      </Section>
      <Section name="Switch">
        <Switch
          label="Выкуп"
          states={["включён", "выключен"]}
          checked
          onCheckedChange={() => {
            /* the showcase acts on nothing */
          }}
        />
        <Switch
          label="Доверенный"
          states={["да", "нет"]}
          checked={false}
          onCheckedChange={() => {
            /* the showcase acts on nothing */
          }}
        />
        <Switch
          label="Недоступен"
          checked={false}
          disabled
          onCheckedChange={() => {
            /* the showcase acts on nothing */
          }}
        />
      </Section>
      <Section name="Dropdown">
        <Dropdown
          label="Jam ▾"
          items={[
            { key: "p", label: "Профиль и трейд-ссылка", href: "#" },
            { key: "o", label: "Трейды", href: "#", meta: "3" },
            { key: "s", separator: true },
            {
              key: "x",
              label: "Выйти",
              tone: "danger",
              onSelect: () => {
                /* the showcase acts on nothing */
              },
            },
          ]}
        />
      </Section>
      <Section name="Accordion">
        <Panel className="w-64">
          <Accordion title="Качество" defaultOpen>
            <p className="text-fg-muted text-body">Прямо с завода</p>
          </Accordion>
          <Accordion title="Редкость">
            <p className="text-fg-muted text-body">Covert</p>
          </Accordion>
        </Panel>
      </Section>
      <Section name="Logo">
        <div className="flex items-center gap-6">
          <Logo />
          <Logo className="text-lg" />
          <LogoMark className="text-accent size-8" />
          <LogoMark className="text-fg size-8" />
        </div>
      </Section>
      <Section name="Panel">
        <Panel className="w-64">Панель: фильтры, тулбар, блоки.</Panel>
      </Section>
    </main>
  );
}

export default function DevUiPage() {
  assertDevOnly();
  return <Showcase />;
}
