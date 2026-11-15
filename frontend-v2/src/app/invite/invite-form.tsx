"use client";

import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Loader2 } from "lucide-react";
import { ApiError, authApi } from "@/lib/api";
import { AuthCard } from "@/components/auth/auth-card";
import { RecoveryKeyNotice } from "@/components/auth/recovery-key-notice";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";

export function InviteForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recoveryKey, setRecoveryKey] = useState<string | null>(null);

  function goHome() {
    router.replace("/");
    router.refresh();
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    if (password !== confirm) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    setError(null);
    setPending(true);
    try {
      const response = await authApi.acceptInvite({
        token,
        password,
        name: name.trim() || null,
      });
      if (response.recovery_key) setRecoveryKey(response.recovery_key);
      else goHome();
    } catch (inviteError) {
      setError(
        inviteError instanceof ApiError && inviteError.status === 422
          ? inviteError.message
          : "La invitación no es válida o ha caducado. Pide una nueva al administrador.",
      );
    } finally {
      setPending(false);
    }
  }

  if (recoveryKey) {
    return (
      <AuthCard
        eyebrow="Cuenta creada"
        title="Tu clave de recuperación"
        description="Tu base de datos ya está cifrada con tu contraseña."
      >
        <RecoveryKeyNotice
          recoveryKey={recoveryKey}
          onContinue={goHome}
          continueLabel="Entrar en el panel"
        />
      </AuthCard>
    );
  }

  return (
    <AuthCard
      eyebrow="Invitación"
      title="Crea tu cuenta"
      description="Elige tu contraseña. El administrador no la conoce ni puede leer tus datos."
    >
      {!token ? (
        <p className="rounded-lg border border-negative/25 bg-negative-soft px-3 py-2 text-[12px] text-negative">
          Falta el token de invitación en el enlace.
        </p>
      ) : (
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <Field label="Nombre (opcional)" htmlFor="invite-name">
            <Input
              id="invite-name"
              autoComplete="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field label="Contraseña" htmlFor="invite-password" hint="Mínimo 12 caracteres.">
            <Input
              id="invite-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </Field>
          <Field label="Repite la contraseña" htmlFor="invite-confirm">
            <Input
              id="invite-confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              required
            />
          </Field>
          {error ? (
            <p
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
            disabled={pending || !password || !confirm}
          >
            {pending ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <ArrowRight className="size-3.5" aria-hidden />
            )}
            Crear cuenta
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
