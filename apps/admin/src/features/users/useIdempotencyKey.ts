/**
 * One `Idempotency-Key` per confirmed submission, not per click.
 *
 * `keyFor(body)` returns the same key while the request body stays the same — a
 * double click or a retry after a lost response replays instead of writing
 * twice — and a fresh one once the body changes (the API answers 409 to an old
 * key on a new body). `reset()` after success, so the next deliberate action of
 * the same shape is a new one.
 */
import { useCallback, useRef } from "react";

import { newUuid } from "@/lib/uuid";

export interface IdempotencyKey {
  keyFor: (body: string) => string;
  reset: () => void;
}

export function useIdempotencyKey(prefix: string): IdempotencyKey {
  const ref = useRef<{ body: string; key: string } | null>(null);
  const keyFor = useCallback(
    (body: string): string => {
      if (ref.current?.body !== body) {
        ref.current = { body, key: `${prefix}-${newUuid()}` };
      }
      return ref.current.key;
    },
    [prefix],
  );
  const reset = useCallback(() => {
    ref.current = null;
  }, []);
  return { keyFor, reset };
}
