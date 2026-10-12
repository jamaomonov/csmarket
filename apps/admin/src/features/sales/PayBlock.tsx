/**
 * The first screen of a payout on a phone: who is paying it («Беру в работу»), the amount to
 * send with «Скопировать сумму», the card (brand, masked; «Показать номер» / «Скопировать
 * номер» go through the audited reveal, which also claims the request) and the sale number.
 * The number lives only in this component's state and hides after a minute or a decision.
 * When the clipboard refuses (iPhone Safari after a network wait), the number stays on screen
 * in a read-only field to tap, select and copy by hand.
 */
import { Button } from "@csmarket/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { copyLater, copyText } from "./clipboard";
import { PAYOUTS_KEY, payoutKey } from "./keys";
import { CARD_BRANDS, groupDigits, payoutErrorText } from "./labels";
import { claimPayout, type PayoutDetail as Detail, releasePayout, revealCard } from "./payoutsApi";

import { Money } from "@/components/Money";
import { useAuthStore } from "@/features/auth/authStore";
import { useIdempotencyKey } from "@/features/users/useIdempotencyKey";
import { formatDateTime } from "@/lib/format";

const REVEAL_MS = 60_000;

function CopyButton({ text, label }: { text: string; label: string }) {
  const [state, setState] = useState<"idle" | "ok" | "failed">("idle");
  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={() => {
        void copyText(text).then((ok) => {
          setState(ok ? "ok" : "failed");
        });
      }}
    >
      {state === "ok" ? "Скопировано" : state === "failed" ? "Не скопировалось" : label}
    </Button>
  );
}

function ClaimBar({ detail }: { detail: Detail }) {
  const qc = useQueryClient();
  const meId = useAuthStore((s) => s.me?.id ?? null);
  const id = detail.request.id;
  const claimKey = useIdempotencyKey("admin-payout-claim");
  const releaseKey = useIdempotencyKey("admin-payout-release");
  const done = (next: Detail) => {
    qc.setQueryData(payoutKey(id), next);
    void qc.invalidateQueries({ queryKey: PAYOUTS_KEY });
  };
  const claim = useMutation({
    mutationFn: (takeover: boolean) =>
      claimPayout(id, takeover, claimKey.keyFor(JSON.stringify({ id, takeover }))),
    onSuccess: (next) => {
      claimKey.reset();
      done(next);
    },
  });
  const release = useMutation({
    mutationFn: () => releasePayout(id, releaseKey.keyFor(id)),
    onSuccess: (next) => {
      releaseKey.reset();
      done(next);
    },
  });
  if (!detail.can_decide) return null;
  const by = detail.request.claimed_by ?? null;
  const until = detail.request.claimed_until ?? null;
  const mine = by !== null && by.id === meId;
  const error = claim.error ?? release.error;
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="claim-bar">
      {by === null ? (
        <Button
          disabled={claim.isPending}
          onClick={() => {
            claim.mutate(false);
          }}
        >
          Беру в работу
        </Button>
      ) : mine ? (
        <>
          <span className="text-success text-sm font-medium">
            Вы платите{until ? ` до ${formatDateTime(until).slice(-5)}` : ""}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={release.isPending}
            onClick={() => {
              release.mutate();
            }}
          >
            Отпустить
          </Button>
        </>
      ) : (
        <>
          <span role="status" className="text-danger text-sm font-semibold">
            Платит {by.display_name ?? "другой администратор"}
            {until ? ` до ${formatDateTime(until).slice(-5)}` : ""} — не платите второй раз
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={claim.isPending}
            onClick={() => {
              claim.mutate(true);
            }}
          >
            Забрать себе
          </Button>
        </>
      )}
      {error ? (
        <p role="alert" className="text-danger w-full text-sm">
          {payoutErrorText(error)}
        </p>
      ) : null}
    </div>
  );
}

function CardNumber({ detail, onRevealed }: { detail: Detail; onRevealed: () => void }) {
  const [number, setNumber] = useState<string | null>(null);
  const [copy, setCopy] = useState<"idle" | "ok" | "failed">("idle");
  const [error, setError] = useState<unknown>(null);
  const id = detail.request.id;
  // Gone when the request is decided, and after a minute either way.
  useEffect(() => {
    setNumber(null);
    setCopy("idle");
  }, [detail.request.status, detail.can_decide]);
  useEffect(() => {
    if (number === null) return;
    const t = setTimeout(() => {
      setNumber(null);
      setCopy("idle");
    }, REVEAL_MS);
    return () => {
      clearTimeout(t);
    };
  }, [number]);
  const reveal = (purpose: "show" | "copy"): Promise<string> => {
    setError(null);
    const fetched = revealCard(id, purpose).then((r) => {
      setNumber(r.number);
      onRevealed();
      return r.number;
    });
    fetched.catch((e: unknown) => {
      setError(e);
    });
    return fetched;
  };
  if (!detail.can_decide) return null;
  return (
    <div className="space-y-2">
      {number !== null ? (
        <input
          readOnly
          aria-label="Номер карты"
          value={groupDigits(number)}
          onFocus={(e) => {
            e.currentTarget.select();
          }}
          className="border-border bg-bg w-full rounded-md border px-3 py-2 font-mono text-lg tracking-wider"
        />
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          onClick={() => {
            void reveal("show");
          }}
        >
          Показать номер
        </Button>
        <Button
          onClick={() => {
            // Started inside the tap: Safari keeps the right to write the clipboard.
            if (number !== null) {
              void copyText(number).then((ok) => {
                setCopy(ok ? "ok" : "failed");
              });
              return;
            }
            void copyLater(reveal("copy")).then((ok) => {
              setCopy(ok ? "ok" : "failed");
            });
          }}
        >
          Скопировать номер
        </Button>
      </div>
      {copy === "ok" ? <p className="text-success text-sm">Номер скопирован.</p> : null}
      {copy === "failed" && number !== null ? (
        <p className="text-fg-muted text-sm">
          Не скопировалось автоматически: нажмите на номер, выделите и скопируйте.
        </p>
      ) : null}
      {error !== null ? (
        <p role="alert" className="text-danger text-sm">
          {payoutErrorText(error)}
        </p>
      ) : null}
    </div>
  );
}

export function PayBlock({ detail, onChanged }: { detail: Detail; onChanged: () => void }) {
  const r = detail.request;
  return (
    <section
      aria-label="Оплата"
      className="border-border bg-surface space-y-4 rounded-lg border p-4"
      data-testid="pay-block"
    >
      <ClaimBar detail={detail} />
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-fg-muted text-sm">К выплате</p>
          <Money uzs={r.amount_uzs} className="text-2xl font-bold" />
        </div>
        <CopyButton text={r.amount_uzs} label="Скопировать сумму" />
      </div>
      <div>
        <p className="text-fg-muted text-sm">Карта</p>
        <p className="font-mono text-lg">
          <span className="font-sans font-semibold">{CARD_BRANDS[r.card_type]}</span>{" "}
          {r.card_masked}
        </p>
      </div>
      <CardNumber key={r.id} detail={detail} onRevealed={onChanged} />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-fg-muted">Продажа</span>
        <span className="font-mono">{r.sale_number}</span>
        <CopyButton text={r.sale_number} label="Скопировать" />
      </div>
    </section>
  );
}
