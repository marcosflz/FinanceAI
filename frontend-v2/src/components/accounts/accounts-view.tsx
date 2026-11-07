"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArchiveRestore,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleDollarSign,
  CreditCard,
  Eye,
  EyeOff,
  Landmark,
  Link2,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wallet,
  X,
} from "lucide-react";
import { accountsApi } from "@/lib/api";
import { DEMO_MODE, sleep, withMock } from "@/lib/demo";
import {
  mockAccounts,
  mockMovements,
  mockTransferSuggestions,
} from "@/lib/mock";
import type { Account, AccountType, TransferSuggestion } from "@/lib/types";
import { cn, formatDate, formatMoney, maskIban, relativeDate, toNumber } from "@/lib/utils";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { DatePicker, toIsoDate } from "@/components/ui/date-picker";
import { useToast } from "@/components/ui/toast";

const EMPTY_ACCOUNTS: Account[] = [];
const EMPTY_SUGGESTIONS: TransferSuggestion[] = [];

const accountTypeLabels: Record<AccountType, string> = {
  broker_central: "Cuenta principal",
  efectivo_externa: "Cuenta vinculada",
};

interface AccountFormState {
  nombre: string;
  tipo: AccountType;
  iban: string;
  patrones: string;
  balanceInicial: string;
  balanceInicialFecha: string;
}

const emptyForm: AccountFormState = {
  nombre: "",
  tipo: "efectivo_externa",
  iban: "",
  patrones: "",
  balanceInicial: "",
  balanceInicialFecha: "",
};

function simplePatternMatch(haystack: string, pattern: string): boolean {
  const normalized = pattern.replace(/\*/g, "").trim().toLowerCase();
  if (!normalized) return false;
  return haystack.toLowerCase().includes(normalized);
}

