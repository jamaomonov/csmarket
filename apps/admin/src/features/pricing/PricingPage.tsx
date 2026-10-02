/**
 * «Цены»: the pricing document (edit, confirm, save — every price is recomputed), a preview
 * of the unsaved rules, and per-skin prices. M4b, ruling R8.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { getPricing, type PricingOut, savePricing } from "./api";
import { errorText } from "./labels";
import { OverrideCard } from "./OverrideCard";
import { PreviewCard } from "./PreviewCard";
import { fromRules, type RulesDraft, toRules } from "./rules-draft";
import { RulesForm } from "./RulesForm";

import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime, formatSum } from "@/lib/format";

const PRICING_KEY = ["pricing", "rules"] as const;
const count = (n: number): string => new Intl.NumberFormat("ru").format(n);

function StatusLine({ data }: { data: PricingOut }) {
  const parts = [
    `Активных скинов: ${count(data.items_active)}`,
    `с ручной ценой: ${count(data.items_overridden)}`,
    data.rate_uzs === null ? "курс неизвестен" : `курс: ${formatSum(data.rate_uzs)} за $1`,
  ];
  if (data.updated_at !== null) {
    const who = data.updated_by?.display_name ?? "администратор";
    parts.push(`правила обновил ${who} ${formatDateTime(data.updated_at)}`);
  } else {
    parts.push("правила по умолчанию");
  }
  return (
    <p data-testid="pricing-status" className="text-fg-muted text-sm">
      {parts.join(", ")}
    </p>
  );
}

export function PricingPage() {
  const qc = useQueryClient();
  const pricing = useQuery({ queryKey: PRICING_KEY, queryFn: getPricing });
  const [draft, setDraft] = useState<RulesDraft | null>(null);
  const [confirming, setConfirming] = useState(false);
  const idem = useIdempotencyKey("pricing");
  const inFlight = useRef(false);
  const save = useMutation({
    mutationFn: (d: RulesDraft) => {
      const rules = toRules(d);
      return savePricing(rules, idem.keyFor(JSON.stringify(rules)));
    },
    onSuccess: (saved) => {
      idem.reset();
      qc.setQueryData(PRICING_KEY, saved);
      setDraft(fromRules(saved.rules));
      setConfirming(false);
    },
    onError: () => {
      setConfirming(false);
    },
    onSettled: () => {
      inFlight.current = false;
    },
  });

  if (pricing.isError) {
    return (
      <p role="alert" className="text-danger">
        {errorText(pricing.error)}
      </p>
    );
  }
  if (!pricing.data) return <p className="text-fg-muted">Загрузка…</p>;
  const saved = fromRules(pricing.data.rules);
  const current = draft ?? saved;
  const dirty = JSON.stringify(current) !== JSON.stringify(saved);

  const confirm = (): void => {
    if (inFlight.current) return;
    inFlight.current = true;
    save.mutate(current);
  };
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold">Цены</h1>
        <StatusLine data={pricing.data} />
      </header>
      <RulesForm
        draft={current}
        dirty={dirty}
        saving={save.isPending}
        error={save.isError ? errorText(save.error) : null}
        onChange={setDraft}
        onReset={() => {
          setDraft(null);
          save.reset();
        }}
        onSave={() => {
          save.reset();
          setConfirming(true);
        }}
      />
      {confirming && (
        <div className="border-warning bg-surface flex flex-wrap items-center gap-3 rounded-lg border p-4">
          <span>Сохранить и пересчитать цены всех скинов?</span>
          <Button type="button" disabled={save.isPending} onClick={confirm}>
            Да, сохранить
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setConfirming(false);
            }}
          >
            Отмена
          </Button>
        </div>
      )}
      <PreviewCard rules={toRules(current)} />
      <OverrideCard />
    </div>
  );
}
