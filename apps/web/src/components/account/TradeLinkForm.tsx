"use client";

import { SessionApiError } from "@csmarket/api-client";
import { Button, Input } from "@csmarket/ui";
import { ArrowLeftRight, CheckCircle2, CircleHelp, Pencil, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type SyntheticEvent } from "react";

import { Notice, SettingsCard } from "./SettingsCard";

import { session } from "@/lib/api";
import {
  errorKey,
  shortTradeLink,
  STEAM_TRADE_URL_PAGE,
  verdictMessage,
  type CheckState,
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
  /** Without a saved link, show a row with «Добавить» instead of the open form (the profile). */
  collapseEmpty?: boolean;
}

interface SavedLinkProps {
  url: string;
}

/** The saved link, token hidden; on phones without the host. */
function SavedLink({ url }: SavedLinkProps) {
  const short = shortTradeLink(url);
  return (
    <span className="block truncate font-mono text-[13px]">
      {short === null ? (
        url
      ) : (
        <>
          <span className="max-sm:hidden">{short.host}/</span>…{short.query}
        </>
      )}
    </span>
  );
}

/** «Ссылка на обмен»: the saved link (token hidden) with «Изменить», or the form with «Где взять?». */
export function TradeLinkForm({ initial, onChange, collapseEmpty = false }: TradeLinkFormProps) {
  const t = useTranslations("web.account.tradeLink");
  const p = useTranslations("web.account.profile");
  const [value, setValue] = useState(initial.trade_link ?? "");
  const [saved, setSaved] = useState(initial.trade_link !== null);
  const [savedValue, setSavedValue] = useState(initial.trade_link ?? "");
  // A saved link reads as text with «Изменить»; the form opens for a new one.
  const [editing, setEditing] = useState(initial.trade_link === null && !collapseEmpty);
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
  const canRecheck = busy === null && saved && !error && !ok;
  const recheck = (
    <button
      type="button"
      onClick={() => {
        void check();
      }}
      className="text-accent mt-1.5 block font-semibold underline-offset-2 hover:underline"
    >
      {t("check")}
    </button>
  );
  const showMessage = busy === null && message !== null && (!ok || fresh || editing);
  const status = (
    <>
      {error ? (
        <Notice tone="bad" role="alert">
          {t(`errors.${error}`)}
        </Notice>
      ) : null}
      {busy === "checking" ? (
        <Notice tone="muted" role="status">
          {t("checking")}
        </Notice>
      ) : null}
      {showMessage ? (
        <Notice tone={message.tone} role="status">
          {t(`status.${message.key}`)}
          {canRecheck ? recheck : null}
        </Notice>
      ) : null}
      {!showMessage && canRecheck ? <div className="text-sm">{recheck}</div> : null}
    </>
  );
  const title = (
    <>
      {t("title")}
      {ok && !editing ? (
        <CheckCircle2 className="text-success size-4" aria-label={t("status.ok")} role="img" />
      ) : null}
    </>
  );
  if (!editing) {
    const empty = !saved;
    return (
      <SettingsCard
        icon={ArrowLeftRight}
        done={ok}
        title={title}
        hint={empty ? t("hint") : <SavedLink url={savedValue} />}
        aside={
          <Button
            variant={empty ? "primary" : "secondary"}
            size="sm"
            className="max-sm:size-9 max-sm:px-0"
            onClick={() => {
              setEditing(true);
            }}
          >
            {empty ? (
              <Plus className="size-4" aria-hidden />
            ) : (
              <Pencil className="size-3.5" aria-hidden />
            )}
            <span className="max-sm:sr-only">{empty ? p("add") : p("edit")}</span>
          </Button>
        }
      >
        {status}
      </SettingsCard>
    );
  }
  return (
    <SettingsCard icon={ArrowLeftRight} title={title} hint={t("hint")}>
      <form
        onSubmit={(e) => {
          void save(e);
        }}
        className="mt-3 flex flex-col gap-2 sm:flex-row"
      >
        <Input
          type="url"
          inputMode="url"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setError(null);
          }}
          placeholder="https://steamcommunity.com/tradeoffer/new/?partner=…&token=…"
          aria-label={t("title")}
          className="min-w-0 flex-1"
          required
        />
        <div className="flex gap-2">
          <Button type="submit" disabled={busy !== null} className="flex-1 sm:flex-none">
            {busy === "saving" ? t("saving") : t("save")}
          </Button>
          {saved || collapseEmpty ? (
            <Button
              type="button"
              variant="secondary"
              className="flex-1 sm:flex-none"
              onClick={() => {
                setValue(savedValue);
                setError(null);
                setEditing(false);
              }}
            >
              {p("cancel")}
            </Button>
          ) : null}
        </div>
      </form>
      <details className="group mt-3 text-sm">
        <summary className="text-fg-muted hover:text-fg inline-flex cursor-pointer list-none items-center gap-1.5 font-medium [&::-webkit-details-marker]:hidden">
          <CircleHelp className="text-accent size-4" aria-hidden />
          {t("whereToFind")}
        </summary>
        <div className="border-border bg-bg/40 mt-2 rounded-lg border px-3 py-2.5">
          <p className="text-fg-muted">{t("steps")}</p>
          <a
            href={STEAM_TRADE_URL_PAGE}
            target="_blank"
            rel="noreferrer"
            className="text-accent mt-2 inline-block font-semibold underline-offset-2 hover:underline"
          >
            {t("openSteam")}
          </a>
        </div>
      </details>
      {status}
    </SettingsCard>
  );
}
