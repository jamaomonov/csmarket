"use client";

import { Button } from "@csmarket/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

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
  const [copyFailed, setCopyFailed] = useState(false);
  const [notAllowed, setNotAllowed] = useState(false);
  const tokenRef = useRef<HTMLElement>(null);

  // gcTime 0 and a reset on «Готово» / unmount: the token must not outlive the screen in the
  // mutation cache (its `data`); it is copied to local state below and read only from there.
  const issue = useMutation({
    mutationFn: () => issueApiKey(mintApiKeyKey()),
    gcTime: 0,
    onMutate: () => {
      setNotAllowed(false);
    },
    onSuccess: async (issued) => {
      setToken(issued.token);
      setConfirm(null);
      setNotAllowed(false);
      await qc.invalidateQueries({ queryKey: API_KEY_KEY });
    },
    onError: async (err) => {
      setConfirm(null);
      setNotAllowed(err instanceof ApiKeyNotAllowedError);
      await qc.invalidateQueries({ queryKey: API_KEY_KEY });
    },
  });
  const revoke = useMutation({
    mutationFn: () => revokeApiKey(mintApiKeyKey()),
    onSuccess: async () => {
      setConfirm(null);
      await qc.invalidateQueries({ queryKey: API_KEY_KEY });
    },
    onError: async () => {
      setConfirm(null);
      // Revoked elsewhere (404 `api_key_missing`) or any failure: show what is really there.
      await qc.invalidateQueries({ queryKey: API_KEY_KEY });
    },
  });
  const resetIssue = issue.reset;
  useEffect(() => resetIssue, [resetIssue]);
  // A different key (issued, revoked elsewhere) than the one that was refused: ask again.
  const keyId = key.data?.id ?? null;
  useEffect(() => {
    setNotAllowed(false);
  }, [keyId]);

  const when = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" });
  const busy = issue.isPending || revoke.isPending;
  const failed = (issue.isError && !notAllowed) || revoke.isError;

  function selectToken(): boolean {
    const node = tokenRef.current;
    if (!node) return false;
    const range = document.createRange();
    range.selectNodeContents(node);
    const sel = window.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(range);
    return true;
  }

  async function copy(value: string) {
    setCopyFailed(false);
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      return;
    } catch {
      // No clipboard API (plain http, old browser): select the text and try the old way.
    }
    let done = false;
    try {
      // eslint-disable-next-line @typescript-eslint/no-deprecated -- the only copy path without the Clipboard API
      done = selectToken() && document.execCommand("copy");
    } catch {
      done = false;
    }
    setCopied(done);
    setCopyFailed(!done);
  }

  function finish() {
    setToken(null);
    setCopied(false);
    setCopyFailed(false);
    issue.reset();
  }

  let body;
  let hint: string = notAllowed ? t("needTopup") : t("hint");
  if (token !== null) {
    body = (
      <>
        <Notice tone="warn" role="status">
          {t("saveIt")}
        </Notice>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
          <code
            ref={tokenRef}
            aria-label={t("tokenTitle")}
            className="num bg-bg/40 border-border min-w-0 flex-1 break-all rounded-lg border px-3 py-2 text-[13px]"
          >
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
        <span role="status" className="sr-only">
          {copied ? t("copied") : ""}
        </span>
        {copyFailed ? (
          <Notice tone="warn" role="alert">
            {t("copyManually")}
          </Notice>
        ) : null}
        <Button className="mt-3" onClick={finish}>
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
  const yesRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (confirm !== null) yesRef.current?.focus();
  }, [confirm]);
  return (
    <>
      <ul className="text-fg-muted mt-3 flex flex-col gap-1 text-sm">
        <li>{t("created", { date: when.format(new Date(apiKey.created_at)) })}</li>
        <li>
          {apiKey.last_used_at
            ? t("lastUsed", { date: when.format(new Date(apiKey.last_used_at)) })
            : t("neverUsed")}
        </li>
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
              ref={yesRef}
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
