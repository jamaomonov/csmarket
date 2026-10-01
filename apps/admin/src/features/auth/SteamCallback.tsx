/** Steam's return page: hands the `openid.*` assertion to the API and opens the session. */
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { loginHref, useAuthStore } from "./authStore";

export function SteamCallback() {
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const completeSteam = useAuthStore((s) => s.completeSteam);
  const [failed, setFailed] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    // The assertion is single-use: run once even under StrictMode's double effect.
    if (started.current) return;
    started.current = true;
    const params: Record<string, string> = {};
    search.forEach((value, key) => {
      if (key.startsWith("openid.")) params[key] = value;
    });
    // The signed assertion must not linger in the address bar or history.
    window.history.replaceState(null, "", window.location.pathname);
    completeSteam(params)
      .then(() => {
        void navigate("/", { replace: true });
      })
      .catch(() => {
        setFailed(true);
      });
  }, [search, completeSteam, navigate]);

  if (!failed) return <p className="text-fg-muted p-8">Входим через Steam…</p>;
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
      <p className="font-semibold">Не получилось войти через Steam.</p>
      <a href={loginHref()} className="text-accent underline">
        Попробовать ещё раз
      </a>
      <Link to="/login" className="text-fg-muted text-sm">
        Назад
      </Link>
    </div>
  );
}
