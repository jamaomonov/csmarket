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

import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
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
      <PageHeader title="Цены" meta={<StatusLine data={pricing.data} />} />
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
        <Modal
          title="Сохранить наценки?"
          description="Цены всех скинов пересчитаются по новым правилам."
          busy={save.isPending}
          onClose={() => {
            setConfirming(false);
          }}
        >
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="secondary"
              disabled={save.isPending}
              onClick={() => {
                setConfirming(false);
              }}
            >
              Отмена
            </Button>
            <Button type="button" disabled={save.isPending} onClick={confirm}>
              Да, сохранить
            </Button>
          </div>
        </Modal>
      )}
      <PreviewCard rules={toRules(current)} />
      <OverrideCard />
    </div>
  );
}
