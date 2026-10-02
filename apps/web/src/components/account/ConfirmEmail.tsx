"use client";

import { SessionApiError } from "@csmarket/api-client";
import { Button, buttonVariants } from "@csmarket/ui";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { Link } from "@/i18n/navigation";
import { session } from "@/lib/api";
import { ACCOUNT } from "@/lib/paths";

type State = "checking" | "done" | "expired" | "invalid" | "failed";

/** What a refusal means to the reader. */
function refused(err: unknown): State {
  if (!(err instanceof SessionApiError)) return "failed";
  if (err.code === "email_token_expired") return "expired";
  if (err.code === "email_token_invalid" || err.code === "email_token_stale") return "invalid";
  return "failed";
}

/**
 * Confirms the email a letter's link names. The token is read from the address bar once,
 * then removed from it (it never renders and is not left in history); works signed out.
 */
export function ConfirmEmail() {
  const t = useTranslations("web.account.email.confirm");
  const token = useRef<string | null | undefined>(undefined);
  const [state, setState] = useState<State>("checking");

  const confirm = useCallback(async () => {
    if (!token.current) {
      setState("invalid");
      return;
    }
    setState("checking");
    try {
      await session.apiPost("/api/v1/email/confirm", { token: token.current });
      setState("done");
    } catch (err) {
      setState(refused(err));
    }
  }, []);

  useEffect(() => {
    if (token.current !== undefined) return; // StrictMode runs effects twice: post once
    token.current = new URLSearchParams(window.location.search).get("token");
    window.history.replaceState(window.history.state, "", window.location.pathname);
    void confirm();
  }, [confirm]);

  return (
    <div className="flex flex-col items-start gap-4" data-state={state}>
      <p role="status">{t(state)}</p>
      {state === "failed" ? (
        <Button
          type="button"
          onClick={() => {
            void confirm();
          }}
        >
          {t("retry")}
        </Button>
      ) : null}
      {state !== "checking" && state !== "failed" ? (
        <Link href={ACCOUNT} className={buttonVariants({ variant: "secondary" })}>
          {t("toProfile")}
        </Link>
      ) : null}
    </div>
  );
}
