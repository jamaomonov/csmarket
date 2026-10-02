"use client";

import { SessionApiError } from "@csmarket/api-client";
import { Button } from "@csmarket/ui";
import { useTranslations } from "next-intl";
import { useEffect, useState, type SyntheticEvent } from "react";

import { session } from "@/lib/api";

/** A confirmation letter may be asked for again a minute after the last one. */
const COOLDOWN_MS = 60_000;

interface EmailFormProps {
  email: string | null;
  /** The saved address is confirmed: order letters go to it. */
  verified: boolean;
  /** When the latest confirmation letter was queued (ISO), if any. */
  sentAt: string | null;
  onChange: () => void;
}

type Outcome = "saved" | "sent" | "invalid" | "failed" | "wait" | null;

/** Milliseconds until a resend is allowed again, from the last send. */
function waitLeft(lastSent: number | null): number {
  return lastSent === null ? 0 : Math.max(0, lastSent + COOLDOWN_MS - Date.now());
}

export function EmailForm({ email, verified, sentAt, onChange }: EmailFormProps) {
  const t = useTranslations("web.account.email");
  const generic = useTranslations("web.account.tradeLink.errors");
  const [value, setValue] = useState(email ?? "");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [lastSent, setLastSent] = useState<number | null>(sentAt ? Date.parse(sentAt) : null);
  const [cooling, setCooling] = useState(() => waitLeft(lastSent) > 0);

  useEffect(() => {
    const left = waitLeft(lastSent);
    setCooling(left > 0);
    if (left === 0) return;
    const timer = setTimeout(() => {
      setCooling(false);
    }, left);
    return () => {
      clearTimeout(timer);
    };
  }, [lastSent]);

  async function save(e: SyntheticEvent) {
    e.preventDefault();
    setBusy(true);
    setOutcome(null);
    const next = value.trim() || null;
    try {
      // The fields of `MeOut` this form reads (the API answers the whole profile).
      const me = await session.apiPatch<{ email_verification_sent_at?: string | null }>(
        "/api/v1/me",
        { email: next },
        { idempotencyKey: crypto.randomUUID() },
      );
      const changed = next !== null && next !== email;
      // Within a minute of the last letter the API saves the address but sends nothing.
      const deferred = changed && me.email_verification_sent_at === null;
      setOutcome(deferred ? "wait" : changed ? "sent" : "saved");
      if (changed) setLastSent(Date.now());
      onChange();
    } catch (err) {
      setOutcome(err instanceof SessionApiError && err.status === 422 ? "invalid" : "failed");
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setBusy(true);
    setOutcome(null);
    try {
      await session.apiPost(
        "/api/v1/me/email/verification",
        {},
        { idempotencyKey: crypto.randomUUID() },
      );
      setOutcome("sent");
      setLastSent(Date.now());
    } catch (err) {
      if (err instanceof SessionApiError && err.status === 429) {
        setOutcome("wait");
      } else if (err instanceof SessionApiError && err.code === "email_already_verified") {
        onChange();
      } else {
        setOutcome("failed");
      }
    } finally {
      setBusy(false);
    }
  }

  const unverified = email !== null && !verified;
  return (
    <section className="border-border rounded-lg border p-5">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-bold">{t("title")}</h2>
        {email !== null && verified ? (
          <span className="bg-success text-success-fg rounded px-2 py-0.5 text-xs">
            {t("verified")}
          </span>
        ) : null}
      </div>
      <p className="text-fg-muted mt-1 text-sm">{t("hint")}</p>
      <form
        onSubmit={(e) => {
          void save(e);
        }}
        className="mt-4 flex flex-col gap-3 sm:flex-row"
      >
        <input
          type="email"
          inputMode="email"
          autoComplete="email"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setOutcome(null);
          }}
          aria-label={t("title")}
          className="border-border bg-surface flex-1 rounded-md border px-3 py-2 text-sm"
        />
        <Button type="submit" disabled={busy}>
          {t("save")}
        </Button>
      </form>
      {unverified ? (
        <div className="mt-3 flex flex-col items-start gap-2 text-sm">
          <p>{t("unverified", { email })}</p>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={busy || cooling}
            onClick={() => {
              void resend();
            }}
          >
            {t("resend")}
          </Button>
        </div>
      ) : null}
      {outcome === "saved" ? <p className="text-success mt-3 text-sm">{t("saved")}</p> : null}
      {outcome === "sent" ? <p className="text-success mt-3 text-sm">{t("sent")}</p> : null}
      {outcome === "wait" ? <p className="text-fg-muted mt-3 text-sm">{t("resendSoon")}</p> : null}
      {outcome === "invalid" ? <p className="text-danger mt-3 text-sm">{t("invalid")}</p> : null}
      {outcome === "failed" ? (
        <p className="text-danger mt-3 text-sm">{generic("generic")}</p>
      ) : null}
    </section>
  );
}
