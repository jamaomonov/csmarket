"use client";

import { SessionApiError } from "@csmarket/api-client";
import { Button } from "@csmarket/ui";
import { ArrowLeftRight, CheckCircle2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type SyntheticEvent } from "react";

import { SettingsCard } from "./SettingsCard";

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
  bad: "text-danger",
  muted: "text-fg-muted",
};

export function TradeLinkForm({ initial, onChange }: TradeLinkFormProps) {
  const t = useTranslations("web.account.tradeLink");
  const p = useTranslations("web.account.profile");
  const [value, setValue] = useState(initial.trade_link ?? "");
  const [saved, setSaved] = useState(initial.trade_link !== null);
  const [savedValue, setSavedValue] = useState(initial.trade_link ?? "");
  // A saved link reads as text with «Изменить»; the form opens for a new one.
  const [editing, setEditing] = useState(initial.trade_link === null);
  const [state, setState] = useState<CheckState>({
    verdict: initial.verdict,
    reason: initial.reason,
  });
  const [busy, setBusy] = useState<"saving" | "checking" | null>(null);
  // A verdict just asked for is said in words; a saved working link shows only the tick.
  const [fresh, setFresh] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function check() {
    setBusy("checking");
    try {
      const out = await session.apiPost<TradeLinkOut>("/api/v1/me/trade-link/check", {});
      setState({ verdict: out.verdict, reason: out.reason });
    } catch {
      setState({ verdict: null, reason: "unavailable" });
    } finally {
      setFresh(true);
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
      setSavedValue(value.trim());
      setEditing(false);
    } catch (err) {
      setBusy(null);
      // The old verdict belongs to a link the visitor is replacing; next to this
      // error it would read as a verdict on the link just refused.
      setState({ verdict: null, reason: null });
      setError(errorKey(err instanceof SessionApiError ? err.code : undefined));
      return;
    }
    await check();
  }

  const message = verdictMessage(state);
  const ok = message?.tone === "ok";
  const status = (
    <>
      {error ? <p className="text-danger mt-3 text-sm">{t(`errors.${error}`)}</p> : null}
      {busy === "checking" ? <p className="text-fg-muted mt-3 text-sm">{t("checking")}</p> : null}
      {busy === null && message && (!ok || fresh || editing) ? (
        <p className={`mt-3 text-sm ${TONE[message.tone]}`}>{t(`status.${message.key}`)}</p>
      ) : null}
      {busy === null && saved && !error && !ok ? (
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
    </>
  );
  if (!editing) {
    return (
      <SettingsCard
        icon={ArrowLeftRight}
        title={
          <>
            {t("title")}
            {ok ? (
              <CheckCircle2
                className="text-success size-[18px]"
                aria-label={t("status.ok")}
                role="img"
              />
            ) : null}
          </>
        }
        hint={<span className="block truncate">{savedValue}</span>}
        aside={
          <Button
            variant="secondary"
            onClick={() => {
              setEditing(true);
            }}
          >
            {p("edit")}
          </Button>
        }
      >
        {status}
      </SettingsCard>
    );
  }
  return (
    <SettingsCard icon={ArrowLeftRight} title={t("title")} hint={t("hint")}>
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
            setError(null);
          }}
          placeholder="https://steamcommunity.com/tradeoffer/new/?partner=…&token=…"
          aria-label={t("title")}
          className="border-border bg-bg flex-1 rounded-md border px-3 py-2 text-sm"
          required
        />
        <Button type="submit" disabled={busy !== null}>
          {busy === "saving" ? t("saving") : t("save")}
        </Button>
        {saved ? (
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setValue(savedValue);
              setError(null);
              setEditing(false);
            }}
          >
            {p("cancel")}
          </Button>
        ) : null}
      </form>
      {status}
    </SettingsCard>
  );
}
