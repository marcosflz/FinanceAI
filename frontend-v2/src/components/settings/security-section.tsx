"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Copy,
  DatabaseZap,
  HardDriveDownload,
  KeyRound,
  Loader2,
  LockKeyhole,
  UserPlus,
  Users,
} from "lucide-react";
import { accountDataApi, adminApi, ApiError, authApi } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { DEMO_MODE } from "@/lib/demo";
import type { DatabaseExportFormat } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { RecoveryKeyNotice } from "@/components/auth/recovery-key-notice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Field, Input } from "@/components/ui/form";
import { Segmented } from "@/components/ui/segmented";
import { useToast } from "@/components/ui/toast";

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}

function PasswordInput({
  id,
  value,
  onChange,
  label = "Contraseña actual",
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  label?: string;
}) {
  return (
    <Field label={label} htmlFor={id}>
      <Input
        id={id}
        type="password"
        autoComplete="current-password"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </Field>
  );
}

function EncryptionCard({ encrypted, perUser }: { encrypted: boolean; perUser: boolean }) {
  return (
    <Card>
      <CardHeader className="py-3">
        <div>
          <CardTitle>Cifrado de tus datos</CardTitle>
          <CardDescription>Base de datos propia, cifrada con una clave que deriva de tu contraseña</CardDescription>
        </div>
        <Badge variant={encrypted ? "positive" : "warning"}>
          <LockKeyhole className="size-2.5" aria-hidden />
          {encrypted ? "Cifrado activo" : perUser ? "Sin cifrado" : "Modo de un usuario"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-1.5 pt-0 text-[11px] leading-5 text-muted-foreground">
        {encrypted ? (
          <>
            <p>
              Cuentas, movimientos, cartera y extractos viven en un SQLite propio cifrado con
              SQLCipher. El servidor solo guarda tu clave envuelta: sin tu contraseña (o tu clave
              de recuperación) nadie, tampoco el administrador, puede leerlos en disco ni en
              las copias de seguridad.
            </p>
            <p>
              Mientras tienes la sesión abierta la clave está en memoria del servidor; el
              proveedor de IA que configures ve lo que el asistente le envía.
            </p>
          </>
        ) : (
          <p>
            Este servidor funciona con una base de datos compartida sin cifrado por usuario
            (<span className="num">TENANT_MODE={perUser ? "per_user" : "single"}</span>).
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function AutomationCard({ automationUntil }: { automationUntil?: string | null }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const active = Boolean(automationUntil && new Date(automationUntil) > new Date());

  const mutation = useMutation({
    mutationFn: (enabled: boolean) => authApi.setAutomation(enabled, password),
    onSuccess: (result) => {
      setPassword("");
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      toast({
        title: result.automation_until ? "Automatizaciones activadas" : "Automatizaciones desactivadas",
        description: result.automation_until
          ? `Hasta ${formatDateTime(result.automation_until)}. Se renueva cada vez que entras.`
          : "El worker ya no puede abrir tus datos sin sesión.",
        variant: "success",
      });
    },
    onError: (error) =>
      toast({
        title: "No se pudo cambiar",
        description: errorMessage(error, "Revisa la contraseña."),
        variant: "error",
      }),
  });

  return (
    <Card>
      <CardHeader className="py-3">
        <div>
          <CardTitle>Automatizaciones sin sesión abierta</CardTitle>
          <CardDescription>Permite que las tareas programadas lean tus datos</CardDescription>
        </div>
        <Badge variant={active ? "accent" : "neutral"}>
          <Bot className="size-2.5" aria-hidden />
          {active ? "Activas" : "Solo con sesión"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <p className="text-[11px] leading-5 text-muted-foreground">
          Tu clave se entrega sellada al proceso worker y solo vive en su memoria, con
          caducidad. Si el servidor se reinicia, las tareas esperan a tu siguiente inicio de
          sesión. Nunca se guarda en disco una clave capaz de abrir tus datos.
          {active && automationUntil ? (
            <>
              {" "}Concesión válida hasta{" "}
              <span className="num text-foreground">{formatDateTime(automationUntil)}</span>.
            </>
          ) : null}
        </p>
        <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <PasswordInput id="automation-password" value={password} onChange={setPassword} />
          <Button
            variant={active ? "outline" : "primary"}
            size="sm"
            disabled={!password || mutation.isPending || DEMO_MODE}
            onClick={() => mutation.mutate(!active)}
          >
            {mutation.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
            {active ? "Desactivar" : "Activar"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function RecoveryCard({ email }: { email: string }) {
  const { toast } = useToast();
  const [password, setPassword] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => authApi.regenerateRecoveryKey(email, password),
    onSuccess: (result) => {
      setPassword("");
      setNewKey(result.recovery_key);
    },
    onError: (error) =>
      toast({
        title: "No se pudo generar",
        description: errorMessage(error, "Revisa la contraseña."),
        variant: "error",
      }),
  });

  return (
    <Card>
      <CardHeader className="py-3">
        <div>
          <CardTitle>Clave de recuperación</CardTitle>
          <CardDescription>Genera una nueva si perdiste la anterior; la vieja deja de valer</CardDescription>
        </div>
        <KeyRound className="size-4 text-muted-foreground" aria-hidden />
      </CardHeader>
      <CardContent className="pt-0">
        {newKey ? (
          <RecoveryKeyNotice recoveryKey={newKey} onContinue={() => setNewKey(null)} continueLabel="Hecho" />
        ) : (
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <PasswordInput id="recovery-password" value={password} onChange={setPassword} />
            <Button
              size="sm"
              disabled={!password || mutation.isPending || DEMO_MODE}
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
              Generar nueva clave
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ExportCard({ encrypted }: { encrypted: boolean }) {
  const { toast } = useToast();
  const [format, setFormat] = useState<DatabaseExportFormat>("sqlite");
  const [password, setPassword] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const mutation = useMutation({
    mutationFn: () => accountDataApi.exportDatabase(password, format, passphrase),
    onSuccess: ({ blob, filename }) => {
      setPassword("");
      setPassphrase("");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
      toast({ title: "Base de datos descargada", description: filename, variant: "success" });
    },
    onError: (error) =>
      toast({
        title: "No se pudo exportar",
        description: errorMessage(error, "Revisa la contraseña."),
        variant: "error",
      }),
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate();
  }

  const needsPassphrase = format === "sqlcipher";
  return (
    <Card>
      <CardHeader className="py-3">
        <div>
          <CardTitle>Descargar tu base de datos</CardTitle>
          <CardDescription>Copia completa en SQLite: tus datos, tu control</CardDescription>
        </div>
        <HardDriveDownload className="size-4 text-muted-foreground" aria-hidden />
      </CardHeader>
      <CardContent className="pt-0">
        <form className="space-y-3" onSubmit={onSubmit}>
          <Segmented
            aria-label="Formato de exportación"
            value={format}
            onChange={setFormat}
            options={[
              { value: "sqlite", label: "SQLite sin cifrar" },
              {
                value: "sqlcipher",
                label: "SQLCipher con passphrase",
                disabled: !encrypted,
                title: encrypted ? undefined : "Requiere cifrado por usuario",
              },
            ]}
          />
          <p className="text-[11px] leading-5 text-muted-foreground">
            {needsPassphrase
              ? "Se cifra con una passphrase que eliges ahora (no tu contraseña). Ábrela con DB Browser for SQLite (SQLCipher) o el CLI sqlcipher."
              : "Se abre con cualquier herramienta SQLite. Guárdala en un lugar seguro: no lleva cifrado."}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <PasswordInput id="export-password" value={password} onChange={setPassword} />
            {needsPassphrase ? (
              <Field label="Passphrase de la copia" htmlFor="export-passphrase" hint="Mínimo 12 caracteres.">
                <Input
                  id="export-passphrase"
                  type="password"
                  autoComplete="new-password"
                  value={passphrase}
                  onChange={(event) => setPassphrase(event.target.value)}
                />
              </Field>
            ) : null}
          </div>
          <div className="flex justify-end">
            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={
                DEMO_MODE ||
                mutation.isPending ||
                !password ||
                (needsPassphrase && passphrase.length < 12)
              }
            >
              {mutation.isPending ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <DatabaseZap className="size-3.5" aria-hidden />
              )}
              Descargar
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function UsersCard({ currentUserId }: { currentUserId: number }) {
  const { toast } = useToast();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => adminApi.listUsers() });

  const invite = useMutation({
    mutationFn: () => adminApi.invite(email.trim()),
    onSuccess: (result) => {
      setEmail("");
      setInviteLink(`${window.location.origin}${result.invite_path}`);
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (error) =>
      toast({
        title: "No se pudo invitar",
        description: errorMessage(error, "Revisa el email."),
        variant: "error",
      }),
  });

  const toggle = useMutation({
    mutationFn: ({ id, disabled }: { id: number; disabled: boolean }) =>
      adminApi.setDisabled(id, disabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "users"] }),
    onError: (error) =>
      toast({ title: "No se pudo actualizar", description: errorMessage(error, ""), variant: "error" }),
  });

  async function onToggle(id: number, emailLabel: string, disabled: boolean) {
    if (disabled) {
      const ok = await confirm({
        title: `¿Deshabilitar a ${emailLabel}?`,
        description: "Se cierran sus sesiones y se revocan sus automatizaciones. Sus datos siguen cifrados e intactos.",
        confirmLabel: "Deshabilitar",
        tone: "danger",
      });
      if (!ok) return;
    }
    toggle.mutate({ id, disabled });
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <div>
          <CardTitle>Usuarios</CardTitle>
          <CardDescription>
            Alta por invitación: cada persona elige su contraseña y nadie más puede abrir sus datos
          </CardDescription>
        </div>
        <Users className="size-4 text-muted-foreground" aria-hidden />
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <form
          className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            invite.mutate();
          }}
        >
          <Field label="Email de la persona invitada" htmlFor="invite-email">
            <Input
              id="invite-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>
          <Button type="submit" size="sm" disabled={!email || invite.isPending}>
            <UserPlus className="size-3.5" aria-hidden />
            Crear invitación
          </Button>
        </form>

        {inviteLink ? (
          <div className="space-y-1.5 rounded-lg border border-border bg-subtle p-2.5">
            <p className="text-[11px] text-muted-foreground">
              Enlace válido 7 días. Envíalo por un canal privado; solo se muestra ahora.
            </p>
            <div className="flex items-center gap-2">
              <code className="num min-w-0 flex-1 truncate text-[11px]">{inviteLink}</code>
              <Button
                size="sm"
                onClick={() => navigator.clipboard.writeText(inviteLink).catch(() => undefined)}
              >
                <Copy className="size-3.5" aria-hidden />
                Copiar
              </Button>
            </div>
          </div>
        ) : null}

        <div className="divide-y divide-border rounded-lg border border-border">
          {(users.data?.items ?? []).map((item) => (
            <div key={item.id} className="flex items-center justify-between gap-3 px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-[12px] font-medium">{item.email}</p>
                <p className="text-[10px] text-muted-foreground">
                  {item.role === "admin" ? "Admin" : "Usuario"}
                  {item.last_login_at ? ` · último acceso ${formatDateTime(item.last_login_at)}` : ""}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {item.invite_pending ? <Badge variant="warning">Invitación pendiente</Badge> : null}
                {item.encrypted ? <Badge variant="positive">Cifrado</Badge> : null}
                {item.disabled ? <Badge variant="negative">Deshabilitado</Badge> : null}
                {item.id !== currentUserId ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onToggle(item.id, item.email, !item.disabled)}
                  >
                    {item.disabled ? "Habilitar" : "Deshabilitar"}
                  </Button>
                ) : null}
              </div>
            </div>
          ))}
          {users.isLoading ? (
            <p className="px-3 py-2 text-[11px] text-muted-foreground">Cargando…</p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export function SecuritySection() {
  const me = useMe();
  const user = me.data;
  const encrypted = Boolean(user?.tenancy?.encryption);
  const perUser = user?.tenancy?.mode === "per_user";

  return (
    <div className="space-y-4">
      <EncryptionCard encrypted={encrypted} perUser={perUser} />
      <ExportCard encrypted={encrypted} />
      {encrypted ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <AutomationCard automationUntil={user?.automation_until} />
          {user ? <RecoveryCard email={user.email} /> : null}
        </div>
      ) : null}
      {user?.role === "admin" && perUser ? <UsersCard currentUserId={user.id} /> : null}
    </div>
  );
}
