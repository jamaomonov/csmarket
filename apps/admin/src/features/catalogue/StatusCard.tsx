/**
 * «Состояние» of the catalogue as four tiles like the dashboard: skins on sale, the last
 * catalogue import, the last price sync (red when it failed, with the last good time) and the
 * CBU rate.
 */
import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";

import { type CatalogStatus, getStatus, type JobOut } from "./api";
import { formatNumber, formatWhen } from "./format";

import { Section } from "@/components/Section";
import { Reason } from "@/components/Status";
import { Tile } from "@/features/dashboard/Tile";
import { ApiError, formatApiError } from "@/lib/api";
import { formatRate } from "@/lib/format";

const SMALL = "text-fg-muted text-sm font-normal";

interface JobTileProps {
  title: string;
  job: JobOut | null;
  okText: string;
  failText: string;
  children?: ReactNode;
}

/** A job's last outcome: the word large, when small; a failure red with its reason. */
function JobTile({ title, job, okText, failText, children }: JobTileProps) {
  const failed = job !== null && !job.ok;
  return (
    <Tile title={title} alert={failed}>
      {job === null ? (
        <span className="text-fg-muted">ещё не запускалось</span>
      ) : job.ok ? (
        <>
          <span>{okText}</span>
          <span className={SMALL}>{formatWhen(job.finished_at)}</span>
        </>
      ) : (
        <>
          <span className="text-danger">{failText}</span>
          <span className={SMALL}>
            {formatWhen(job.finished_at)} ·{" "}
            {job.error ? <Reason of="catalogueJob" code={job.error} /> : "причина неизвестна"}
          </span>
        </>
      )}
      {children}
    </Tile>
  );
}

function StatusBody({ s }: { s: CatalogStatus }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile title="Скины в продаже">
          <span>{formatNumber(s.items_active)}</span>
          <span className={SMALL}>
            из {formatNumber(s.items_total)} · скрыто {formatNumber(s.items_hidden)}
          </span>
        </Tile>
        <JobTile title="Каталог" job={s.import_job} okText="Обновлён" failText="Не обновился" />
        <JobTile
          title="Цены"
          job={s.price_sync_job}
          okText="Обновлены"
          failText="Цены не обновились"
        >
          {s.prices_updated_at && !(s.price_sync_job?.ok ?? false) && (
            <span className={SMALL}>
              <span>Цены обновлены</span> {formatWhen(s.prices_updated_at)}
            </span>
          )}
        </JobTile>
        <Tile title="Курс ЦБ">
          {s.fx ? (
            <>
              <span>{formatRate(s.fx.usd_uzs)}</span>
              <span className={SMALL}>{formatWhen(s.fx.fetched_at)}</span>
            </>
          ) : (
            <span className={SMALL}>Курса нет — цены показываются в долларах</span>
          )}
        </Tile>
      </div>
      {(!s.sync_enabled || !s.waxpeer_key_set) && (
        <p className="text-fg-muted mt-3 text-sm">Обновление цен выключено на этом сервере</p>
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
