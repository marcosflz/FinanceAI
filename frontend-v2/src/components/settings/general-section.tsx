"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Check, KeyRound, Monitor, Moon, Save, ShieldCheck, Sun } from "lucide-react";
import { ApiError, authApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DEMO_MODE } from "@/lib/demo";
import { useTheme, type Theme } from "@/lib/theme";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Badge } from "@/components/ui/badge";
import { cn, formatDateTime } from "@/lib/utils";
import type { User } from "@/lib/types";

const themeOptions: Array<{ value: Theme; label: string; icon: typeof Sun }> = [
  { value: "light", label: "Claro", icon: Sun },
  { value: "dark", label: "Oscuro", icon: Moon },
  { value: "system", label: "Sistema", icon: Monitor },
];

export function GeneralSection() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const { toast } = useToast();
  const confirm = useConfirm();
  const fallbackName = user?.email?.split("@")[0] ?? "";
  const [name, setName] = useState(user?.name ?? fallbackName);
  const [email, setEmail] = useState(user?.email ?? "");
  const [emailPassword, setEmailPassword] = useState("");
  const [profilePending, setProfilePending] = useState(false);
  const [locale, setLocale] = useState("es-ES");
  const [currency, setCurrency] = useState("EUR");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordPending, setPasswordPending] = useState(false);
  const [sessionsPending, setSessionsPending] = useState(false);

  const emailChanged =
    email.trim().toLowerCase() !== (user?.email ?? "").trim().toLowerCase();
  const nameChanged = name.trim() !== (user?.name ?? fallbackName).trim();
  const profileDirty = emailChanged || nameChanged;

  function resetProfile() {
    setName(user?.name ?? fallbackName);
    setEmail(user?.email ?? "");
    setEmailPassword("");
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profileDirty) {
      toast({
        title: "Sin cambios",
        description: "Modifica tu nombre o email antes de guardar.",
      });
      return;
    }

    const nextName = name.trim();
    const nextEmail = email.trim().toLowerCase();
    setProfilePending(true);
    try {
      const updated: User = DEMO_MODE
        ? {
            ...(user as User),
            name: nextName || null,
            email: nextEmail,
          }
        : await authApi.updateProfile({
            name: nextName || null,
            email: nextEmail,
            ...(emailChanged ? { current_password: emailPassword } : {}),
          });
      queryClient.setQueryData(["auth", "me"], updated);
      setName(updated.name ?? updated.email.split("@")[0]);
      setEmail(updated.email);
      setEmailPassword("");
      toast({
        title: "Perfil actualizado",
        description: emailChanged
          ? "Usa el nuevo email la próxima vez que inicies sesión."
          : "Tus datos de perfil se han guardado.",
        variant: "success",
      });
    } catch (error) {
      toast({
        title: "No se pudo guardar el perfil",
        description:
          error instanceof ApiError
            ? error.message
            : "Revisa los datos y que el backend esté disponible.",
        variant: "error",
      });
    } finally {
      setProfilePending(false);
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Leemos del DOM y no solo del estado: los gestores de contraseñas pueden
    // autocompletar sin disparar onChange y dejar el estado vacío.
    const formData = new FormData(event.currentTarget);
    const currentPassword = String(formData.get("current_password") ?? password);
    const nextPassword = String(formData.get("new_password") ?? newPassword);

    setPasswordError(null);
    if (!currentPassword || !nextPassword) {
      const message = "Rellena la contraseña actual y la nueva contraseña.";
      setPasswordError(message);
      toast({ title: "Faltan datos", description: message, variant: "error" });
      return;
    }
    if (nextPassword.length < 12) {
      const message = `La nueva contraseña debe tener al menos 12 caracteres (${nextPassword.length}/12).`;
      setPasswordError(message);
      toast({
        title: "Contraseña demasiado corta",
        description: message,
        variant: "error",
      });
      return;
    }

    setPasswordPending(true);
    try {
      if (DEMO_MODE) await new Promise((resolve) => setTimeout(resolve, 450));
      else await authApi.changePassword(currentPassword, nextPassword);
      setPassword("");
      setNewPassword("");
      setPasswordError(null);
      toast({
        title: "Contraseña actualizada",
        description: DEMO_MODE
          ? "Modo demo: no se ha llamado al backend."
          : "La sesión actual sigue activa. El resto de sesiones se pueden cerrar aparte.",
        variant: "success",
      });
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Revisa la contraseña actual y que el backend esté disponible.";
      setPasswordError(message);
      toast({
        title: "No se pudo cambiar la contraseña",
        description: message,
        variant: "error",
      });
    } finally {
      setPasswordPending(false);
    }
  }

  async function closeAllSessions() {
    const ok = await confirm({
      title: "¿Cerrar todas las sesiones?",
      description:
        "Se cerrarán todas las sesiones, incluida esta. Tendrás que volver a iniciar sesión.",
      confirmLabel: "Cerrar sesiones",
      tone: "danger",
    });
    if (!ok) return;
    setSessionsPending(true);
    try {
      if (!DEMO_MODE) await authApi.logoutAll();
      queryClient.clear();
      router.replace("/login");
      router.refresh();
    } catch (error) {
      toast({
        title: "No se pudieron cerrar las sesiones",
        description:
          error instanceof ApiError
            ? error.message
            : "Comprueba que el backend esté disponible.",
        variant: "error",
      });
      setSessionsPending(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="py-3">
          <div>
            <CardTitle>Perfil</CardTitle>
            <CardDescription>Identidad, idioma y moneda de presentación</CardDescription>
          </div>
          <Badge variant="accent">Admin</Badge>
        </CardHeader>
        <CardContent className="pt-1">
          <form onSubmit={saveProfile}>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Nombre" htmlFor="settings-name">
                <Input
                  id="settings-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  autoComplete="name"
                  maxLength={120}
                />
              </Field>
              <Field
                label="Email"
                htmlFor="settings-email"
                hint="Es tu usuario de acceso. Cambiarlo requiere la contraseña actual."
              >
                <Input
                  id="settings-email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  maxLength={255}
                />
              </Field>
              {emailChanged ? (
                <div className="sm:col-span-2">
                  <Field
                    label="Contraseña actual"
                    htmlFor="settings-email-password"
                    hint="Necesaria para confirmar el cambio de email."
                  >
                    <Input
                      id="settings-email-password"
                      type="password"
                      value={emailPassword}
                      onChange={(event) => setEmailPassword(event.target.value)}
                      autoComplete="current-password"
                    />
                  </Field>
                </div>
              ) : null}
              <Field label="Idioma" htmlFor="settings-locale">
                <Select
                  id="settings-locale"
                  value={locale}
                  onChange={(event) => setLocale(event.target.value)}
                >
                  <option value="es-ES">Español (España)</option>
                  <option value="en-GB">English (UK)</option>
                </Select>
              </Field>
              <Field label="Moneda" htmlFor="settings-currency">
                <Select
                  id="settings-currency"
                  value={currency}
                  onChange={(event) => setCurrency(event.target.value)}
                >
                  <option value="EUR">Euro (EUR)</option>
                  <option value="USD">Dólar (USD)</option>
                  <option value="GBP">Libra (GBP)</option>
                </Select>
              </Field>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3">
              <span className="mr-auto text-[10px] text-muted-foreground">
                {emailChanged
                  ? "El nuevo email será tu usuario de acceso."
                  : "Se guardan nombre y email. Idioma y moneda son visuales; la contraseña, en Seguridad."}
              </span>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={resetProfile}
                disabled={!profileDirty || profilePending}
              >
                Descartar
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                loading={profilePending}
                disabled={!profileDirty || (emailChanged && !emailPassword)}
              >
                <Save className="size-3.5" aria-hidden />
                Guardar cambios
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="py-3">
          <div>
            <CardTitle>Apariencia</CardTitle>
            <CardDescription>
              Tema claro, oscuro o automático según el sistema
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="pt-1">
          <div className="grid grid-cols-3 gap-2 sm:max-w-md">
            {themeOptions.map((option) => {
              const Icon = option.icon;
              const active = theme === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setTheme(option.value)}
                  aria-pressed={active}
                  className={cn(
                    "flex items-center justify-center gap-2 rounded-lg border px-3 py-2.5 text-[11px] font-medium transition-colors",
                    active
                      ? "border-accent bg-accent-soft text-accent-soft-foreground"
                      : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <Icon className="size-3.5" aria-hidden />
                  {option.label}
                  {active ? <Check className="size-3" aria-hidden /> : null}
                </button>
              );
            })}
          </div>
          <p className="mt-3 text-[10px] leading-4 text-muted-foreground">
            El acento de la interfaz se define en la variable CSS{" "}
            <span className="num">--accent</span> y puede cambiarse sin tocar los
            componentes.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="py-3">
          <div>
            <CardTitle>Seguridad</CardTitle>
            <CardDescription>Contraseña, sesiones y cookies</CardDescription>
          </div>
          <ShieldCheck className="size-4 text-positive" aria-hidden />
        </CardHeader>
        <CardContent className="pt-1">
          <form onSubmit={changePassword} className="grid gap-3 sm:grid-cols-2">
            <Field label="Contraseña actual" htmlFor="settings-current-password">
              <Input
                id="settings-current-password"
                name="current_password"
                type="password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setPasswordError(null);
                }}
                autoComplete="current-password"
              />
            </Field>
            <Field
              label="Nueva contraseña"
              htmlFor="settings-new-password"
              error={passwordError ?? undefined}
              hint={
                newPassword
                  ? `${newPassword.length}/12 caracteres mínimos. El servidor aplica Argon2id.`
                  : "Mínimo 12 caracteres. El servidor aplica Argon2id."
              }
            >
              <Input
                id="settings-new-password"
                name="new_password"
                type="password"
                value={newPassword}
                onChange={(event) => {
                  setNewPassword(event.target.value);
                  setPasswordError(null);
                }}
                autoComplete="new-password"
              />
            </Field>
            <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
              <Button
                type="submit"
                variant="primary"
                size="sm"
                loading={passwordPending}
              >
                <KeyRound className="size-3.5" aria-hidden />
                Cambiar contraseña
              </Button>
              <Button
                variant="secondary"
                size="sm"
                loading={sessionsPending}
                onClick={() => void closeAllSessions()}
              >
                Cerrar todas las sesiones
              </Button>
            </div>
          </form>

          <div className="mt-4 border-t border-border pt-3">
            <dl className="grid gap-2 text-[11px] sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground">Último acceso</dt>
                <dd className="mt-0.5 font-medium">
                  {user?.last_login_at ? formatDateTime(user.last_login_at) : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Cookie de sesión</dt>
                <dd className="num mt-0.5 font-medium">__Host-ft_session</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Protección CSRF</dt>
                <dd className="mt-0.5 font-medium">Header X-CSRF-Token</dd>
              </div>
            </dl>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
