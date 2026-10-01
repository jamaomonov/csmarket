/** App shell: topbar (admin name + sign-out) and outlet. The sidebar arrives with the first real pages. */
import { Button } from "@csmarket/ui";
import { NavLink, Outlet } from "react-router-dom";

import { useAuthStore } from "@/features/auth/authStore";

export function Layout() {
  const me = useAuthStore((s) => s.me);
  const signOut = useAuthStore((s) => s.signOut);
  return (
    <div className="min-h-screen">
      <header className="border-border h-(--topbar-height) flex items-center gap-4 border-b px-5">
        <NavLink to="/" className="font-mono text-sm font-bold uppercase tracking-widest">
          csmarket admin
        </NavLink>
        <div className="ml-auto flex items-center gap-3">
          <span className="text-fg-muted text-sm">{me?.display_name ?? "Администратор"}</span>
          <Button variant="ghost" size="sm" onClick={signOut}>
            Выйти
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-5 py-8">
        <Outlet />
      </main>
    </div>
  );
}
