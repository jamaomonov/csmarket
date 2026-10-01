/** Filters kept in the URL query string, so a page can be linked to and survives a reload. */
import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

export interface UrlParams {
  /** The value of `key`, or `""` when absent. */
  get: (key: string) => string;
  /** Set `key` (an empty value removes it), replacing the history entry. */
  set: (key: string, value: string) => void;
}

export function useUrlParams(): UrlParams {
  const [params, setParams] = useSearchParams();
  const get = useCallback((key: string): string => params.get(key) ?? "", [params]);
  const set = useCallback(
    (key: string, value: string): void => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value === "") next.delete(key);
          else next.set(key, value);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  return { get, set };
}
