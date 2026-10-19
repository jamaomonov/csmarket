/** «Карты»: the cards buyers transfer to — masked, with limits and today's sum; add one. */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { addCard, listCards, type P2PCard, patchCard } from "./api";
import { cardsKey } from "./keys";

import { DataTable } from "@/components/DataTable";
import { Section } from "@/components/Section";
import { StatusChip } from "@/components/StatusChip";
import { errorText } from "@/features/users/labels";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatSum } from "@/lib/format";

const FIELD = "border-border bg-bg h-10 rounded-md border px-3";

function Field({
  label,
  value,
  onChange,
  inputMode,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  inputMode?: "numeric" | "text";
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <input
        value={value}
        inputMode={inputMode ?? "text"}
        autoComplete="off"
        onChange={(e) => {
          onChange(e.target.value);
        }}
        className={FIELD}
      />
    </label>
  );
}

function AddCard() {
  const qc = useQueryClient();
  const key = useIdempotencyKey("admin-p2p-card");
  const [pan, setPan] = useState("");
  const [holder, setHolder] = useState("");
  const [label, setLabel] = useState("");
  const [daily, setDaily] = useState("");
  const add = useMutation({
    mutationFn: () => {
      const body = {
        label: label.trim(),
        pan: pan.replace(/\D/g, ""),
        holder_name: holder.trim(),
        network: "humo" as const,
        min_amount_uzs: 10_000,
        max_amount_uzs: 5_000_000,
        daily_limit_uzs: daily.trim() ? Number(daily.replace(/\D/g, "")) : null,
      };
      // The key hides the number: only its last four tell two submissions apart.
      return addCard(body, key.keyFor(JSON.stringify({ ...body, pan: body.pan.slice(-4) })));
    },
    onSuccess: () => {
      key.reset();
      setPan("");
      void qc.invalidateQueries({ queryKey: cardsKey });
    },
  });
  return (
    <Section title="Новая карта">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Номер карты" value={pan} onChange={setPan} inputMode="numeric" />
        <Field label="Держатель" value={holder} onChange={setHolder} />
        <Field label="Название" value={label} onChange={setLabel} />
        <Field
          label="Лимит в день, сум (пусто — без лимита)"
          value={daily}
          onChange={setDaily}
          inputMode="numeric"
        />
      </div>
      <p className="text-fg-muted mt-2 text-sm">
        Номер вводится один раз и хранится зашифрованным. Последние 4 цифры не должны совпадать с
        картами второго проекта на том же боте — сверьте их там.
      </p>
      {add.isError && (
        <p role="alert" className="text-danger mt-2 text-sm">
          {errorText(add.error)}
        </p>
      )}
      <Button
        className="mt-3"
        disabled={
          pan.replace(/\D/g, "").length !== 16 || !holder.trim() || !label.trim() || add.isPending
        }
        onClick={() => {
          add.mutate();
        }}
      >
        Добавить карту
      </Button>
    </Section>
  );
}

function Toggle({ card }: { card: P2PCard }) {
  const qc = useQueryClient();
  const key = useIdempotencyKey("admin-p2p-card-toggle");
  const flip = useMutation({
    mutationFn: () => {
      const body = { active: !card.active };
      return patchCard(card.id, body, key.keyFor(JSON.stringify({ id: card.id, ...body })));
    },
    onSuccess: () => {
      key.reset();
      void qc.invalidateQueries({ queryKey: cardsKey });
    },
  });
  return (
    <Button
      size="sm"
      variant={card.active ? "secondary" : "primary"}
      disabled={flip.isPending}
      onClick={(e) => {
        e.stopPropagation();
        flip.mutate();
      }}
    >
      {card.active ? "Выключить" : "Включить"}
    </Button>
  );
}

export function CardsTab() {
  const q = useQuery({ queryKey: cardsKey, queryFn: listCards });
  return (
    <div className="space-y-4">
      <DataTable
        label="Карты P2P"
        rows={q.data?.items}
        loading={q.isPending}
        rowKey={(c) => c.id}
        empty="Карт пока нет."
        columns={[
          { key: "label", header: "Карта", cell: (c) => `${c.label} · ${c.masked}` },
          { key: "holder", header: "Держатель", cell: (c) => c.holder_name },
          {
            key: "limits",
            header: "Лимиты",
            cell: (c) =>
              `${formatSum(c.min_amount_uzs)} – ${formatSum(c.max_amount_uzs)}${c.daily_limit_uzs ? ` · в день ${formatSum(c.daily_limit_uzs)}` : ""}`,
          },
          { key: "today", header: "Сегодня", align: "right", cell: (c) => formatSum(c.today_uzs) },
          {
            key: "state",
            header: "Состояние",
            cell: (c) => (
              <StatusChip tone={c.active ? "success" : "muted"}>
                {c.active ? "включена" : "выключена"}
              </StatusChip>
            ),
          },
          { key: "toggle", header: "", cell: (c) => <Toggle card={c} /> },
        ]}
        mobileCard={(c) => (
          <div className="flex items-center justify-between gap-2 text-sm">
            <div>
              <div className="font-medium">
                {c.label} · {c.masked}
              </div>
              <div className="text-fg-muted text-xs">сегодня {formatSum(c.today_uzs)}</div>
            </div>
            <Toggle card={c} />
          </div>
        )}
      />
      <AddCard />
    </div>
  );
}
