"use client";

import { useState, type ReactNode } from "react";
import {
  AlertCircle,
  BookOpen,
  Brain,
  Check,
  ChevronDown,
  Copy,
  FilePen,
  ChartLine,
  Loader2,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import type { AgentApproval, ApprovalDecision, ChatMessage, MessagePart } from "@/lib/agent-types";
import { cn, formatDateTime } from "@/lib/utils";
import { ApprovalCard } from "@/components/assistant/approval-card";
import { ChartWidget, isChartSpec } from "@/components/assistant/chart-widget";
import { isRecommendationSpec, RecommendationsWidget } from "@/components/assistant/recommendations-widget";
import { Markdown } from "@/components/ui/markdown";
import { TextShimmer } from "@/components/ui/text-shimmer";

/** Nombre visible de cada herramienta: [en curso, terminado]. */
export const TOOL_LABELS: Record<string, [string, string]> = {
  get_overview: ["Calculando tus KPIs…", "Resumen de KPIs"],
  search_movements: ["Buscando movimientos…", "Búsqueda de movimientos"],
  get_movement: ["Leyendo el movimiento…", "Detalle de movimiento"],
  spending_by_category: ["Agrupando el gasto por categoría…", "Gasto por categoría"],
  cashflow: ["Calculando el flujo de caja…", "Flujo de caja"],
  top_merchants: ["Buscando tus comercios principales…", "Comercios principales"],
  list_accounts: ["Consultando tus cuentas…", "Cuentas"],
  get_portfolio: ["Consultando tu cartera…", "Cartera"],
  list_categories: ["Leyendo las categorías…", "Categorías"],
  list_rules: ["Leyendo las reglas…", "Reglas"],
  pending_review: ["Revisando pendientes…", "Movimientos pendientes"],
  recategorize_movements: ["Preparando cambios de categoría…", "Cambiar categorías"],
  update_movement_fields: ["Preparando la edición…", "Editar movimiento"],
  create_rule: ["Preparando la regla…", "Crear regla"],
  create_category: ["Preparando la categoría…", "Crear categoría"],
  show_chart: ["Dibujando el gráfico…", "Gráfico"],
  activate_skill: ["Activando la skill…", "Skill activada"],
  read_skill_file: ["Leyendo recursos de la skill…", "Recurso de la skill"],
  read_draft: ["Leyendo el borrador…", "Leer borrador"],
  read_draft_file: ["Leyendo un archivo…", "Leer archivo"],
  write_draft_file: ["Escribiendo archivos…", "Escribir archivo"],
  delete_draft_file: ["Actualizando archivos…", "Borrar archivo"],
  validate_draft: ["Validando la skill…", "Validar skill"],
  list_duplicates: ["Buscando posibles duplicados…", "Posibles duplicados"],
  list_imports: ["Revisando las importaciones…", "Importaciones"],
  list_assets: ["Leyendo tus activos…", "Activos"],
  list_automations: ["Leyendo las automatizaciones…", "Automatizaciones"],
  list_skills: ["Leyendo tus skills…", "Skills"],
  create_account: ["Preparando la cuenta…", "Crear cuenta"],
  update_account: ["Preparando la edición de la cuenta…", "Editar cuenta"],
  resolve_duplicate: ["Preparando la resolución…", "Resolver duplicado"],
  link_transfer: ["Preparando el enlace…", "Enlazar transferencia"],
  update_asset: ["Preparando la edición del activo…", "Editar activo"],
  create_automation: ["Preparando la automatización…", "Crear automatización"],
  update_automation: ["Preparando la automatización…", "Editar automatización"],
  set_skill_enabled: ["Preparando el cambio…", "Activar skill"],
  search_asset: ["Buscando el activo…", "Búsqueda de activo"],
  get_quote: ["Consultando la cotización…", "Cotización"],
  price_history: ["Analizando la evolución del precio…", "Evolución del precio"],
  asset_fundamentals: ["Leyendo los fundamentales…", "Fundamentales"],
  asset_news: ["Leyendo noticias del activo…", "Noticias del activo"],
  market_news: ["Leyendo noticias de mercado…", "Noticias de mercado"],
  portfolio_live: ["Valorando tu cartera a mercado…", "Cartera a mercado"],
  recommendation_history: ["Revisando recomendaciones anteriores…", "Recomendaciones anteriores"],
  show_recommendations: ["Preparando las recomendaciones…", "Recomendaciones"],
  remember: ["Guardando en la memoria…", "Recordado"],
  forget_memory: ["Olvidando…", "Olvidado"],
  search_memory: ["Buscando en la memoria…", "Memoria"],
};

const WRITE_TOOLS = new Set([
  "recategorize_movements",
  "update_movement_fields",
  "create_rule",
  "create_category",
  "create_account",
  "update_account",
  "resolve_duplicate",
  "link_transfer",
  "update_asset",
  "create_automation",
  "update_automation",
  "set_skill_enabled",
]);
const MEMORY_TOOLS = new Set(["remember", "forget_memory", "search_memory"]);
const MARKET_TOOLS = new Set([
  "search_asset",
  "get_quote",
  "price_history",
  "asset_fundamentals",
  "asset_news",
  "market_news",
  "portfolio_live",
  "recommendation_history",
]);
const DRAFT_TOOLS = new Set(["read_draft", "read_draft_file", "write_draft_file", "delete_draft_file", "validate_draft"]);
/** Partes que no son pasos: se pintan en línea (gráficos) o como cabecera. */
const NOT_STEPS = new Set(["show_chart", "activate_skill", "show_recommendations"]);

type ToolPart = Extract<MessagePart, { type: "tool" }>;

function failed(part: ToolPart): boolean {
  const result = part.result;
  if (result && typeof result === "object" && "error" in (result as object)) return true;
  return Boolean(result && typeof result === "object" && (result as { ok?: boolean }).ok === false);
}

function stepLabel(part: ToolPart, running: boolean): string {
  const labels = TOOL_LABELS[part.name];
  if (!labels) return part.name;
  if (part.name.endsWith("draft_file") && typeof part.args.path === "string") {
    return `${running ? labels[0].replace("…", "") : labels[1]} · ${part.args.path}`;
  }
  if (part.name === "remember" && typeof part.args.key === "string") {
    return `${running ? "Guardando" : "Recordado"} · ${part.args.key}`;
  }
  if (typeof part.args.ticker === "string" && part.args.ticker) {
    return `${running ? labels[0].replace("…", "") : labels[1]} · ${part.args.ticker.toUpperCase()}`;
  }
  if (part.name === "search_movements" && typeof part.args.text === "string" && part.args.text) {
    return `${running ? "Buscando" : "Búsqueda"} «${part.args.text}»`;
  }
  return running ? labels[0] : labels[1];
}

function stepIcon(name: string): ReactNode {
  if (WRITE_TOOLS.has(name)) return <ShieldCheck className="size-3.5 shrink-0" aria-hidden />;
  if (DRAFT_TOOLS.has(name)) return <FilePen className="size-3.5 shrink-0" aria-hidden />;
  if (name === "read_skill_file") return <BookOpen className="size-3.5 shrink-0" aria-hidden />;
  if (MEMORY_TOOLS.has(name)) return <Brain className="size-3.5 shrink-0" aria-hidden />;
  if (MARKET_TOOLS.has(name)) return <ChartLine className="size-3.5 shrink-0" aria-hidden />;
  return <Wrench className="size-3.5 shrink-0" aria-hidden />;
}

function StepRow({ part, running }: { part: ToolPart; running: boolean }) {
  const [open, setOpen] = useState(false);
  const error = !running && failed(part);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className={cn(
          "flex max-w-full items-center gap-2 text-left text-[13px] transition-colors hover:text-foreground",
          error ? "text-negative" : "text-muted-foreground",
        )}
      >
        {stepIcon(part.name)}
        <span className="truncate">{stepLabel(part, running)}</span>
        {running ? (
          <Loader2 className="size-3 shrink-0 animate-spin" aria-hidden />
        ) : error ? (
          <AlertCircle className="size-3 shrink-0" aria-hidden />
        ) : (
          <Check className="size-3 shrink-0" aria-hidden />
        )}
      </button>
      {open ? (
        <pre className="num scrollbar-thin mt-1.5 max-h-60 overflow-auto rounded-lg border border-border bg-card p-2 text-[11px] leading-4 text-muted-foreground">
          {JSON.stringify({ args: part.args, result: part.result }, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

/**
 * Cabecera de la respuesta (como Nexus): en directo muestra qué hace el
 * asistente con brillo animado; al terminar, «Finalizado · N pasos» plegable.
 */
function RunSteps({
  parts,
  running,
  runningCalls,
  awaiting,
}: {
  parts: MessagePart[];
  running: boolean;
  runningCalls?: Set<string>;
  awaiting: boolean;
}) {
  const [toggled, setToggled] = useState<boolean | null>(null);
  const steps = parts.filter((part): part is ToolPart => part.type === "tool" && !NOT_STEPS.has(part.name));
  const skills = parts.filter((part): part is Extract<MessagePart, { type: "skill" }> => part.type === "skill");
  const hasText = parts.some((part) => part.type === "text" && part.text.trim());
  if (!running && !steps.length && !skills.length) return null;

  const open = toggled ?? (running && !hasText);
  const current = running ? [...steps].reverse().find((step) => runningCalls?.has(step.call_id)) : undefined;
  let label: ReactNode;
  if (running) {
    const text = current
      ? stepLabel(current, true)
      : hasText
        ? "Redactando la respuesta…"
        : steps.length
          ? "Analizando los resultados…"
          : "Pensando…";
    label = <TextShimmer className="text-[13px]">{text}</TextShimmer>;
  } else {
    label = awaiting ? "Esperando tu aprobación" : "Finalizado";
  }

  return (
    <div className="mb-3">
      <div className="flex min-h-7 flex-wrap items-center gap-x-3 gap-y-1.5">
        <button
          type="button"
          disabled={!steps.length}
          aria-expanded={steps.length ? open : undefined}
          onClick={() => setToggled(!open)}
          className="inline-flex min-w-0 items-center gap-1.5 text-[13px] text-muted-foreground transition-colors enabled:hover:text-foreground"
        >
          <span className="truncate">{label}</span>
          {steps.length && !running ? (
            <span className="shrink-0">
              · {steps.length} {steps.length === 1 ? "paso" : "pasos"}
            </span>
          ) : null}
          {steps.length ? (
            <ChevronDown className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-180")} aria-hidden />
          ) : null}
        </button>
        {skills.map((skill) => (
          <span
            key={skill.name}
            className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-0.5 text-[12px] text-accent-soft-foreground"
          >
            <Sparkles className="size-3" aria-hidden />
            {skill.name}
          </span>
        ))}
      </div>
      {open && steps.length ? (
        <div className="animate-fade-in ml-[7px] mt-3 flex flex-col gap-2.5 border-l border-border pb-1 pl-4">
          {steps.map((step) => (
            <StepRow key={step.call_id} part={step} running={Boolean(runningCalls?.has(step.call_id))} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label="Copiar"
      title="Copiar"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        });
      }}
      className={cn(
        "inline-flex size-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-surface-2 hover:text-foreground",
        className,
      )}
    >
      {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
    </button>
  );
}

function plainText(parts: MessagePart[]): string {
  return parts
    .filter((part): part is Extract<MessagePart, { type: "text" }> => part.type === "text")
    .map((part) => part.text)
    .join("\n\n")
    .trim();
}

export function MessageView({
  message,
  streaming,
  runningCalls,
  busy,
  last,
  compact,
  onDecide,
}: {
  message: ChatMessage;
  streaming?: boolean;
  runningCalls?: Set<string>;
  busy?: boolean;
  /** Último mensaje del hilo: muestra la barra de acciones. */
  last?: boolean;
  /** Prosa sans-serif más pequeña (paneles secundarios). */
  compact?: boolean;
  onDecide?: (decision: ApprovalDecision) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="group animate-fade-in flex items-start justify-end gap-1 pt-8 first:pt-0">
        <div className="flex items-center gap-0.5 self-center opacity-0 transition-opacity group-hover:opacity-100 [@media(hover:none)]:opacity-100">
          {message.created_at ? (
            <span className="tabular px-1 text-[12px] text-muted-foreground">{formatDateTime(message.created_at)}</span>
          ) : null}
          <CopyButton text={message.content ?? ""} />
        </div>
        <div
          className={cn(
            "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-surface-2 px-4 py-3 sm:max-w-[75%]",
            compact ? "text-[14px] leading-6" : "text-[15px] leading-6",
          )}
        >
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
  const awaiting = parts.some(
    (part) => part.type === "approvals" && part.items.some((item) => item.status === "pending"),
  );
  const text = plainText(parts);

  return (
    <div className="animate-fade-in pt-6">
      <RunSteps parts={parts} running={Boolean(streaming)} runningCalls={runningCalls} awaiting={awaiting} />
      <div className="space-y-4">
        {parts.map((part, index) => {
          if (part.type === "text") {
            return part.text.trim() ? (
              <Markdown key={index} compact={compact}>
                {part.text}
              </Markdown>
            ) : null;
          }
          if (part.type === "approvals") {
            return (
              <div key={index} className="space-y-2">
                {part.items.map((approval: AgentApproval) => (
                  <ApprovalCard
                    key={approval.id}
                    approval={approval}
                    disabled={busy || !onDecide}
                    onDecide={(decision) => onDecide?.(decision)}
                  />
                ))}
              </div>
            );
          }
          if (part.type === "tool" && part.name === "show_chart" && isChartSpec(part.args)) {
            return <ChartWidget key={index} spec={part.args} />;
          }
          if (part.type === "tool" && part.name === "show_recommendations" && isRecommendationSpec(part.args)) {
            return <RecommendationsWidget key={index} spec={part.args} result={part.result} />;
          }
          return null;
        })}
      </div>
      {last && !streaming && text ? (
        <div className="-ml-2 mt-2 flex items-center gap-0.5">
          <CopyButton text={text} />
        </div>
      ) : null}
    </div>
  );
}
