/**
 * The one save bar of a settings page: pinned to the bottom of the screen across its full width,
 * shown only when something changed, with «Изменено: N полей», «Сбросить» and «Сохранить». A
 * spacer under the form keeps the last fields reachable above it.
 */
import { Button } from "@csmarket/ui";
import { type ReactNode } from "react";

const PLURAL = new Intl.PluralRules("ru");
const FIELDS: Record<string, string> = { one: "поле", few: "поля", many: "полей", other: "поля" };

/** «1 поле», «3 поля», «5 полей». */
export function fieldsWord(n: number): string {
  return `${String(n)} ${FIELDS[PLURAL.select(n)] ?? "полей"}`;
}

type Leaf = string | number | boolean | null;

function leaves(value: unknown, path: string, out: Map<string, Leaf>): Map<string, Leaf> {
  if (Array.isArray(value)) {
    value.forEach((v, i) => leaves(v, `${path}[${String(i)}]`, out));
  } else if (value !== null && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) leaves(v, path === "" ? k : `${path}.${k}`, out);
  } else if (value !== undefined) {
    out.set(path, value as Leaf); // JSON data: the rest are primitives
  }
  return out;
}

/** How many leaf values differ between two JSON-like documents (an added row counts each cell). */
export function countChanges(saved: unknown, draft: unknown): number {
  const a = leaves(saved, "", new Map());
  const b = leaves(draft, "", new Map());
  let n = 0;
  for (const k of new Set([...a.keys(), ...b.keys()])) {
    if (a.get(k) !== b.get(k)) n += 1;
  }
  return n;
}

interface SaveBarProps {
  /** Changed fields; 0 hides the bar. */
  changed: number;
  saving: boolean;
  onSave: () => void;
  onReset: () => void;
  /** An error or a validation note, shown in the bar above the buttons. */
  children?: ReactNode;
}

export function SaveBar({ changed, saving, onSave, onReset, children }: SaveBarProps) {
  if (changed === 0) return null;
  return (
    <>
      <div aria-hidden className="h-24" />
      <div
        role="region"
        aria-label="Несохранённые изменения"
        className="border-border bg-bg/95 fixed inset-x-0 bottom-0 z-30 border-t px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur md:px-6"
      >
        <div className="mx-auto flex max-w-[1600px] flex-col gap-2">
          {children}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-warning text-sm font-medium">
              Изменено: {fieldsWord(changed)}
            </span>
            <div className="ml-auto flex gap-2">
              <Button variant="secondary" disabled={saving} onClick={onReset}>
                Сбросить
              </Button>
              <Button disabled={saving} onClick={onSave}>
                Сохранить
              </Button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