function AccountCard({
  account,
  onEdit,
  onReapply,
  onDelete,
  onRestore,
  deleting,
  reapplying,
}: {
  account: Account;
  onEdit: () => void;
  onReapply: () => void;
  onDelete: () => void;
  onRestore: () => void;
  deleting: boolean;
  reapplying: boolean;
}) {
  const difference = account.reconciliacion_diferencia;
  const reconciled = difference !== null && Math.abs(toNumber(difference)) < 0.005;
  const archived = !account.activo;

  return (
    <Card className={cn("flex flex-col", archived && "opacity-70")}>
      <CardHeader className="px-4 pt-4">
        <div className="flex min-w-0 items-start gap-2.5">
          <span
            className="mt-1 size-2.5 shrink-0 rounded-[3px]"
            style={{ backgroundColor: account.color }}
            aria-hidden
          />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <CardTitle className="truncate">{account.nombre}</CardTitle>
              {account.es_propia ? (
                <Badge variant="accent" className="shrink-0">
                  Propia
                </Badge>
              ) : null}
              {archived ? (
                <Badge variant="neutral" className="shrink-0">
                  Archivada
                </Badge>
              ) : null}
            </div>
            <CardDescription>
              {accountTypeLabels[account.tipo]}
              {account.broker ? ` · ${account.broker}` : ""}
            </CardDescription>
          </div>
        </div>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={onEdit}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label={`Editar ${account.nombre}`}
          >
            <Pencil className="size-3.5" aria-hidden />
          </button>
          {archived ? (
            <button
              type="button"
              onClick={onRestore}
              className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              aria-label={`Restaurar ${account.nombre}`}
              title="Restaurar cuenta"
            >
              <ArchiveRestore className="size-3.5" aria-hidden />
            </button>
          ) : (
            <button
              type="button"
              onClick={onDelete}
              disabled={deleting}
              className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-negative-soft hover:text-negative disabled:opacity-50"
              aria-label={`Eliminar ${account.nombre}`}
              title="Eliminar o archivar cuenta"
            >
              {deleting ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <Trash2 className="size-3.5" aria-hidden />
              )}
            </button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col px-4 pt-3">
        <p className="num text-[24px] font-semibold leading-7 tracking-[-0.02em]">
          {formatMoney(account.balance)}
        </p>
        <p className="num mt-1 text-[10px] text-muted-foreground">
          {maskIban(account.iban)}
        </p>
        {account.balances && account.balances.length > 1 ? (
          <div className="mt-1 flex flex-wrap gap-1">
            {account.balances.map((balance) => (
              <span
                key={balance.currency}
                className="num rounded bg-muted px-1.5 py-0.5 text-[9px] text-muted-foreground"
                title={`Equivalente ${formatMoney(balance.balance_eur)}`}
              >
                {formatMoney(balance.balance, { currency: balance.currency })}
              </span>
            ))}
          </div>
        ) : null}
        {toNumber(account.balance_inicial) !== 0 ? (
          <p className="num mt-0.5 text-[10px] text-muted-foreground">
            Saldo inicial: {formatMoney(account.balance_inicial ?? 0)}
            {account.balance_inicial_fecha
              ? ` · ${formatDate(account.balance_inicial_fecha, "short")}`
              : ""}
          </p>
        ) : null}

        <div className="mt-3 space-y-1.5 border-t border-border pt-2.5">
          <div className="flex items-center justify-between gap-2 text-[10px]">
            <span className="text-muted-foreground">Conciliación</span>
            {reconciled ? (
              <span className="inline-flex items-center gap-1 text-positive">
                <CheckCircle2 className="size-3" aria-hidden />
                {account.last_reconciled_at
                  ? relativeDate(account.last_reconciled_at)
                  : "Al día"}
              </span>
            ) : difference !== null ? (
              <span className="inline-flex items-center gap-1 text-warning">
                <AlertTriangle className="size-3" aria-hidden />
                {formatMoney(difference, { signDisplay: "always" })}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-muted-foreground">
                <AlertTriangle className="size-3" aria-hidden />
                Sin conciliar
              </span>
            )}
          </div>
          {account.last_reconciled_at ? (
            <p className="text-[10px] text-muted-foreground">
              Última: {formatDate(account.last_reconciled_at, "medium")}
            </p>
          ) : null}
        </div>

        <div className="mt-3 flex flex-wrap gap-1">
          {account.alias_patrones.slice(0, 3).map((pattern) => (
            <Badge key={pattern} variant="outline" className="font-mono text-[9px]">
              {pattern}
            </Badge>
          ))}
          {account.alias_patrones.length > 3 ? (
            <Badge variant="neutral">+{account.alias_patrones.length - 3}</Badge>
          ) : null}
          {account.alias_patrones.length === 0 ? (
            <span className="text-[10px] text-muted-foreground">Sin patrones</span>
          ) : null}
        </div>

        <div className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-2.5">
          {archived ? (
            <span className="text-[10px] text-muted-foreground">
              No participa en la detección
            </span>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-1.5"
              onClick={onReapply}
              disabled={reapplying}
            >
              {reapplying ? (
                <Loader2 className="size-3 animate-spin" aria-hidden />
              ) : (
                <Sparkles className="size-3" aria-hidden />
              )}
              Reaplicar patrones
            </Button>
          )}
          <span className="num text-[9px] text-muted-foreground">{account.moneda}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function TransferRow({
  suggestion,
  status,
  onResolve,
}: {
  suggestion: TransferSuggestion;
  status: "pendiente" | "confirmada" | "descartada";
  onResolve: (resolution: "confirmada" | "descartada") => void;
}) {
  if (status !== "pendiente") {
    return (
      <div className="flex items-center gap-2 px-4 py-2.5 text-[11px] text-muted-foreground">
        <CheckCircle2
          className={cn("size-3.5", status === "confirmada" ? "text-positive" : "text-muted-foreground")}
          aria-hidden
        />
        <span className="truncate">
          {suggestion.outbound.merchant} · {formatMoney(suggestion.amount)}
        </span>
        <Badge
          variant={status === "confirmada" ? "positive" : "neutral"}
          className="ml-auto"
        >
          {status === "confirmada" ? "Vinculada" : "Descartada"}
        </Badge>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-[11px]">
          <span className="truncate font-medium">
            {suggestion.outbound.account?.nombre ?? "Origen"}
          </span>
          <ArrowRight className="size-3 shrink-0 text-muted-foreground" aria-hidden />
          <span className="truncate font-medium">
            {suggestion.inbound.account?.nombre ?? "Destino"}
          </span>
          <Badge variant="accent" className="ml-1 shrink-0">
            {Math.round(suggestion.score * 100)} %
          </Badge>
        </div>
        <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
          {suggestion.outbound.merchant} → {suggestion.inbound.merchant} ·{" "}
          {formatDate(suggestion.date, "medium")}
        </p>
      </div>
      <div className="flex items-center justify-between gap-2 sm:justify-end">
        <span className="num text-[12px] font-medium">
          {formatMoney(suggestion.amount)}
        </span>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => onResolve("confirmada")}
            className="inline-flex size-7 items-center justify-center rounded-md border border-border text-positive transition-colors hover:bg-positive-soft"
            aria-label="Confirmar transferencia interna"
            title="Confirmar vínculo"
          >
            <Check className="size-3.5" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => onResolve("descartada")}
            className="inline-flex size-7 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Descartar transferencia interna"
            title="No es una transferencia interna"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </div>
      </div>
    </div>
  );
}

export function AccountsView() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const confirm = useConfirm();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<AccountFormState>(emptyForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [localAccounts, setLocalAccounts] = useState<Account[]>([]);
  const [localOverrides, setLocalOverrides] = useState<Record<number, Partial<Account>>>({});
  const [reapplying, setReapplying] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [transferStatus, setTransferStatus] = useState<
    Record<number, "confirmada" | "descartada">
  >({});

  const accountsQuery = useQuery({
    queryKey: ["accounts", "all"],
    queryFn: () => withMock(() => accountsApi.list(true), { items: mockAccounts }),
  });

  const transfersQuery = useQuery({
    queryKey: ["transfers", "suggestions"],
    queryFn: () =>
      withMock(() => accountsApi.transferSuggestions(), {
        items: mockTransferSuggestions,
      }),
  });

  const baseAccounts = accountsQuery.data?.items ?? (DEMO_MODE ? mockAccounts : EMPTY_ACCOUNTS);
  const accounts = useMemo(
    () => [
      ...baseAccounts.map((account) => ({
        ...account,
        ...localOverrides[account.id],
      })),
      ...localAccounts,
    ],
    [baseAccounts, localOverrides, localAccounts],
  );

  const activeAccounts = accounts.filter((account) => account.activo);
  const visibleAccounts = includeInactive ? accounts : activeAccounts;
  const archivedCount = accounts.length - activeAccounts.length;
  const total = activeAccounts.reduce(
    (sum, account) => sum + toNumber(account.balance),
    0,
  );
  const unreconciled = activeAccounts.filter(
    (account) =>
      account.reconciliacion_diferencia === null ||
      Math.abs(toNumber(account.reconciliacion_diferencia)) >= 0.005,
  ).length;

  const suggestions =
    transfersQuery.data?.items ?? (DEMO_MODE ? mockTransferSuggestions : EMPTY_SUGGESTIONS);
  const pendingSuggestions = suggestions.filter(
    (suggestion) => !transferStatus[suggestion.id],
  );

  const patternMatches = useMemo(() => {
    if (!DEMO_MODE) return null;
    const patterns = form.patrones
      .split(/[\n,]+/)
      .map((pattern) => pattern.trim())
      .filter(Boolean);
    if (patterns.length === 0) return 0;
    return mockMovements.filter((movement) =>
      patterns.some((pattern) =>
        simplePatternMatch(
          `${movement.merchant ?? ""} ${movement.description ?? ""} ${movement.counterparty_name ?? ""}`,
          pattern,
        ),
      ),
    ).length;
  }, [form.patrones]);

  function openCreate() {
    const hasActive = baseAccounts.some((account) => account.activo);
    setEditingId(null);
    setForm({
      ...emptyForm,
      tipo: hasActive ? "efectivo_externa" : "broker_central",
    });
    setFormError(null);
    setShowForm(true);
  }

  function openEdit(account: Account) {
    setEditingId(account.id);
    setForm({
      nombre: account.nombre,
      tipo: account.tipo,
      iban: account.iban ?? "",
      patrones: account.alias_patrones.join(", "),
      balanceInicial:
        toNumber(account.balance_inicial) !== 0
          ? String(toNumber(account.balance_inicial))
          : "",
      balanceInicialFecha: account.balance_inicial_fecha ?? "",
    });
    setFormError(null);
    setShowForm(true);
  }

  async function submitForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form.nombre.trim()) {
      setFormError("El nombre de la cuenta es obligatorio.");
      return;
    }
    const normalizedIban = form.iban.replace(/\s+/g, "").toUpperCase();
    if (normalizedIban && !/^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$/.test(normalizedIban)) {
      setFormError("El IBAN no tiene un formato válido.");
      return;
    }
    const initialRaw = form.balanceInicial.trim().replace(",", ".");
    const initialValue = initialRaw ? Number(initialRaw) : 0;
    if (!Number.isFinite(initialValue)) {
      setFormError("El saldo inicial debe ser un número válido.");
      return;
    }

    const payload: Partial<Account> = {
      nombre: form.nombre.trim(),
      tipo: form.tipo,
      iban: normalizedIban || null,
      balance_inicial: initialValue,
      balance_inicial_fecha: form.balanceInicialFecha || null,
      alias_patrones: form.patrones
        .split(/[\n,]+/)
        .map((pattern) => pattern.trim())
        .filter(Boolean),
    };

    setSubmitting(true);
    try {
      if (DEMO_MODE) {
        await sleep(300);
        if (editingId !== null) {
          setLocalOverrides((current) => ({
            ...current,
            [editingId]: { ...current[editingId], ...payload },
          }));
        } else {
          setLocalAccounts((current) => [
            ...current,
            {
              id: Date.now(),
              nombre: payload.nombre ?? "Cuenta",
              tipo: payload.tipo ?? "efectivo_externa",
              broker: null,
              iban: payload.iban ?? null,
              alias_patrones: payload.alias_patrones ?? [],
              es_propia: true,
              moneda: "EUR",
              color: "#64748b",
              activo: true,
              balance: 0,
              last_reconciled_at: null,
              reconciliacion_diferencia: null,
            },
          ]);
        }
      } else if (editingId !== null) {
        await accountsApi.update(editingId, payload);
        await queryClient.invalidateQueries({ queryKey: ["accounts"] });
      } else {
        await accountsApi.create(payload);
        await queryClient.invalidateQueries({ queryKey: ["accounts"] });
      }

      toast({
        title: editingId !== null ? "Cuenta actualizada" : "Cuenta creada",
        description: DEMO_MODE
          ? "Cambio aplicado en memoria (modo demo)."
          : `${payload.nombre} · se re-etiquetarán los movimientos coincidentes.`,
        variant: "success",
      });
      setShowForm(false);
      setEditingId(null);
      setForm(emptyForm);
    } catch {
      setFormError("No se pudo guardar la cuenta. Revisa la sesión y vuelve a intentarlo.");
    } finally {
      setSubmitting(false);
    }
  }

  async function reapplyPatterns(account: Account) {
    setReapplying(account.id);
    try {
      const result = DEMO_MODE
        ? await sleep(350).then(() => ({
            matches: account.alias_patrones.length * 6,
            updated: account.alias_patrones.length * 4,
          }))
        : await accountsApi.reapplyPatterns(account.id);
      toast({
        title: "Patrones reaplicados",
        description: `${result.matches} coincidencias revisadas · ${result.updated} movimientos actualizados.`,
        variant: "success",
      });
      if (!DEMO_MODE) await queryClient.invalidateQueries({ queryKey: ["accounts"] });
    } catch {
      toast({
        title: "No se pudieron reaplicar los patrones",
        description: "Comprueba que la cuenta y sus patrones son válidos.",
        variant: "error",
      });
    } finally {
      setReapplying(null);
    }
  }

  async function deleteAccount(account: Account) {
    const confirmed = await confirm({
      title: `¿Eliminar «${account.nombre}»?`,
      description:
        "Si tiene movimientos o extractos no se borran: la cuenta se archiva y deja de " +
        "aparecer. Podrás restaurarla desde «Ver archivadas».",
      confirmLabel: "Eliminar cuenta",
      tone: "danger",
    });
    if (!confirmed) return;

    setDeleting(account.id);
    try {
      const result = DEMO_MODE
        ? { mode: "hard" as const, message: "Cuenta eliminada (demo)." }
        : await accountsApi.remove(account.id);
      if (DEMO_MODE) {
        setLocalOverrides((current) => ({
          ...current,
          [account.id]: { ...current[account.id], activo: false },
        }));
      }
      if (editingId === account.id) {
        setShowForm(false);
        setEditingId(null);
      }
      toast({
        title:
          result.mode === "archived" ? "Cuenta archivada" : "Cuenta eliminada",
        description: result.message,
        variant: "success",
      });
      if (!DEMO_MODE) {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["accounts"] }),
          queryClient.invalidateQueries({ queryKey: ["analytics"] }),
          queryClient.invalidateQueries({ queryKey: ["data-health"] }),
          queryClient.invalidateQueries({ queryKey: ["movements"] }),
        ]);
      }
    } catch {
      toast({
        title: "No se pudo eliminar la cuenta",
        description: "Revisa la sesión y vuelve a intentarlo.",
        variant: "error",
      });
    } finally {
      setDeleting(null);
    }
  }

  async function restoreAccount(account: Account) {
    try {
      if (!DEMO_MODE) {
        await accountsApi.update(account.id, { activo: true });
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["accounts"] }),
          queryClient.invalidateQueries({ queryKey: ["analytics"] }),
          queryClient.invalidateQueries({ queryKey: ["data-health"] }),
        ]);
      } else {
        setLocalOverrides((current) => ({
          ...current,
          [account.id]: { ...current[account.id], activo: true },
        }));
      }
      toast({
        title: "Cuenta restaurada",
        description: `${account.nombre} vuelve a estar disponible para importar.`,
        variant: "success",
      });
    } catch {
      toast({
        title: "No se pudo restaurar la cuenta",
        description: "Revisa la sesión y vuelve a intentarlo.",
        variant: "error",
      });
    }
  }

  async function resolveTransfer(
    suggestion: TransferSuggestion,
    resolution: "confirmada" | "descartada",
  ) {
    setTransferStatus((current) => ({ ...current, [suggestion.id]: resolution }));
    try {
      if (!DEMO_MODE) {
        if (resolution === "confirmada") {
          await accountsApi.linkTransfer({
            outbound_id: suggestion.outbound.id,
            inbound_id: suggestion.inbound.id,
          });
        } else {
          await accountsApi.dismissTransfer({
            outbound_id: suggestion.outbound.id,
            inbound_id: suggestion.inbound.id,
          });
        }
        await queryClient.invalidateQueries({ queryKey: ["transfers", "suggestions"] });
      }
      toast({
        title:
          resolution === "confirmada"
            ? "Transferencia interna vinculada"
            : "Sugerencia descartada",
        description:
          resolution === "confirmada"
            ? "Los dos movimientos quedan fuera de ingresos y gastos."
            : "El par no volverá a proponerse.",
        variant: "success",
      });
    } catch {
      setTransferStatus((current) => {
        const next = { ...current };
        delete next[suggestion.id];
        return next;
      });
      toast({
        title: "No se pudo guardar la decisión",
        description: "La API v3 no está disponible.",
        variant: "error",
      });
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Tesorería"
        title="Cuentas"
        description="Cada extracto pertenece a una cuenta. Aquí ves el saldo calculado con sus movimientos; las transferencias internas no cuentan como gasto ni ingreso."
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setIncludeInactive((current) => !current)}
            >
              {includeInactive ? (
                <EyeOff className="size-3.5" aria-hidden />
              ) : (
                <Eye className="size-3.5" aria-hidden />
              )}
              {includeInactive
                ? "Ocultar archivadas"
                : `Ver archivadas${archivedCount > 0 ? ` (${archivedCount})` : ""}`}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void accountsQuery.refetch()}
              loading={accountsQuery.isFetching}
            >
              <RefreshCw className="size-3.5" aria-hidden />
              Recargar
            </Button>
            <Button variant="primary" size="sm" onClick={openCreate}>
              <Plus className="size-3.5" aria-hidden />
              Añadir cuenta
            </Button>
          </>
        }
      />

      {showForm ? (
        <Card className="animate-fade-in">
          <CardHeader className="py-3">
            <div>
              <CardTitle>{editingId !== null ? "Editar cuenta" : "Nueva cuenta"}</CardTitle>
              <CardDescription>
                Elige esta cuenta al importar un extracto. IBAN y patrones
                ayudan a detectar transferencias internas y a conciliar saldos.
              </CardDescription>
            </div>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Cerrar formulario"
            >
              <X className="size-4" aria-hidden />
            </button>
          </CardHeader>
          <CardContent className="pt-0">
            <form onSubmit={submitForm} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Nombre" htmlFor="account-name">
                <Input
                  id="account-name"
                  value={form.nombre}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, nombre: event.target.value }))
                  }
                  placeholder="Revolut"
                  required
                />
              </Field>
              <Field label="Tipo" htmlFor="account-type">
                <Select
                  id="account-type"
                  value={form.tipo}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      tipo: event.target.value as AccountType,
                    }))
                  }
                >
                  <option value="broker_central">Cuenta principal</option>
                  <option value="efectivo_externa">Cuenta vinculada</option>
                </Select>
              </Field>
              <Field
                label="IBAN"
                htmlFor="account-iban"
                hint="Opcional. Se guarda normalizado."
                className="lg:col-span-2"
              >
                <Input
                  id="account-iban"
                  value={form.iban}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, iban: event.target.value }))
                  }
                  placeholder="ES00 0000 0000 0000 0000"
                  className="num"
                  autoComplete="off"
                />
              </Field>
              <Field
                label="Saldo inicial"
                htmlFor="account-balance-initial"
                hint="Opcional. Saldo al inicio del primer extracto importado."
                className="lg:col-span-2"
              >
                <Input
                  id="account-balance-initial"
                  type="number"
                  step="0.01"
                  value={form.balanceInicial}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      balanceInicial: event.target.value,
                    }))
                  }
                  placeholder="0,00"
                  className="num"
                  inputMode="decimal"
                />
              </Field>
              <Field
                label="Fecha del saldo inicial"
                htmlFor="account-balance-initial-date"
                hint="Opcional. El saldo se calcula con movimientos desde esta fecha."
                className="lg:col-span-2"
              >
                <DatePicker
                  id="account-balance-initial-date"
                  aria-label="Fecha del saldo inicial"
                  placeholder="Sin fecha"
                  max={toIsoDate(new Date())}
                  value={form.balanceInicialFecha}
                  onChange={(value) =>
                    setForm((current) => ({
                      ...current,
                      balanceInicialFecha: value,
                    }))
                  }
                />
              </Field>
              <Field
                label="Patrones de contraparte"
                htmlFor="account-patterns"
                hint="Separados por comas. Admite comodines (*)."
                className="sm:col-span-2 lg:col-span-4"
              >
                <Textarea
                  id="account-patterns"
                  value={form.patrones}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, patrones: event.target.value }))
                  }
                  rows={2}
                  placeholder="Revolut**5844*, Marcos Florez Fernandez, Bunq test*"
                  className="min-h-16"
                />
              </Field>

              <div className="flex flex-wrap items-center gap-3 sm:col-span-2 lg:col-span-4">
                <Button type="submit" variant="primary" size="sm" loading={submitting}>
                  {editingId !== null ? "Guardar cambios" : "Crear cuenta"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setShowForm(false);
                    setEditingId(null);
                  }}
                >
                  Cancelar
                </Button>
                {patternMatches !== null && form.patrones.trim() ? (
                  <span className="text-[10px] text-muted-foreground">
                    {patternMatches} movimientos coinciden en el histórico de ejemplo.
                  </span>
                ) : null}
                {formError ? (
                  <span role="alert" className="text-[11px] text-negative">
                    {formError}
                  </span>
                ) : null}
              </div>
            </form>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="card px-4 py-3">
          <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            <Wallet className="size-3" aria-hidden />
            Saldo de cuentas activas
          </p>
          <p className="num mt-1 text-[22px] font-semibold leading-7">{formatMoney(total)}</p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            {activeAccounts.length} activas
            {archivedCount > 0 ? ` · ${archivedCount} archivadas` : ""} · EUR
          </p>
        </div>
        <div className="card px-4 py-3">
          <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            <ShieldCheck className="size-3" aria-hidden />
            Conciliadas
          </p>
          <p className="num mt-1 text-[22px] font-semibold leading-7">
            {activeAccounts.length - unreconciled} / {activeAccounts.length}
          </p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            {unreconciled > 0 ? `${unreconciled} requieren revisión` : "Todo cuadra"}
          </p>
        </div>
        <div className="card px-4 py-3">
          <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            <Link2 className="size-3" aria-hidden />
            Transferencias sugeridas
          </p>
          <p className="num mt-1 text-[22px] font-semibold leading-7">{pendingSuggestions.length}</p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            Pares pendientes de confirmar
          </p>
        </div>
      </div>

      {accountsQuery.isLoading ? (
        <PageSkeleton />
      ) : accountsQuery.isError ? (
        <ErrorState
          title="No se pudieron cargar las cuentas"
          action={
            <Button variant="secondary" size="sm" onClick={() => accountsQuery.refetch()}>
              <RefreshCw className="size-3.5" aria-hidden />
              Reintentar
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visibleAccounts.map((account) => (
            <AccountCard
              key={account.id}
              account={account}
              onEdit={() => openEdit(account)}
              onReapply={() => void reapplyPatterns(account)}
              onDelete={() => void deleteAccount(account)}
              onRestore={() => void restoreAccount(account)}
              deleting={deleting === account.id}
              reapplying={reapplying === account.id}
            />
          ))}
          <button
            type="button"
            onClick={openCreate}
            className="flex min-h-[220px] flex-col items-center justify-center rounded-xl border border-dashed border-input bg-card text-muted-foreground transition-colors hover:border-accent hover:bg-accent-soft/30 hover:text-foreground"
          >
            <Plus className="mb-2 size-5" aria-hidden />
            <span className="text-[12px] font-medium">Añadir cuenta</span>
            <span className="mt-0.5 text-[10px]">IBAN, patrones y saldo inicial</span>
          </button>
        </div>
      )}

      <Card className="overflow-hidden">
        <CardHeader className="py-3">
          <div>
            <CardTitle>Transferencias internas sugeridas</CardTitle>
            <CardDescription>
              Pares de salida/entrada entre cuentas propias. Confirmar no crea ni borra
              movimientos: solo los enlaza y los excluye de los KPIs.
            </CardDescription>
          </div>
          <Badge variant={pendingSuggestions.length > 0 ? "warning" : "positive"}>
            {pendingSuggestions.length} pendientes
          </Badge>
        </CardHeader>
        {transfersQuery.isLoading ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
          </div>
        ) : suggestions.length === 0 ? (
          <EmptyState
            title="Sin sugerencias"
            description="No hay pares de transferencias internas pendientes."
            icon={<Link2 className="size-4" aria-hidden />}
          />
        ) : (
          <div className="divide-y divide-border">
            {suggestions.map((suggestion) => (
              <TransferRow
                key={suggestion.id}
                suggestion={suggestion}
                status={transferStatus[suggestion.id] ?? "pendiente"}
                onResolve={(resolution) => void resolveTransfer(suggestion, resolution)}
              />
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="py-3">
            <div>
              <CardTitle>Cómo se resuelven las transferencias</CardTitle>
              <CardDescription>IBAN y patrones, en este orden</CardDescription>
            </div>
            <Landmark className="size-4 text-muted-foreground" aria-hidden />
          </CardHeader>
          <CardContent className="space-y-2.5 pt-0 text-[11px] leading-5 text-muted-foreground">
            {[
              "Al importar eliges la cuenta a la que pertenece el extracto.",
              "Se extrae el IBAN de la descripción original antes de redactarla.",
              "Si coincide con otra cuenta propia, el movimiento se marca como interno.",
              "Los pares internos se excluyen de ingresos, gastos y tasa de ahorro.",
            ].map((item, index) => (
              <p key={item} className="flex gap-2">
                <span className="num mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full bg-muted text-[9px] font-medium text-muted-foreground">
                  {index + 1}
                </span>
                {item}
              </p>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="py-3">
            <div>
              <CardTitle>Conciliación de saldos</CardTitle>
              <CardDescription>Saldo declarado frente a calculado</CardDescription>
            </div>
            <CreditCard className="size-4 text-muted-foreground" aria-hidden />
          </CardHeader>
          <CardContent className="pt-0">
            <div className="divide-y divide-border">
              {visibleAccounts.map((account) => {
                const difference = account.reconciliacion_diferencia;
                const ok = difference !== null && Math.abs(toNumber(difference)) < 0.005;
                return (
                  <div key={account.id} className="flex items-center gap-2 py-2 text-[11px]">
                    <CircleDollarSign
                      className={cn(
                        "size-3.5 shrink-0",
                        ok ? "text-positive" : difference === null ? "text-muted-foreground" : "text-warning",
                      )}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1 truncate">{account.nombre}</span>
                    <span className="num text-[10px] text-muted-foreground">
                      {difference === null
                        ? "sin snapshot"
                        : formatMoney(difference, { signDisplay: "always" })}
                    </span>
                  </div>
                );
              })}
            </div>
            <p className="mt-2 border-t border-border pt-2 text-[10px] leading-4 text-muted-foreground">
              La conciliación completa (saldo declarado vs. calculado) se guardará en{" "}
              <span className="num">account_balance_snapshots</span>. Esta pantalla usa el
              último snapshot disponible.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
