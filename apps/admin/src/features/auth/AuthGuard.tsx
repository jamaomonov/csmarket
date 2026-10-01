/** Route gate: boots the session once, then admits only a signed-in admin. */
import { useEffect } from "react";
import { Navigate, Outlet } from "react-router-dom";

import { useAuthStore } from "./authStore";
import { Forbidden } from "./Forbidden";

export function AuthGuard() {
  const status = useAuthStore((s) => s.status);
  const bootstrap = useAuthStore((s) => s.bootstrap);
  useEffect(() => {
    if (status === "loading") void bootstrap();
  }, [status, bootstrap]);

  if (status === "loading") return <p className="text-fg-muted p-8">Загрузка…</p>;
  if (status === "anonymous") return <Navigate to="/login" replace />;
  if (status === "forbidden" || status === "suspended") {
    return <Forbidden suspended={status === "suspended"} />;
  }
  return <Outlet />;
}
