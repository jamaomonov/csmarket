/** Catalogue counts, last job outcomes and the CBU rate. */
import { useQuery } from "@tanstack/react-query";

import { type CatalogStatus, getStatus, type JobOut } from "./api";
import { formatNumber, formatRate, formatWhen } from "./format";

import { ApiError, formatApiError } from "@/lib/api";

const ERROR_LABELS: Record<string, string> = {
  thin_snapshot: "Waxpeer прислал неполный список — цены остались прежними",
};

interface JobLineProps {
  name: string;
  job: JobOut | null;
  okText: string;
  failText: string;
}

function JobLine({ name, job, okText, failText }: JobLineProps) {
  if (!job) return <li className="text-fg-muted">{name}: ещё не запускалось</li>;
  if (job.ok) return <li>{`${okText} ${formatWhen(job.finished_at)}`}</li>;
  const reason = job.error
    ? (ERROR_LABELS[job.error] ?? `ошибка: ${job.error}`)
    : "ошибка: неизвестна";
  return (
    <li>
      <span className="text-danger">{failText}</span>{" "}
      <span className="text-fg-muted">{formatWhen(job.finished_at)}</span>
      <div className="text-fg-muted text-sm">{reason}</div>
    </li>
  );
}

function StatusBody({ s }: { s: CatalogStatus }) {
  return (
    <div className="space-y-4">
      <ul className="space-y-1">
        <li>Скинов в каталоге: {formatNumber(s.items_total)}</li>
        <li>В продаже: {formatNumber(s.items_active)}</li>
        <li>Скрыто: {formatNumber(s.items_hidden)}</li>
        {s.prices_updated_at && <li>Цены обновлены: {formatWhen(s.prices_updated_at)}</li>}
      </ul>
      <ul className="space-y-1">
        <JobLine
          name="Каталог"
          job={s.import_job}
          okText="Каталог обновлён"
          failText="Каталог не обновился"
        />
        <JobLine
          name="Цены"
          job={s.price_sync_job}
          okText="Цены обновлены"
          failText="Цены не обновились"
        />
      </ul>
      <p>
        {s.fx
          ? `Курс ЦБ: ${formatRate(s.fx.usd_uzs)} сум за $ · ${formatWhen(s.fx.fetched_at)}`
          : "Курса нет — цены показываются в долларах"}
      </p>
      {(!s.sync_enabled || !s.waxpeer_key_set) && (
        <p className="text-fg-muted text-sm">Обновление цен выключено на этом сервере</p>
      )}
    </div>
  );
}

export function StatusCard() {
  const q = useQuery({ queryKey: ["catalogue", "status"], queryFn: getStatus });
  return (
    <section className="border-border bg-surface rounded-lg border p-5">
      <h2 className="mb-3 text-lg font-semibold">Состояние</h2>
      {q.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {q.isError && (
        <p role="alert" className="text-danger">
          {q.error instanceof ApiError ? formatApiError(q.error) : "Не удалось загрузить"}
        </p>
      )}
      {q.data && <StatusBody s={q.data} />}
    </section>
  );
}
