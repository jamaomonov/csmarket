import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";

/** The balance's method id in the payment picker (not a kassa). */
export const WALLET = "wallet";

/**
 * Which payment method to show selected, given whether the balance can pay.
 *
 * A buyer whose balance covers the price starts on «Баланс» — no redirect, no card. If the
 * price then grows past the balance, an automatic choice goes back to the default kassa.
 * A method the buyer picked by hand is never changed.
 */
export function preferBalance(
  current: string,
  o: { ready: boolean; picked: boolean; fallback: string },
): string {
  if (o.picked) return current;
  if (o.ready) return WALLET;
  return current === WALLET ? o.fallback : current;
}

/**
 * Applies `preferBalance` to a method state whenever the balance's readiness changes.
 * Returns the function a method tile calls on a tap, which marks the choice as the
 * buyer's own.
 */
export function usePreferBalance(
  ready: boolean,
  setMethod: Dispatch<SetStateAction<string>>,
  fallback: string,
): () => void {
  const picked = useRef(false);
  useEffect(() => {
    setMethod((current) => preferBalance(current, { ready, picked: picked.current, fallback }));
  }, [ready, fallback, setMethod]);
  return useCallback(() => {
    picked.current = true;
  }, []);
}
