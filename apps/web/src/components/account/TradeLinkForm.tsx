"use client";

import { SessionApiError } from "@csmarket/api-client";
import { Button } from "@csmarket/ui";
import { useTranslations } from "next-intl";
import { useState, type SyntheticEvent } from "react";

import { session } from "@/lib/api";
import {
  errorKey,
  STEAM_TRADE_URL_PAGE,
  verdictMessage,
  type CheckState,
  type Tone,
} from "@/lib/trade-link";

interface TradeLinkState extends CheckState {
  trade_link: string | null;
}

interface TradeLinkOut extends TradeLinkState {
  checked_at: string | null;
}

interface TradeLinkFormProps {
  initial: TradeLinkState;
  onChange: () => void;
}

const TONE: Record<Tone, string> = {
  ok: "text-success",
  warn: "text-warning",
  bad: "text-danger",
  muted: "text-fg-muted",
};

export function TradeLinkForm({ initial, onChange }: TradeLinkFormProps) {
  const t = useTranslations("web.account.tradeLink");
  const [value, setValue] = useState(initial.trade_link ?? "");
  const [saved, setSaved] = useState(initial.trade_link !== null);
  const [state, setState] = useState<CheckState>({
    verdict: initial.verdict,
    reason: initial.reason,
  });
  const [busy, setBusy] = useState<"saving" | "checking" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function check() {
    setBusy("checking");
    try {
      const out = await session.apiPost<TradeLinkOut>("/api/v1/me/trade-link/check", {});
      setState({ verdict: out.verdict, reason: out.reason });
    } catch {
      setState({ verdict: null, reason: "unavailable" });
    } finally {
      setBusy(null);
      onChange();
    }
  }

  async function save(e: SyntheticEvent) {
    e.preventDefault();
    setError(null);
    setBusy("saving");
    try {
      const out = await session.apiPut<TradeLinkOut>(
        "/api/v1/me/trade-link",
        { url: value.trim() },
        { idempotencyKey: crypto.randomUUID() },
      );
      setState({ verdict: out.verdict, reason: out.reason });
      setSaved(true);
    } catch (err) {
      setBusy(null);
      setError(errorKey(err instanceof SessionApiError ? err.code : undefined));
      return;
    }
    await check();
  }

  const message = verdictMessage(state);
  return (
    <section className="border-border rounded-lg border p-5">
      <h2 className="text-lg font-bold">{t("title")}</h2>
      <p className="text-fg-muted mt-1 text-sm">{t("hint")}</p>
      <details className="mt-3 text-sm">
        <summary className="text-accent cursor-pointer font-semibold">{t("whereToFind")}</summary>
        <p className="text-fg-muted mt-2">{t("steps")}</p>
        <a
          href={STEAM_TRADE_URL_PAGE}
          target="_blank"
          rel="noreferrer"
          className="text-accent mt-2 inline-block underline"
        >
          {t("openSteam")}
        </a>
      </details>
      <form
        onSubmit={(e) => {
          void save(e);
        }}
        className="mt-4 flex flex-col gap-3 sm:flex-row"
      >
        <input
          type="url"
          inputMode="url"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
          }}
          placeholder="https://steamcommunity.com/tradeoffer/new/?partner=…&token=…"
          aria-label={t("title")}
          className="border-border bg-surface flex-1 rounded-md border px-3 py-2 text-sm"
          required
        />
        <Button type="submit" disabled={busy !== null}>
          {busy === "saving" ? t("saving") : t("save")}
        </Button>
      </form>
      {error ? <p className="text-danger mt-3 text-sm">{t(`errors.${error}`)}</p> : null}
      {busy === "checking" ? <p className="text-fg-muted mt-3 text-sm">{t("checking")}</p> : null}
      {busy === null && message ? (
        <p className={`mt-3 text-sm ${TONE[message.tone]}`}>{t(`status.${message.key}`)}</p>
      ) : null}
      {busy === null && saved && !error ? (
        <button
          type="button"
          onClick={() => {
            void check();
          }}
          className="text-accent mt-2 text-sm underline"
        >
          {t("check")}
        </button>
      ) : null}
    </section>
  );
}
