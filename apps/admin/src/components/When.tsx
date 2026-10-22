/**
 * A list row's time in the one format (`listTime`): «5 мин назад» or «21.10 09:05», with the full
 * `DD.MM.YYYY HH:MM` in the tooltip and in `dateTime`.
 */
import { formatDateTime, listTime } from "@/lib/format";

interface WhenProps {
  iso: string;
  className?: string;
}

export function When({ iso, className }: WhenProps) {
  return (
    <time
      dateTime={iso}
      title={formatDateTime(iso)}
      className={`whitespace-nowrap ${className ?? ""}`}
    >
      {listTime(iso)}
    </time>
  );
}
