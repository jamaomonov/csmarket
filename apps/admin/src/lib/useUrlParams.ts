/** Filters kept in the URL query string, so a page can be linked to and survives a reload. */
import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

export interface UrlParams {
  /** The value of `key`, or `""` when absent. */
  get: (key: string) => string;
  /** Set `key` (an empty value removes it), replacing the history entry. */
  set: (key: string, value: string) => void;
  /** Set several keys in one history entry (an empty value removes its key). */
  setAll: (values: Record<string, string>) => void;
}

export function useUrlParams(): UrlParams {
  const [params, setParams] = useSearchParams();
  const get = useCallback((key: string): string => params.get(key) ?? "", [params]);
  const setAll = useCallback(
    (values: Record<string, string>): void => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(values)) {
            if (value === "") next.delete(key);
            else next.set(key, value);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  const set = useCallback(
    (key: string, value: string): void => {
      setAll({ [key]: value });
    },
    [setAll],
  );
  return { get, set, setAll };
}
