"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2 } from "lucide-react";
import { ApiError, authApi } from "@/lib/api";
import { AuthCard } from "@/components/auth/auth-card";
import { RecoveryKeyNotice } from "@/components/auth/recovery-key-notice";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";

export function RecoverForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [recoveryKey, setRecoveryKey] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newKey, setNewKey] = useState<string | null>(null);

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
      const response = await authApi.recover({
        email: email.trim(),
        recovery_key: recoveryKey,
        new_password: password,
      });
      setNewKey(response.recovery_key ?? null);
      if (!response.recovery_key) {
        router.replace("/");
        router.refresh();
      }
    } catch (recoverError) {
      if (recoverError instanceof ApiError && recoverError.status === 422) {
        setError(recoverError.message);
      } else if (recoverError instanceof ApiError && recoverError.status === 429) {
        setError("Demasiados intentos. Espera un minuto antes de volver a probar.");
      } else {
        setError("Email o clave de recuperación incorrectos.");
      }
    } finally {
      setPending(false);
    }
  }

  if (newKey) {
    return (
      <AuthCard
        eyebrow="Cuenta recuperada"
        title="Nueva clave de recuperación"
        description="La clave anterior ya no sirve. Guarda esta antes de continuar."
      >
        <RecoveryKeyNotice
          recoveryKey={newKey}
          continueLabel="Entrar en el panel"
          onContinue={() => {
            router.replace("/");
            router.refresh();
          }}
        />
      </AuthCard>
    );
  }

  return (
    <AuthCard
      eyebrow="Recuperar cuenta"
      title="Restablece tu contraseña"
      description="Con la clave de recuperación que guardaste al crear la cuenta. Tus datos se conservan."
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <Field label="Email" htmlFor="recover-email">
          <Input
            id="recover-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </Field>
        <Field
          label="Clave de recuperación"
          htmlFor="recover-key"
          hint="8 grupos de 4 caracteres; los guiones son opcionales."
        >
          <Input
            id="recover-key"
            autoComplete="off"
            spellCheck={false}
            className="num uppercase"
            placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"
            value={recoveryKey}
            onChange={(event) => setRecoveryKey(event.target.value)}
            required
          />
        </Field>
        <Field label="Nueva contraseña" htmlFor="recover-password" hint="Mínimo 12 caracteres.">
          <Input
            id="recover-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </Field>
        <Field label="Repite la contraseña" htmlFor="recover-confirm">
          <Input
            id="recover-confirm"
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
          disabled={pending || !email || !recoveryKey || !password || !confirm}
        >
          {pending ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <ArrowRight className="size-3.5" aria-hidden />
          )}
          Restablecer contraseña
        </Button>
        <p className="text-center text-[12px] text-muted-foreground">
          <Link href="/login" className="underline underline-offset-2 hover:text-foreground">
            Volver al acceso
          </Link>
        </p>
      </form>
    </AuthCard>
  );
}
