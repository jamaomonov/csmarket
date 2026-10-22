/** «Состояние» of the catalogue: counts, the last job outcomes and the CBU rate (one Section). */
import { useQuery } from "@tanstack/react-query";

import { type CatalogStatus, getStatus, type JobOut } from "./api";
import { formatNumber, formatWhen } from "./format";

import { Row, Section } from "@/components/Section";
import { Reason } from "@/components/Status";
import { ApiError, formatApiError } from "@/lib/api";
import { formatRate } from "@/lib/format";

interface JobRowProps {
  label: string;
  job: JobOut | null;
  okText: string;
  failText: string;
}

function JobRow({ label, job, okText, failText }: JobRowProps) {
  return (
    <Row label={label}>
      {job === null ? (
        <span className="text-fg-muted">ещё не запускалось</span>
      ) : job.ok ? (
        `${okText} ${formatWhen(job.finished_at)}`
      ) : (
        <>
          <span className="text-danger">{failText}</span>{" "}
          <span className="text-fg-muted">{formatWhen(job.finished_at)}</span>
          <div className="text-fg-muted">
            {job.error ? (
              <Reason of="catalogueJob" code={job.error} capitalise />
            ) : (
              "Причина неизвестна"
            )}
          </div>
        </>
      )}
    </Row>
  );
}

function StatusBody({ s }: { s: CatalogStatus }) {
  return (
    <>
      <dl>
        <Row label="Скинов в каталоге">{formatNumber(s.items_total)}</Row>
        <Row label="В продаже">{formatNumber(s.items_active)}</Row>
        <Row label="Скрыто">{formatNumber(s.items_hidden)}</Row>
        {s.prices_updated_at && <Row label="Цены обновлены">{formatWhen(s.prices_updated_at)}</Row>}
        <JobRow
          label="Каталог"
          job={s.import_job}
          okText="Обновлён"
          failText="Каталог не обновился"
        />
        <JobRow
          label="Цены"
          job={s.price_sync_job}
          okText="Обновлены"
          failText="Цены не обновились"
        />
        <Row label="Курс ЦБ">
          {s.fx ? (
            <>
              {formatRate(s.fx.usd_uzs)}
              <span className="text-fg-muted"> · {formatWhen(s.fx.fetched_at)}</span>
            </>
          ) : (
            "Курса нет — цены показываются в долларах"
          )}
        </Row>
      </dl>
      {(!s.sync_enabled || !s.waxpeer_key_set) && (
        <p className="text-fg-muted mt-2 text-sm">Обновление цен выключено на этом сервере</p>
      )}
    </>
  );
}

export function StatusCard() {
  const q = useQuery({ queryKey: ["catalogue", "status"], queryFn: getStatus });
  return (
    <Section title="Состояние">
      {q.isPending && <p className="text-fg-muted">Загрузка…</p>}
      {q.isError && (
        <p role="alert" className="text-danger">
          {q.error instanceof ApiError ? formatApiError(q.error) : "Не удалось загрузить"}
        </p>
      )}
      {q.data && <StatusBody s={q.data} />}
    </Section>
  );
}
