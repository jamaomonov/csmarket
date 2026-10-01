"use client";

import { SessionApiError } from "@csmarket/api-client";
import { Button } from "@csmarket/ui";
import { useTranslations } from "next-intl";
import { useState, type SyntheticEvent } from "react";

import { session } from "@/lib/api";

interface EmailFormProps {
  email: string | null;
  onChange: () => void;
}

type Outcome = "saved" | "invalid" | "failed" | null;

export function EmailForm({ email, onChange }: EmailFormProps) {
  const t = useTranslations("web.account.email");
  const generic = useTranslations("web.account.tradeLink.errors");
  const [value, setValue] = useState(email ?? "");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);

  async function save(e: SyntheticEvent) {
    e.preventDefault();
    setBusy(true);
    setOutcome(null);
    try {
      await session.apiPatch(
        "/api/v1/me",
        { email: value.trim() || null },
        { idempotencyKey: crypto.randomUUID() },
      );
      setOutcome("saved");
      onChange();
    } catch (err) {
      setOutcome(err instanceof SessionApiError && err.status === 422 ? "invalid" : "failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="border-border rounded-lg border p-5">
      <h2 className="text-lg font-bold">{t("title")}</h2>
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
          }}
          aria-label={t("title")}
          className="border-border bg-surface flex-1 rounded-md border px-3 py-2 text-sm"
        />
        <Button type="submit" disabled={busy}>
          {t("save")}
        </Button>
      </form>
      {outcome === "saved" ? <p className="text-success mt-3 text-sm">{t("saved")}</p> : null}
      {outcome === "invalid" ? <p className="text-danger mt-3 text-sm">{t("invalid")}</p> : null}
      {outcome === "failed" ? (
        <p className="text-danger mt-3 text-sm">{generic("generic")}</p>
      ) : null}
    </section>
  );
}
