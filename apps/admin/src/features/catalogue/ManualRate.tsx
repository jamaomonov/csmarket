/**
 * «Курс вручную»: when neither cbu.uz nor the fallback answers, the admin types today's CBU
 * rate; soʻm prices use it at once (runbook `fx-rate.md`).
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { setManualRate } from "./api";

import { CONFIRM_BUTTONS, ConfirmSheet } from "@/components/ConfirmSheet";
import { ApiError, formatApiError } from "@/lib/api";

const CBU = "https://cbu.uz/ru/arkhiv-kursov-valyut/";

/** `"12 004,02"` → `"12004.02"`. */
function clean(raw: string): string {
  return raw.replace(/\s/g, "").replace(",", ".");
}

export function ManualRate() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const rate = Number(clean(value));
  const plausible = rate >= 1000 && rate <= 100000;
  const save = useMutation({
    mutationFn: () => setManualRate(clean(value)),
    onSuccess: () => {
      setOpen(false);
      setValue("");
      void qc.invalidateQueries({ queryKey: ["catalogue", "status"] });
    },
  });
  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        className="mt-2 min-h-11 sm:min-h-8"
        onClick={() => {
          setOpen(true);
        }}
      >
        Курс вручную
      </Button>
      {open && (
        <ConfirmSheet
          title="Курс вручную"
          busy={save.isPending}
          onClose={() => {
            setOpen(false);
          }}
        >
          <p className="text-sm">
            Возьмите курс доллара на сегодня с{" "}
            <a href={CBU} target="_blank" rel="noreferrer" className="text-accent underline">
              cbu.uz
            </a>
            . Цены в сумах сразу пересчитаются по нему.
          </p>
          <label className="flex flex-col gap-1 text-sm">
            Курс ЦБ, сум
            <input
              inputMode="decimal"
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
              }}
              placeholder="12 004,02"
              className="border-border bg-bg h-11 rounded-md border px-3"
            />
          </label>
          {save.isError && (
            <p role="alert" className="text-danger text-sm">
              {save.error instanceof ApiError
                ? formatApiError(save.error)
                : "Не получилось. Попробуйте ещё раз."}
            </p>
          )}
          <div className={CONFIRM_BUTTONS}>
            <Button
              variant="secondary"
              disabled={save.isPending}
              onClick={() => {
                setOpen(false);
              }}
            >
              Отмена
            </Button>
            <Button
              disabled={!plausible || save.isPending}
              onClick={() => {
                save.mutate();
              }}
            >
              Сохранить курс
            </Button>
          </div>
        </ConfirmSheet>
      )}
    </>
  );
}
