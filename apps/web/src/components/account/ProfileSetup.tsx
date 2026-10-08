import { Badge, cn } from "@csmarket/ui";
import { Check, ChevronRight, Gift } from "lucide-react";
import { useTranslations } from "next-intl";

export interface SetupStep {
  key: "steam" | "tradeLink" | "email";
  done: boolean;
  /** The row on the page that sets this step (`#…`), for a step not done yet. */
  href?: string;
}

interface ProfileSetupProps {
  steps: SetupStep[];
}

/** «Настройка профиля»: what is set and what is left, each open step a link to its row. */
export function ProfileSetup({ steps }: ProfileSetupProps) {
  const t = useTranslations("web.account.profile");
  const done = steps.filter((s) => s.done).length;
  const total = steps.length;
  return (
    <section className="bg-surface rounded-xl p-4 sm:p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[15px] font-semibold">{t("setupTitle")}</h2>
        <span className="num text-fg-muted text-sm">{t("setupProgress", { done, total })}</span>
      </div>
      <div
        role="progressbar"
        aria-label={t("setupTitle")}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        className="bg-surface-2 mt-3 h-1.5 overflow-hidden rounded-full"
      >
        <div
          className="bg-accent duration-(--duration-base) h-full rounded-full transition-[width]"
          style={{ width: `${String(Math.round((done / total) * 100))}%` }}
        />
      </div>
      <ul className="mt-4 flex flex-col gap-1">
        {steps.map((step) => {
          const label = t(`steps.${step.key}`);
          const mark = (
            <span
              className={cn(
                "grid size-6 shrink-0 place-items-center rounded-full",
                step.done
                  ? "bg-accent text-accent-fg"
                  : "border-border-strong border-2 border-dashed",
              )}
            >
              {step.done ? <Check className="size-3.5" strokeWidth={3} aria-hidden /> : null}
            </span>
          );
          return (
            <li key={step.key}>
              {step.done || !step.href ? (
                <span className="flex items-center gap-3 rounded-lg px-2 py-2 text-sm">
                  {mark}
                  <span className={cn("flex-1", step.done && "text-fg-muted")}>{label}</span>
                  <span className="sr-only">{step.done ? t("stepDone") : t("stepLeft")}</span>
                </span>
              ) : (
                <a
                  href={step.href}
                  className="hover:bg-surface-hover focus-visible:ring-accent flex items-center gap-3 rounded-lg px-2 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2"
                >
                  {mark}
                  <span className="flex-1">{label}</span>
                  <span className="sr-only">{t("stepLeft")}</span>
                  <ChevronRight className="text-fg-dim size-4" aria-hidden />
                </a>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The referral programme, not open yet: a teaser card. */
export function ReferralTeaser() {
  const t = useTranslations("web.account.profile");
  const soon = useTranslations("web.soon");
  return (
    <section className="bg-surface relative overflow-hidden rounded-xl p-4 sm:p-5">
      <div
        aria-hidden
        className="pointer-events-none absolute -right-10 -top-10 size-36 rounded-full"
        style={{ background: "radial-gradient(closest-side, rgb(75 243 100 / 0.14), transparent)" }}
      />
      <div className="relative flex items-start gap-3">
        <span className="bg-accent-subtle text-accent grid size-10 shrink-0 place-items-center rounded-lg">
          <Gift className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-[15px] font-semibold">{t("referralTitle")}</h3>
            <Badge tone="neutral">{soon("badge")}</Badge>
          </div>
          <p className="text-fg-muted mt-1 text-sm">{t("referralHint")}</p>
        </div>
      </div>
    </section>
  );
}
