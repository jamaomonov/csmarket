/** App shell: topbar + outlet. The sidebar arrives with the first real pages (M1). */
import { NavLink, Outlet } from "react-router-dom";

export function Layout() {
  return (
    <div className="min-h-screen">
      <header className="border-border h-(--topbar-height) flex items-center gap-4 border-b px-5">
        <NavLink to="/" className="font-mono text-sm font-bold uppercase tracking-widest">
          csmarket admin
        </NavLink>
      </header>
      <main className="mx-auto max-w-6xl px-5 py-8">
        <Outlet />
      </main>
    </div>
  );
}
