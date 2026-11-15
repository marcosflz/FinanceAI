"use client";

import { Fragment, useState, type ReactNode } from "react";
import { ChevronRight, Loader2, Sparkles, Wrench } from "lucide-react";
import type { AgentApproval, ApprovalDecision, ChatMessage, MessagePart } from "@/lib/agent-types";
import { cn } from "@/lib/utils";
import { ApprovalCard } from "@/components/assistant/approval-card";
import { ChartWidget, isChartSpec } from "@/components/assistant/chart-widget";

const TOOL_NAMES: Record<string, string> = {
  get_overview: "Resumen de KPIs",
  search_movements: "Buscar movimientos",
  get_movement: "Detalle de movimiento",
  spending_by_category: "Gasto por categoría",
  cashflow: "Flujo de caja",
  top_merchants: "Comercios principales",
  list_accounts: "Cuentas",
  get_portfolio: "Cartera",
  list_categories: "Categorías",
  list_rules: "Reglas",
  pending_review: "Pendientes",
  recategorize_movements: "Cambiar categorías",
  update_movement_fields: "Editar movimiento",
  create_rule: "Crear regla",
  create_category: "Crear categoría",
  show_chart: "Gráfico",
};

/** Negrita ``**x**`` y saltos de línea: suficiente para respuestas cortas. */
function RichText({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="space-y-2">
      {blocks.map((block, index) => {
        const lines = block.split("\n");
        const isList = lines.every((line) => /^\s*([-*•]|\d+\.)\s+/.test(line));
        const render = (line: string): ReactNode[] =>
          line.split(/(\*\*[^*]+\*\*)/g).map((chunk, i) =>
            chunk.startsWith("**") && chunk.endsWith("**") ? (
              <strong key={i} className="font-semibold">
                {chunk.slice(2, -2)}
              </strong>
            ) : (
              <Fragment key={i}>{chunk}</Fragment>
            ),
          );
        if (isList) {
          return (
            <ul key={index} className="list-disc space-y-0.5 pl-5">
              {lines.map((line, i) => (
                <li key={i}>{render(line.replace(/^\s*([-*•]|\d+\.)\s+/, ""))}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={index} className="whitespace-pre-wrap">
            {lines.map((line, i) => (
              <Fragment key={i}>
                {i > 0 ? <br /> : null}
                {render(line)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}

function ToolChip({ part, running }: { part: Extract<MessagePart, { type: "tool" }>; running?: boolean }) {
  const [open, setOpen] = useState(false);
  const failed = Boolean(part.result && typeof part.result === "object" && "error" in (part.result as object));
  return (
    <div className="text-[11px]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 transition-colors hover:bg-muted",
          failed ? "border-negative/30 text-negative" : "border-border text-muted-foreground",
        )}
        aria-expanded={open}
      >
        {running ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Wrench className="size-3" aria-hidden />}
        {TOOL_NAMES[part.name] ?? part.name}
        <ChevronRight className={cn("size-3 transition-transform", open ? "rotate-90" : "")} aria-hidden />
      </button>
      {open ? (
        <pre className="num mt-1 max-h-60 overflow-auto rounded-lg border border-border bg-subtle p-2 text-[10px] leading-4">
          {JSON.stringify({ args: part.args, result: part.result }, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

export function MessageView({
  message,
  streaming,
  runningCalls,
  busy,
  onDecide,
}: {
  message: ChatMessage;
  streaming?: boolean;
  runningCalls?: Set<string>;
  busy?: boolean;
  onDecide: (decision: ApprovalDecision) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-[13px] leading-5 text-accent-foreground">
          {message.content}
        </div>
      </div>
    );
  }

  const parts = message.parts.length
    ? message.parts
    : message.content
      ? [{ type: "text", text: message.content } as MessagePart]
      : [];

  return (
    <div className="flex gap-2.5">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
        <Sparkles className="size-3.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 space-y-2 text-[13px] leading-5">
        {parts.map((part, index) => {
          if (part.type === "text") return <RichText key={index} text={part.text} />;
          if (part.type === "approvals") {
            return (
              <div key={index} className="space-y-2">
                {part.items.map((approval: AgentApproval) => (
                  <ApprovalCard key={approval.id} approval={approval} disabled={busy} onDecide={onDecide} />
                ))}
              </div>
            );
          }
          if (part.name === "show_chart" && isChartSpec(part.args)) {
            return <ChartWidget key={index} spec={part.args} />;
          }
          return <ToolChip key={index} part={part} running={runningCalls?.has(part.call_id)} />;
        })}
        {streaming && !parts.length ? (
          <p className="flex items-center gap-1.5 text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            Pensando…
          </p>
        ) : null}
      </div>
    </div>
  );
}
