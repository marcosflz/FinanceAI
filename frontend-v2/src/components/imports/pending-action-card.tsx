"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, FileText, Landmark, Trash2 } from "lucide-react";
import { accountsApi, importsApi } from "@/lib/api";
import { DEMO_MODE, sleep, withMock } from "@/lib/demo";
import type { AccountType, ImportPendingAction, ImportSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { Field, Input, Select } from "@/components/ui/form";
import { Segmented } from "@/components/ui/segmented";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

/** Acciones que bloquean la importación hasta que el usuario las apruebe. */
export function isBlockingAction(
  action: ImportPendingAction | null | undefined,
): action is Exclude<ImportPendingAction, { type: "review_movements" }> {
  return Boolean(action && action.type !== "review_movements");
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function maskIban(iban?: string | null): string | null {
  if (!iban) return null;
  return `${iban.slice(0, 4)} ···· ${iban.slice(-4)}`;
}

/** Quita un fichero que aún no ha generado datos. */
export function useDiscardImport() {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const { toast } = useToast();
  return async function discard(item: Pick<ImportSummary, "id" | "filename">) {
    const ok = await confirm({
      title: "¿Descartar este archivo?",
      description: `Se eliminará «${item.filename}» de la lista sin importar ningún movimiento.`,
      confirmLabel: "Descartar",
      tone: "danger",
    });
    if (!ok) return false;
    try {
      if (DEMO_MODE) await sleep(300);
      else await importsApi.remove(item.id);
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
      toast({ title: "Archivo descartado", variant: "success" });
      return true;
    } catch (error) {
      toast({
        title: "No se pudo descartar",
        description: errorMessage(error, "Inténtalo de nuevo."),
        variant: "error",
      });
      return false;
    }
  };
}

type Mode = "create" | "assign";

/**
 * Tarjeta de aprobación de una acción propuesta por el agente de importación.
 * Mientras no se apruebe, el extracto no crea movimientos.
 */
export function PendingActionCard({
  item,
  showFile = true,
  className,
}: {
  item: ImportSummary;
  showFile?: boolean;
  className?: string;
}) {
  const action = item.pending_action;
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const discard = useDiscardImport();
  const [busy, setBusy] = useState(false);

  const proposal =
    action && (action.type === "create_account" || action.type === "confirm_account")
      ? action
      : null;
  const [mode, setMode] = useState<Mode>(
    proposal?.type === "confirm_account" && proposal.suggested_account_id ? "assign" : "create",
  );
  const [name, setName] = useState(proposal?.proposed_account.nombre ?? "");
  const [iban, setIban] = useState(proposal?.proposed_account.iban ?? "");
  const [type, setType] = useState<AccountType>(
    proposal?.proposed_account.tipo ?? "efectivo_externa",
  );
  const [balance, setBalance] = useState(
    proposal?.proposed_account.balance_inicial != null
      ? String(proposal.proposed_account.balance_inicial)
      : "",
  );
  const [balanceDate, setBalanceDate] = useState(
    proposal?.proposed_account.balance_inicial_fecha ?? "",
  );
  const [accountChoice, setAccountChoice] = useState(
    proposal?.suggested_account_id ? String(proposal.suggested_account_id) : "",
  );

  const accountsQuery = useQuery({
    queryKey: ["accounts", false],
    queryFn: () => withMock(() => accountsApi.list(false), { items: [] }),
    enabled: Boolean(proposal),
  });
  const accounts = accountsQuery.data?.items ?? [];

  if (!action || action.type === "review_movements") return null;

  async function approve() {
    if (!proposal || busy) return;
    if (mode === "create" && !name.trim()) {
      toast({ title: "Falta el nombre de la cuenta", variant: "error" });
      return;
    }
    if (mode === "assign" && !accountChoice) {
      toast({ title: "Selecciona una cuenta", variant: "error" });
      return;
    }
    setBusy(true);
    try {
      if (DEMO_MODE) {
        await sleep(400);
      } else if (mode === "create") {
        await importsApi.confirmAccount(item.id, {
          action: "create",
          account: {
            nombre: name.trim(),
            iban: iban.replace(/\s+/g, "") || null,
            tipo: type,
            broker: proposal.proposed_account.broker,
            es_propia: true,
            moneda: proposal.proposed_account.moneda || "EUR",
            color: "#00B4D8",
            activo: true,
            alias_patrones: [],
            balance_inicial: balance ? Number(balance.replace(",", ".")) : 0,
            balance_inicial_fecha: balanceDate || null,
          },
        });
      } else {
        await importsApi.confirmAccount(item.id, {
          action: "assign",
          account_id: Number(accountChoice),
        });
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["imports"] }),
        queryClient.invalidateQueries({ queryKey: ["accounts"] }),
      ]);
      toast({
        title: mode === "create" ? "Cuenta creada" : "Cuenta asignada",
        description: "El extracto continúa importándose con esa cuenta.",
        variant: "success",
      });
    } catch (error) {
      toast({
        title: "No se pudo aprobar",
        description: errorMessage(error, "Revisa los datos de la cuenta."),
        variant: "error",
      });
    } finally {
      setBusy(false);
    }
  }

  const title =
    action.type === "create_account"
      ? "Crear cuenta nueva"
      : action.type === "confirm_account"
        ? "Confirmar la cuenta del extracto"
        : "Fichero con varios productos";

  return (
    <div
      className={cn(
        "rounded-xl border border-warning/30 bg-card px-4 py-3",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-warning-soft text-warning">
          {action.type === "unsupported_product" ? (
            <AlertTriangle className="size-4" aria-hidden />
          ) : (
            <Landmark className="size-4" aria-hidden />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <p className="text-[13px] font-medium text-foreground">{title}</p>
            {showFile ? (
              <Link
                href={`/imports/${item.id}`}
                className="inline-flex min-w-0 items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
              >
                <FileText className="size-3 shrink-0" aria-hidden />
                <span className="truncate">{item.filename}</span>
                {item.row_count ? <span>· {item.row_count} filas</span> : null}
              </Link>
            ) : null}
          </div>
          {action.reason ? (
            <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">{action.reason}</p>
          ) : null}
        </div>
      </div>

      {action.type === "unsupported_product" ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 pl-11">
          <p className="text-[11px] leading-5 text-muted-foreground">
            Exporta la Cuenta Corriente y la Cuenta Conjunta en ficheros separados.
            Pockets/Depósito no se controlan como cuentas.
          </p>
          <Button variant="secondary" size="sm" onClick={() => void discard(item)}>
            <Trash2 className="size-3.5" aria-hidden />
            Descartar archivo
          </Button>
        </div>
      ) : proposal ? (
        <div className="mt-3 space-y-3 sm:pl-11">
          <Segmented
            aria-label="Cómo resolver la cuenta"
            value={mode}
            onChange={setMode}
            options={[
              { value: "create", label: "Crear cuenta nueva" },
              {
                value: "assign",
                label: "Usar una existente",
                disabled: !accountsQuery.isLoading && accounts.length === 0,
              },
            ]}
          />

          {mode === "create" ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <Field label="Nombre" className="lg:col-span-2">
                <Input value={name} onChange={(event) => setName(event.target.value)} />
              </Field>
              <Field label="IBAN" className="lg:col-span-2">
                <Input
                  value={iban}
                  onChange={(event) => setIban(event.target.value)}
                  placeholder="Sin IBAN"
                />
              </Field>
              <Field label="Tipo">
                <Select
                  value={type}
                  onChange={(event) => setType(event.target.value as AccountType)}
                >
                  <option value="efectivo_externa">Cuenta bancaria</option>
                  <option value="broker_central">Broker</option>
                </Select>
              </Field>
              <Field label="Saldo inicial" hint="Del propio extracto, si lo trae.">
                <Input
                  type="number"
                  step="0.01"
                  value={balance}
                  onChange={(event) => setBalance(event.target.value)}
                  placeholder="0.00"
                />
              </Field>
              <Field label="Fecha del saldo">
                <DatePicker
                  aria-label="Fecha del saldo inicial"
                  placeholder="Sin fecha"
                  value={balanceDate}
                  onChange={setBalanceDate}
                />
              </Field>
            </div>
          ) : (
            <Field label="Cuenta" className="max-w-md">
              <Select
                value={accountChoice}
                onChange={(event) => setAccountChoice(event.target.value)}
                disabled={accountsQuery.isLoading}
              >
                <option value="">Selecciona una cuenta…</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.nombre}
                    {account.iban ? ` · ${maskIban(account.iban)}` : ""}
                  </option>
                ))}
              </Select>
            </Field>
          )}

          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void discard(item)}
              disabled={busy}
            >
              <Trash2 className="size-3.5" aria-hidden />
              Descartar archivo
            </Button>
            <Button variant="primary" size="sm" onClick={() => void approve()} loading={busy}>
              <Check className="size-3.5" aria-hidden />
              {mode === "create" ? "Aprobar e importar" : "Asignar e importar"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
