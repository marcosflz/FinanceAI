"use client";

import { useState } from "react";
import { Check, ShieldAlert, X } from "lucide-react";
import type { AgentApproval, ApprovalDecision } from "@/lib/agent-types";
import { formatDate, formatMoney } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/form";

const TOOL_LABELS: Record<string, string> = {
  recategorize_movements: "Cambiar categorías",
  update_movement_fields: "Editar movimiento",
  create_rule: "Crear regla de clasificación",
  create_category: "Crear categoría",
};

const ARG_LABELS: Record<string, string> = {
  movement_id: "Movimiento",
  merchant: "Comercio",
  note: "Nota",
  estado: "Estado",
  field: "Campo",
  operator: "Operador",
  value: "Valor",
  category: "Categoría",
  priority: "Prioridad",
  auto_approve: "Auto-aprobar",
  name: "Nombre",
  parent: "Dentro de",
};

/**
 * Tarjeta de confirmación de una acción del asistente. Para lotes de
 * recategorización permite aceptar fila a fila.
 */
export function ApprovalCard({
  approval,
  disabled,
  onDecide,
}: {
  approval: AgentApproval;
  disabled?: boolean;
  onDecide: (decision: ApprovalDecision) => void;
}) {
  const rows = approval.preview?.kind === "recategorize" ? approval.preview.rows ?? [] : [];
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(rows.filter((row) => row.valid).map((row) => row.id)),
  );
  const decided = approval.status !== "pending";

  function toggle(id: number) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function approve() {
    if (rows.length) {
      const all = rows.filter((row) => row.valid).every((row) => selected.has(row.id));
      onDecide({
        call_id: approval.call_id,
        approved: true,
        selected_ids: all ? undefined : [...selected],
      });
      return;
    }
    onDecide({ call_id: approval.call_id, approved: true });
  }

  return (
    <div className="rounded-xl border border-warning/30 bg-warning-soft/50 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[12px] font-medium text-foreground">
          <ShieldAlert className="size-3.5 text-warning" aria-hidden />
          {TOOL_LABELS[approval.tool] ?? approval.tool}
        </p>
        {decided ? (
          <Badge
            variant={
              approval.status === "approved"
                ? "positive"
                : approval.status === "denied"
                  ? "negative"
                  : "neutral"
            }
          >
            {approval.status === "approved"
              ? "Aprobado"
              : approval.status === "denied"
                ? "Denegado"
                : "Resuelta"}
          </Badge>
        ) : (
          <Badge variant="warning">Necesita tu confirmación</Badge>
        )}
      </div>

      {rows.length ? (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-[11px]">
            <thead className="bg-subtle text-left text-muted-foreground">
              <tr>
                <th className="w-8 px-2 py-1.5" aria-label="Aceptar" />
                <th className="px-2 py-1.5 font-medium">Fecha</th>
                <th className="px-2 py-1.5 font-medium">Movimiento</th>
                <th className="px-2 py-1.5 text-right font-medium">Importe</th>
                <th className="px-2 py-1.5 font-medium">Ahora</th>
                <th className="px-2 py-1.5 font-medium">Propuesta</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row) => (
                <tr key={row.id} className={row.valid ? "" : "opacity-60"}>
                  <td className="px-2 py-1.5">
                    <Checkbox
                      aria-label={`Aceptar cambio del movimiento ${row.id}`}
                      checked={selected.has(row.id)}
                      disabled={!row.valid || decided || disabled}
                      onChange={() => toggle(row.id)}
                    />
                  </td>
                  <td className="num whitespace-nowrap px-2 py-1.5">
                    {row.date ? formatDate(row.date, "day") : "—"}
                  </td>
                  <td className="max-w-[180px] truncate px-2 py-1.5">{row.merchant ?? `#${row.id}`}</td>
                  <td className="num whitespace-nowrap px-2 py-1.5 text-right">
                    {row.amount != null ? formatMoney(row.amount) : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-muted-foreground">{row.category ?? "Sin categoría"}</td>
                  <td className="px-2 py-1.5 font-medium">
                    {row.new_category ?? <span className="text-negative">No existe</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <dl className="grid gap-x-3 gap-y-1 rounded-lg border border-border bg-card p-2.5 text-[11px] sm:grid-cols-[auto_1fr]">
          {Object.entries(approval.args).map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-muted-foreground">{ARG_LABELS[key] ?? key}</dt>
              <dd className="num break-all">{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {!decided ? (
        <div className="mt-2.5 flex justify-end gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => onDecide({ call_id: approval.call_id, approved: false })}
          >
            <X className="size-3.5" aria-hidden />
            Denegar
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={disabled || (rows.length > 0 && selected.size === 0)}
            onClick={approve}
          >
            <Check className="size-3.5" aria-hidden />
            {rows.length
              ? `Aplicar ${selected.size} de ${rows.length}`
              : "Aprobar"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
