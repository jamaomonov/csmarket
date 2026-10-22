/**
 * The one status chip (admin UX audit §6): `<Status of="order" code="paid" />`. Words and tones
 * come from the dictionary; a code it does not know reads «другой статус» with the code small
 * beside it. `Reason` is the same for a reason line («скин продан»).
 */
import { type ReactNode } from "react";

import { StatusChip, type Tone } from "./StatusChip";

import {
  capital,
  type ReasonKind,
  reasonWord,
  type StatusKind,
  statusWord,
} from "@/lib/dictionary";

/** The raw code beside an unknown word: small, never the only text. */
function RawCode({ code }: { code: string }) {
  return (
    <>
      {" "}
      <span className="text-meta font-normal opacity-75">{code}</span>
    </>
  );
}

interface StatusProps {
  of: StatusKind;
  code: string;
  /** A second line under the chip (a hold's countdown). */
  sub?: ReactNode;
  /** Overrides the dictionary's tone (a sale with an open attention is red). */
  tone?: Tone | undefined;
  title?: string | undefined;
  testId?: string | undefined;
}

export function Status({ of, code, sub, tone, title, testId }: StatusProps) {
  const s = statusWord(of, code);
  return (
    <StatusChip tone={tone ?? s.word.tone} sub={sub} title={title} testId={testId}>
      {s.word.label}
      {s.unknown !== null && <RawCode code={s.unknown} />}
    </StatusChip>
  );
}

interface ReasonProps {
  of: ReasonKind;
  code: string;
  className?: string;
  /** A value standing alone in a cell starts with a capital («Лимит кассы»). */
  capitalise?: boolean;
}

export function Reason({ of, code, className, capitalise = false }: ReasonProps) {
  const r = reasonWord(of, code);
  return (
    <span className={className}>
      {capitalise ? capital(r.word) : r.word}
      {r.unknown !== null && <RawCode code={r.unknown} />}
    </span>
  );
}
