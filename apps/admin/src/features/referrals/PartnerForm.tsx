/** «Сделать партнёром» and a partner's terms: code, percent, term («Навсегда»), note, the switch. */
import { Button, Checkbox, Input } from "@csmarket/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type SubmitEvent, useState } from "react";

import {
  type AdminPartner,
  createPartner,
  type PartnerInput,
  type PartnerPatch,
  PARTNERS_KEY,
  updatePartner,
} from "./api";
import { MARGIN_WARNING, PERCENT_WARN, referralErrorText } from "./labels";

import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";

type PartnerFormProps = { onDone: (partner: AdminPartner) => void } & (
  { userId: string; partner?: undefined } | { partner: AdminPartner; userId?: undefined }
);

interface Draft {
  code: string;
  percent: string;
  months: string;
  forever: boolean;
  note: string;
  active: boolean;
}

const DEFAULT_TERM = 6;

function draftOf(p: AdminPartner | undefined): Draft {
  return {
    code: p?.code ?? "",
    percent: p?.percent ?? "1",
    months: String(p?.term_months ?? DEFAULT_TERM),
    forever: p?.term_months === null,
    note: p?.note ?? "",
    active: p?.active ?? true,
  };
}

function inputOf(d: Draft): PartnerInput {
  return {
    code: d.code.trim(),
    percent: d.percent.trim().replace(",", "."),
    term_months: d.forever ? null : Number(d.months),
    note: d.note.trim() === "" ? null : d.note.trim(),
  };
}

/** Only the fields that differ from what the server has. */
function patchOf(d: Draft, p: AdminPartner): PartnerPatch {
  const next = inputOf(d);
  const patch: PartnerPatch = {};
  if (next.code !== p.code) patch.code = next.code;
  if (Number(next.percent) !== Number(p.percent)) patch.percent = next.percent;
  if (next.term_months !== p.term_months) patch.term_months = next.term_months;
  if (next.note !== p.note) patch.note = next.note;
  if (d.active !== p.active) patch.active = d.active;
  return patch;
}

const field = "flex flex-col gap-1 text-sm";

export function PartnerForm({ userId, partner, onDone }: PartnerFormProps) {
  const qc = useQueryClient();
  const [d, setD] = useState<Draft>(() => draftOf(partner));
  const key = useIdempotencyKey("admin-partner");
  const set = (patch: Partial<Draft>) => {
    setD((prev) => ({ ...prev, ...patch }));
  };
  const save = useMutation({
    mutationFn: (): Promise<AdminPartner> => {
      if (partner === undefined) {
        const body = inputOf(d);
        return createPartner(userId, body, key.keyFor(JSON.stringify(body)));
      }
      const patch = patchOf(d, partner);
      return updatePartner(partner.user_id, patch, key.keyFor(JSON.stringify(patch)));
    },
    onSuccess: (saved) => {
      key.reset();
      void qc.invalidateQueries({ queryKey: PARTNERS_KEY });
      onDone(saved);
    },
  });
  const locked = partner !== undefined && partner.totals.accounts > 0;
  const warn = Number(d.percent.replace(",", ".")) > PERCENT_WARN;
  const onSubmit = (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <label className={field}>
        Код ссылки
        <Input
          aria-label="Код ссылки"
          value={d.code}
          disabled={locked}
          maxLength={32}
          placeholder="zufarmax"
          onChange={(e) => {
            set({ code: e.target.value });
          }}
        />
        <span className="text-fg-muted text-xs">
          {locked
            ? "Код нельзя менять: по ссылке уже пришли люди."
            : `Ссылка: csmarket.uz/?ref=${d.code.trim() || "код"}. Латиница, цифры и дефис.`}
        </span>
      </label>
      <label className={field}>
        Процент с покупок
        <Input
          inputMode="decimal"
          value={d.percent}
          onChange={(e) => {
            set({ percent: e.target.value });
          }}
          className="max-w-32"
        />
      </label>
      {warn ? (
        <p role="status" className="text-warning text-sm">
          {MARGIN_WARNING}
        </p>
      ) : null}
      <div className="flex flex-wrap items-end gap-4">
        <label className={field}>
          Срок, месяцев
          <Input
            type="number"
            min={1}
            max={120}
            value={d.months}
            disabled={d.forever}
            onChange={(e) => {
              set({ months: e.target.value });
            }}
            className="max-w-32"
          />
        </label>
        <Checkbox
          checked={d.forever}
          onChange={(e) => {
            set({ forever: e.target.checked });
          }}
        >
          Навсегда
        </Checkbox>
      </div>
      <label className={field}>
        Заметка
        <textarea
          aria-label="Заметка"
          value={d.note}
          maxLength={1000}
          rows={2}
          onChange={(e) => {
            set({ note: e.target.value });
          }}
          className="border-border bg-bg rounded-md border px-3 py-2 text-base"
        />
        <span className="text-fg-muted text-xs">Видят только админы.</span>
      </label>
      {partner !== undefined ? (
        <Checkbox
          checked={d.active}
          onChange={(e) => {
            set({ active: e.target.checked });
          }}
        >
          Активен
        </Checkbox>
      ) : null}
      {save.isError ? (
        <p role="alert" className="text-danger text-sm">
          {referralErrorText(save.error)}
        </p>
      ) : null}
      <Button type="submit" className="self-start" disabled={save.isPending}>
        {partner === undefined ? "Сделать партнёром" : "Сохранить"}
      </Button>
    </form>
  );
}
