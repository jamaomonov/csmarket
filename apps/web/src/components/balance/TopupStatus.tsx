"use client";

import { SessionApiError } from "@csmarket/api-client";
import { DEFAULT_LOCALE, isLocale } from "@csmarket/i18n";
import { Button, buttonVariants } from "@csmarket/ui";
import { assertNever, formatUzs } from "@csmarket/utils";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { ENTRIES_KEY } from "./EntriesList";

import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { BALANCE_KEY, devPay, getTopup, type Topup } from "@/lib/balance";
import {
  AUTO_OPEN_BUDGET_MS,
  markOpened,
  searchWithoutGo,
  shouldAutoOpen,
} from "@/lib/kassa-redirect";

/** Poll cadence while the customer pays: every 3 s… */
const POLL_MS = 3_000;
/** …for at most 40 polls (2 min) while the tab is visible; then «Обновить». */
const MAX_POLLS = 40;

/**
 * What the customer sees. A pending top-up with nothing to pay is being checked while a
 * kassa holds it (it may still settle), else it reads as expired.
 */
type View = "pending" | "checking" | "succeeded" | "expired" | "reversed";

function viewOf(topup: Topup): View {
  if (topup.status === "pending" && topup.intent_url === null) {
    return topup.awaiting_kassa ? "checking" : "expired";
  }
  return topup.status;
}

/** Views that can still change: the page keeps polling. */
const isOpen = (view: View): boolean => view === "pending" || view === "checking";

/** The kassa page to send the customer to, or `null` (nothing payable, or the dev kassa). */
function kassaUrl(topup: Topup): string | null {
  return viewOf(topup) === "pending" && topup.provider !== "mock" ? topup.intent_url : null;
}

const isNotFound = (err: unknown): boolean => err instanceof SessionApiError && err.status === 404;

interface TopupStatusProps {
  locale: string;
  number: string;
}

/**
 * A top-up's page: waits for the payment (polling), confirms it, or says it is over.
 * With `?go=1` it opens the kassa once, so on a phone the tab left behind the bank app
 * is this page.
 */
export function TopupStatus({ locale, number }: TopupStatusProps) {
  const t = useTranslations("web.balance");
  const nav = useTranslations("web.nav");
  const authT = useTranslations("web.auth");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const apiLocale = isLocale(locale) ? locale : DEFAULT_LOCALE;
  const qc = useQueryClient();

  // Answers seen since the poll budget last started; «Обновить» starts it over.
  const [polls, setPolls] = useState({ stamp: "", count: 0 });
  const topup = useQuery({
    queryKey: ["wallet", "topup", number, apiLocale],
    queryFn: () => getTopup(number, apiLocale),
    enabled: signedIn,
    retry: (failures, err) => !isNotFound(err) && failures < 2,
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && !isOpen(viewOf(data))) return false;
      if (!data && isNotFound(query.state.error)) return false;
      return polls.count > MAX_POLLS ? false : POLL_MS;
    },
  });
  const stamp = `${topup.dataUpdatedAt.toString()}:${topup.errorUpdatedAt.toString()}`;
  if (stamp !== polls.stamp && (topup.dataUpdatedAt > 0 || topup.errorUpdatedAt > 0)) {
    setPolls({ stamp, count: polls.count + 1 });
  }

  useKassaAutoOpen(number, topup.data);

  const shown = topup.data ? viewOf(topup.data) : null;
  useEffect(() => {
    if (shown !== "succeeded") return;
    void qc.invalidateQueries({ queryKey: BALANCE_KEY });
    void qc.invalidateQueries({ queryKey: ENTRIES_KEY });
  }, [shown, qc]);

  const pay = useMutation({
    mutationFn: () => devPay(number),
    onSettled: () => topup.refetch(),
  });

  if (status === "loading") return <Skeleton />;
  if (status === "suspended") return <p className="text-danger">{authT("suspended")}</p>;
  if (!signedIn) {
    return (
      <div className="flex flex-col items-start gap-4">
        <p className="text-fg-muted">{t("signedOut")}</p>
        <a href={signInHref(locale)} className={buttonVariants({ size: "lg" })}>
          {nav("signIn")}
        </a>
      </div>
    );
  }
  if (!topup.data) {
    if (topup.isError) {
      return isNotFound(topup.error) ? (
        <Outcome view="notFound" title={t("topup.notFound")} />
      ) : (
        <FetchFailed
          onRetry={() => {
            void topup.refetch();
          }}
        />
      );
    }
    return <Skeleton />;
  }

  const data = topup.data;
  const amount = formatUzs(locale, data.amount_uzs);
  const current = viewOf(data);
  switch (current) {
    case "succeeded":
      return <Outcome view="succeeded" title={t("topup.done", { amount })} />;
    case "expired":
      return <Outcome view="expired" title={t("topup.expired")} />;
    case "reversed":
      return <Outcome view="reversed" title={t("topup.reversed")} />;
    case "checking":
      return (
        <Waiting
          view="checking"
          amount={amount}
          kassa={null}
          stopped={polls.count > MAX_POLLS}
          onRefresh={() => {
            setPolls({ stamp, count: 0 });
            void topup.refetch();
          }}
          devPay={null}
        />
      );
    case "pending":
      return (
        <Waiting
          view="pending"
          amount={amount}
          kassa={kassaUrl(data)}
          stopped={polls.count > MAX_POLLS}
          onRefresh={() => {
            setPolls({ stamp, count: 0 });
            void topup.refetch();
          }}
          devPay={
            data.provider === "mock"
              ? {
                  busy: pay.isPending,
                  failed: pay.isError,
                  run: () => {
                    pay.mutate();
                  },
                }
              : null
          }
        />
      );
    default:
      return assertNever(current);
  }
}

