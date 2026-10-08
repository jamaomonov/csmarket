"use client";

import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Notice, SettingsCard } from "./SettingsCard";

import {
  API_KEY_KEY,
  ApiKeyNotAllowedError,
  getApiKey,
  issueApiKey,
  mintApiKeyKey,
  revokeApiKey,
  type ApiKeyOut,
} from "@/lib/api-key";

/** Plan C publishes the documentation; until then there is no link to show. */
const API_DOCS_URL: string | null = null;

interface ApiKeyCardProps {
  locale: string;
}

type Confirm = "reissue" | "revoke" | null;

/**
 * «API-ключ» on the profile: issue a key, see it once, reissue or revoke it. The token lives
 * in component state only — never stored — and is dropped on «Готово».
 */
export function ApiKeyCard({ locale }: ApiKeyCardProps) {
  const t = useTranslations("web.apiKey");
  const qc = useQueryClient();
  const key = useQuery({ queryKey: API_KEY_KEY, queryFn: getApiKey });
  const [token, setToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [notAllowed, setNotAllowed] = useState(false);

  const issue = useMutation({
    mutationFn: () => issueApiKey(mintApiKeyKey()),
    onSuccess: async (issued) => {
      setToken(issued.token);
      setConfirm(null);
      setNotAllowed(false);
      await qc.invalidateQueries({ queryKey: API_KEY_KEY });
    },
    onError: (err) => {
      setConfirm(null);
      setNotAllowed(err instanceof ApiKeyNotAllowedError);
    },
  });
  const revoke = useMutation({
    mutationFn: () => revokeApiKey(mintApiKeyKey()),
    onSuccess: async () => {
      setConfirm(null);
      await qc.invalidateQueries({ queryKey: API_KEY_KEY });
    },
    onError: () => {
      setConfirm(null);
    },
  });

  const when = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" });
  const busy = issue.isPending || revoke.isPending;
  const failed = (issue.isError && !notAllowed) || revoke.isError;

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  let body;
  let hint: string = t("hint");
  if (token !== null) {
    body = (
      <>
        <Notice tone="warn" role="status">
          {t("saveIt")}
        </Notice>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
          <code className="num bg-bg/40 border-border min-w-0 flex-1 break-all rounded-lg border px-3 py-2 text-[13px]">
            {token}
          </code>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void copy(token);
            }}
          >
            {copied ? (
              <Check className="size-4" aria-hidden />
            ) : (
              <Copy className="size-4" aria-hidden />
            )}
            {copied ? t("copied") : t("copy")}
          </Button>
        </div>
        <Button
          className="mt-3"
          onClick={() => {
            setToken(null);
            setCopied(false);
          }}
        >
          {t("done")}
        </Button>
      </>
    );
  } else if (key.isPending) {
    body = <div aria-busy className="bg-surface-2 mt-3 h-12 animate-pulse rounded-lg" />;
  } else if (key.isError) {
    hint = t("loadFailed");
  } else if (key.data === null) {
    hint = notAllowed ? t("needTopup") : t("none");
    body = (
      <Button
        className="mt-3"
        disabled={busy || notAllowed}
        onClick={() => {
          issue.mutate();
        }}
      >
        {issue.isPending ? t("issuing") : t("issue")}
      </Button>
    );
  } else {
    body = (
      <LiveKey
        apiKey={key.data}
        when={when}
        confirm={confirm}
        busy={busy}
        onConfirm={setConfirm}
        onReissue={() => {
          issue.mutate();
        }}
        onRevoke={() => {
          revoke.mutate();
        }}
      />
    );
  }
  return (
    <SettingsCard icon={KeyRound} title={t("title")} hint={hint} done={key.data != null}>
      {body}
      {failed ? (
        <Notice tone="bad" role="alert">
          {t("failed")}
        </Notice>
      ) : null}
      {API_DOCS_URL !== null && token === null ? (
        <a href={API_DOCS_URL} className="text-accent mt-3 inline-block text-sm font-semibold">
          {t("docs")}
        </a>
      ) : null}
    </SettingsCard>
  );
}

interface LiveKeyProps {
  apiKey: ApiKeyOut;
  when: Intl.DateTimeFormat;
  confirm: Confirm;
  busy: boolean;
  onConfirm: (c: Confirm) => void;
  onReissue: () => void;
  onRevoke: () => void;
}

function LiveKey({ apiKey, when, confirm, busy, onConfirm, onReissue, onRevoke }: LiveKeyProps) {
  const t = useTranslations("web.apiKey");
  return (
    <>
      <ul className="text-fg-muted mt-3 flex flex-col gap-1 text-sm">
        <li>{t("created", { date: when.format(new Date(apiKey.created_at)) })}</li>
        <li>
          {apiKey.last_used_at
            ? t("lastUsed", { date: when.format(new Date(apiKey.last_used_at)) })
            : t("neverUsed")}
        </li>
        <li>{t("tariff", { name: t(`tariffs.${apiKey.pricing_profile}`) })}</li>
      </ul>
      {confirm === null ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() => {
              onConfirm("reissue");
            }}
          >
            {t("reissue")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="hover:text-danger"
            disabled={busy}
            onClick={() => {
              onConfirm("revoke");
            }}
          >
            {t("revoke")}
          </Button>
        </div>
      ) : (
        <Notice tone="warn" role="status">
          <p>{confirm === "reissue" ? t("reissueSure") : t("revokeSure")}</p>
          <div className="mt-2 flex gap-2">
            <Button
              size="sm"
              disabled={busy}
              onClick={confirm === "reissue" ? onReissue : onRevoke}
            >
              {confirm === "reissue" ? t("reissueYes") : t("revokeYes")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                onConfirm(null);
              }}
            >
              {t("cancel")}
            </Button>
          </div>
        </Notice>
      )}
    </>
  );
}
