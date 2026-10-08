"use client";

import { SessionApiError } from "@csmarket/api-client";
import { Button, Input } from "@csmarket/ui";
import { CheckCircle2, Mail, Pencil, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState, type SyntheticEvent } from "react";

import { Notice, SettingsCard } from "./SettingsCard";

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

/** «Email» on the profile: the address and whether it is confirmed, the form on demand. */
export function EmailForm({ email, verified, sentAt, onChange }: EmailFormProps) {
  const t = useTranslations("web.account.email");
  const p = useTranslations("web.account.profile");
  const generic = useTranslations("web.account.tradeLink.errors");
  const [value, setValue] = useState(email ?? "");
  const [busy, setBusy] = useState(false);
  // The address reads as text (or «Добавить» when there is none); the form opens on demand.
  const [editing, setEditing] = useState(false);
  const [shown, setShown] = useState(email);
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
      setShown(next);
      setEditing(false);
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

  const unverified = shown !== null && !verified;
  const done = shown !== null && verified;
  const notes = (
    <>
      {unverified && !editing ? (
        <Notice tone="warn">
          <p>{t("unverified", { email: shown })}</p>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="mt-2"
            disabled={busy || cooling}
            onClick={() => {
              void resend();
            }}
          >
            {t("resend")}
          </Button>
        </Notice>
      ) : null}
      {outcome === "saved" ? (
        <Notice tone="ok" role="status">
          {t("saved")}
        </Notice>
      ) : null}
      {outcome === "sent" ? (
        <Notice tone="ok" role="status">
          {t("sent")}
        </Notice>
      ) : null}
      {outcome === "wait" ? (
        <Notice tone="muted" role="status">
          {t("resendSoon")}
        </Notice>
      ) : null}
      {outcome === "invalid" ? (
        <Notice tone="bad" role="alert">
          {t("invalid")}
        </Notice>
      ) : null}
      {outcome === "failed" ? (
        <Notice tone="bad" role="alert">
          {generic("generic")}
        </Notice>
      ) : null}
    </>
  );
  const title = (
    <>
      {t("title")}
      {done ? (
        <CheckCircle2 className="text-success size-4" aria-label={t("verified")} role="img" />
      ) : null}
    </>
  );
  if (!editing) {
    return (
      <SettingsCard
        icon={Mail}
        done={done}
        title={title}
        hint={shown === null ? t("hint") : <span className="block truncate">{shown}</span>}
        aside={
          <Button
            variant="secondary"
            size="sm"
            className="max-sm:size-9 max-sm:px-0"
            onClick={() => {
              setValue(shown ?? "");
              setOutcome(null);
              setEditing(true);
            }}
          >
            {shown === null ? (
              <Plus className="size-4" aria-hidden />
            ) : (
              <Pencil className="size-3.5" aria-hidden />
            )}
            <span className="max-sm:sr-only">{shown === null ? p("add") : p("edit")}</span>
          </Button>
        }
      >
        {notes}
      </SettingsCard>
    );
  }
  return (
    <SettingsCard icon={Mail} title={title} hint={t("hint")}>
      <form
        onSubmit={(e) => {
          void save(e);
        }}
        className="mt-3 flex flex-col gap-2 sm:flex-row"
      >
        <Input
          type="email"
          inputMode="email"
          autoComplete="email"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setOutcome(null);
          }}
          placeholder="name@example.com"
          aria-label={t("title")}
          className="min-w-0 flex-1"
          // Opened by the visitor's own click on «Добавить» / «Изменить»: typing starts at once.
          autoFocus
        />
        <div className="flex gap-2">
          <Button type="submit" disabled={busy} className="flex-1 sm:flex-none">
            {t("save")}
          </Button>
          <Button
            type="button"
            variant="secondary"
            className="flex-1 sm:flex-none"
            onClick={() => {
              setValue(shown ?? "");
              setOutcome(null);
              setEditing(false);
            }}
          >
            {p("cancel")}
          </Button>
        </div>
      </form>
      {notes}
    </SettingsCard>
  );
}