/**
 * Open the kassa once when the page arrived with `?go=1`, and strip the flag.
 *
 * The first answer spends the flag whatever it says: a paid or expired top-up opens
 * nothing, and neither does one that answered after `AUTO_OPEN_BUDGET_MS`.
 */
function useKassaAutoOpen(number: string, topup: Topup | undefined): void {
  const latch = useRef(false);
  const arrivedAt = useRef<number | null>(null);
  useEffect(() => {
    arrivedAt.current = Date.now();
  }, []);
  useEffect(() => {
    if (!topup || latch.current) return;
    latch.current = true;
    const { pathname, search, hash } = window.location;
    const open = shouldAutoOpen(number, search);
    if (open) markOpened(number);
    const rest = searchWithoutGo(search);
    if (rest !== search) window.history.replaceState(null, "", `${pathname}${rest}${hash}`);
    const url = kassaUrl(topup);
    const late = Date.now() - (arrivedAt.current ?? Date.now()) > AUTO_OPEN_BUDGET_MS;
    if (open && url !== null && !late) window.location.assign(url);
  }, [number, topup]);
}

function Skeleton() {
  return <div aria-busy className="bg-surface h-40 animate-pulse rounded-lg" />;
}

interface FetchFailedProps {
  onRetry: () => void;
}

function FetchFailed({ onRetry }: FetchFailedProps) {
  const common = useTranslations("common");
  return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-fg-muted">{common("errors.generic")}</p>
      <Button variant="secondary" onClick={onRetry}>
        {common("actions.retry")}
      </Button>
    </div>
  );
}

interface OutcomeProps {
  view: Exclude<View, "pending" | "checking"> | "notFound";
  title: string;
}

/** A top-up that is over (or not there): what happened and the way back to the balance. */
function Outcome({ view, title }: OutcomeProps) {
  const t = useTranslations("web.balance.topup");
  return (
    <Panel view={view}>
      <h1 className="text-2xl font-bold">{title}</h1>
      <Link href="/account/balance" className={buttonVariants({ variant: "secondary" })}>
        {t("toBalance")}
      </Link>
    </Panel>
  );
}

interface WaitingProps {
  /** `checking`: a kassa holds the top-up past its time; nothing to pay, keep waiting. */
  view: "pending" | "checking";
  amount: string;
  /** The kassa's page; `null` for the dev kassa. */
  kassa: string | null;
  /** The poll budget ran out: offer «Обновить». */
  stopped: boolean;
  onRefresh: () => void;
  devPay: { busy: boolean; failed: boolean; run: () => void } | null;
}

function Waiting({ view, amount, kassa, stopped, onRefresh, devPay: test }: WaitingProps) {
  const t = useTranslations("web.balance.topup");
  const common = useTranslations("common");
  return (
    <Panel view={view}>
      <div>
        <h1 className="text-2xl font-bold">{t(view === "checking" ? "checking" : "waiting")}</h1>
        <p className="mt-2 text-3xl font-bold tabular-nums">{amount}</p>
        {view === "checking" ? <p className="text-fg-muted mt-2">{t("checkingNote")}</p> : null}
      </div>
      {test ? (
        <Button size="lg" disabled={test.busy} onClick={test.run}>
          {t("payTest")}
        </Button>
      ) : kassa !== null ? (
        <a href={kassa} className={buttonVariants({ size: "lg" })}>
          {t("pay")}
        </a>
      ) : null}
      {test?.failed ? (
        <p role="alert" className="text-danger text-sm">
          {common("errors.generic")}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-4 text-sm">
        {stopped ? (
          <button type="button" onClick={onRefresh} className="text-accent font-semibold">
            {t("refresh")}
          </button>
        ) : null}
        <Link href="/account/balance" className="text-fg-muted hover:text-fg">
          {t("toBalance")}
        </Link>
      </div>
    </Panel>
  );
}

interface PanelProps {
  view: View | "notFound";
  children: ReactNode;
}

function Panel({ view, children }: PanelProps) {
  return (
    <section
      data-testid="topup-status"
      data-state={view}
      aria-live="polite"
      className="flex flex-col items-start gap-5"
    >
      {children}
    </section>
  );
}
