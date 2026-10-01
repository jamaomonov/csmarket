import { loginHref } from "./authStore";

export function LoginPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <p className="font-mono text-sm font-bold uppercase tracking-widest">csmarket admin</p>
      <a href={loginHref()} className="bg-accent text-accent-fg rounded-md px-5 py-3 font-semibold">
        Войти через Steam
      </a>
      <p className="text-fg-muted max-w-sm text-sm">
        Доступ есть у аккаунтов Steam с ролью администратора.
      </p>
    </div>
  );
}
