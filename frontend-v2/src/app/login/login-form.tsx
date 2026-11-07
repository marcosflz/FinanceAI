"use client";

import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowRight,
  Eye,
  EyeOff,
  Loader2,
  LockKeyhole,
  ShieldCheck,
} from "lucide-react";
import { ApiError, authApi } from "@/lib/api";
import { DEMO_MODE } from "@/lib/demo";
import { formatMoney, safeNextPath } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, Input, Label } from "@/components/ui/form";
import { ThemeToggle } from "@/components/shell/theme-toggle";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = safeNextPath(searchParams.get("next"));

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setError(null);
    setPending(true);

    try {
      await authApi.login({ email: email.trim(), password, remember });
      router.replace(next);
      router.refresh();
    } catch (loginError) {
      if (loginError instanceof ApiError && loginError.status === 429) {
        setError("Demasiados intentos. Espera un minuto antes de volver a probar.");
      } else if (loginError instanceof ApiError && loginError.status === 0) {
        setError("No se pudo conectar con el servidor. Revisa que el backend esté activo.");
      } else {
        setError("Email o contraseña incorrectos.");
      }
      setPending(false);
    }
  }

  function enterDemo() {
    document.cookie = `ft_session=demo; path=/; max-age=${60 * 60 * 8}; SameSite=Lax`;
    router.replace(next);
    router.refresh();
  }

  return (
    <div className="flex min-h-screen bg-background">
      <section className="relative hidden w-1/2 shrink-0 flex-col justify-between overflow-hidden border-r border-border bg-accent-soft px-10 py-8 text-accent-soft-foreground lg:flex xl:px-14">
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-lg bg-accent text-[12px] font-semibold text-accent-foreground">
            FT
          </span>
          <span>
            <span className="block text-[13px] font-semibold leading-4">Financial Tools</span>
            <span className="block text-[10px] leading-3 opacity-70">Panel personal</span>
          </span>
        </div>

        <div className="relative max-w-md">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] opacity-70">
            Octubre 2026 · resumen
          </p>
          <p className="num mt-3 text-[44px] font-semibold leading-none tracking-[-0.04em]">
            {formatMoney(1235.38, { signDisplay: "always" })}
          </p>
          <p className="mt-2 text-[13px] opacity-70">Flujo neto del mes</p>

          <div className="mt-8 grid grid-cols-3 gap-4 border-y border-accent/20 py-4">
            <div>
              <p className="text-[10px] uppercase tracking-[0.1em] opacity-60">Ingresos</p>
              <p className="num mt-1 text-[15px] font-medium">{formatMoney(3420, { compact: true })}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.1em] opacity-60">Gastos</p>
              <p className="num mt-1 text-[15px] font-medium">{formatMoney(2184.62, { compact: true })}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.1em] opacity-60">Ahorro</p>
              <p className="num mt-1 text-[15px] font-medium">36,1 %</p>
            </div>
          </div>

          <div className="mt-6 space-y-2.5">
            {[
              { name: "Mercadona", detail: "Alimentación · regla MCC", amount: -84.32 },
              { name: "Nómina — Acme Studio", detail: "Ingreso · broker", amount: 3200 },
              { name: "Transferencia a Revolut", detail: "Interna · auto-aprobada", amount: -500 },
            ].map((row) => (
              <div
                key={row.name}
                className="flex items-center justify-between gap-4 rounded-lg border border-accent/15 bg-card/40 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-[12px] font-medium">{row.name}</p>
                  <p className="truncate text-[10px] opacity-65">{row.detail}</p>
                </div>
                <p className="num shrink-0 text-[12px] font-medium">
                  {formatMoney(row.amount, { signDisplay: "always" })}
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between gap-4 text-[10px] opacity-60">
          <span className="inline-flex items-center gap-1.5">
            <ShieldCheck className="size-3" aria-hidden />
            Sesión HttpOnly · CSRF · Argon2id
          </span>
          <span className="num">v3 · F5</span>
        </div>

        <span
          aria-hidden
          className="pointer-events-none absolute -bottom-16 -right-10 select-none text-[260px] font-semibold leading-none tracking-[-0.08em] opacity-[0.045]"
        >
          FT
        </span>
      </section>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-14 items-center justify-between px-4 sm:px-8">
          <div className="flex items-center gap-2 lg:invisible">
            <span className="flex size-7 items-center justify-center rounded-lg bg-accent text-[11px] font-semibold text-accent-foreground">
              FT
            </span>
            <span className="text-[13px] font-semibold">Financial Tools</span>
          </div>
          <ThemeToggle />
        </div>

        <div className="flex flex-1 items-center justify-center px-4 pb-16 pt-6 sm:px-8">
          <div className="w-full max-w-sm">
            <div className="mb-7">
              <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                Acceso privado
              </p>
              <h1 className="mt-1.5 text-[26px] font-semibold leading-8 tracking-[-0.03em]">
                Entra en tu panel
              </h1>
              <p className="mt-2 text-[13px] leading-5 text-muted-foreground">
                Tus movimientos, cuentas e inversiones en un único sitio.
              </p>
            </div>

            <form onSubmit={onSubmit} className="space-y-4" noValidate>
              <Field label="Email" htmlFor="login-email">
                <Input
                  id="login-email"
                  name="email"
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  placeholder="tu@email.com"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? "login-error" : undefined}
                />
              </Field>

              <Field label="Contraseña" htmlFor="login-password">
                <div className="relative">
                  <Input
                    id="login-password"
                    name="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    placeholder="••••••••••••"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                    className="pr-10"
                    aria-invalid={Boolean(error)}
                    aria-describedby={error ? "login-error" : undefined}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((value) => !value)}
                    aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                    className="absolute inset-y-0 right-0 flex w-9 items-center justify-center text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {showPassword ? (
                      <EyeOff className="size-4" aria-hidden />
                    ) : (
                      <Eye className="size-4" aria-hidden />
                    )}
                  </button>
                </div>
              </Field>

              <div className="flex items-center gap-2">
                <Checkbox
                  id="remember"
                  checked={remember}
                  onChange={(event) => setRemember(event.target.checked)}
                />
                <Label htmlFor="remember" className="mb-0 cursor-pointer text-[12px] text-foreground">
                  Recordarme durante 7 días
                </Label>
              </div>

              {error ? (
                <p
                  id="login-error"
                  role="alert"
                  className="rounded-lg border border-negative/25 bg-negative-soft px-3 py-2 text-[12px] leading-4 text-negative"
                >
                  {error}
                </p>
              ) : null}

              <Button
                type="submit"
                variant="primary"
                className="h-10 w-full"
                disabled={pending || !email || !password}
              >
                {pending ? (
                  <>
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                    Comprobando…
                  </>
                ) : (
                  <>
                    Entrar
                    <ArrowRight className="size-3.5" aria-hidden />
                  </>
                )}
              </Button>
            </form>

            {DEMO_MODE ? (
              <div className="mt-6 rounded-xl border border-dashed border-border bg-card p-3.5">
                <p className="flex items-center gap-1.5 text-[11px] font-medium text-foreground">
                  <LockKeyhole className="size-3 text-warning" aria-hidden />
                  Modo demo activo
                </p>
                <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                  La autenticación real no está conectada. Entra con datos de ejemplo
                  para revisar las pantallas.
                </p>
                <Button className="mt-2.5 w-full" size="sm" onClick={enterDemo}>
                  Entrar en modo demo
                  <ArrowRight className="size-3" aria-hidden />
                </Button>
              </div>
            ) : null}

            <p className="mt-8 flex items-center justify-center gap-1.5 text-center text-[10px] text-muted-foreground">
              <ShieldCheck className="size-3" aria-hidden />
              La sesión se valida en el servidor. No se guardan contraseñas en el navegador.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
