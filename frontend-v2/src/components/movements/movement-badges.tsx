import type {
  Classification,
  MovementKind,
  MovementState,
} from "@/lib/types";
import {
  BookMarked,
  BrainCircuit,
  Building2,
  ListChecks,
  Sparkles,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  confidenceVariant,
  kindLabels,
  originLabels,
  originVariant,
  stateLabels,
} from "@/components/movements/constants";

export function StateBadge({ state }: { state: MovementState }) {
  const variant =
    state === "aprobado"
      ? "positive"
      : state === "rechazado" || state === "duplicado"
        ? "neutral"
        : "warning";
  return (
    <Badge variant={variant} dot>
      {stateLabels[state]}
    </Badge>
  );
}

export function KindBadge({ kind, className }: { kind: MovementKind; className?: string }) {
  return (
    <Badge variant={kind === "transferencia_interna" ? "info" : "outline"} className={className}>
      {kindLabels[kind]}
    </Badge>
  );
}

export function ConfidenceBadge({
  classification,
  showOrigin = false,
  className,
}: {
  classification: Classification | null;
  showOrigin?: boolean;
  className?: string;
}) {
  if (!classification) {
    return <span className="text-[11px] text-muted-foreground">—</span>;
  }
  const confidence = classification.confianza;
  if (confidence === null || confidence === undefined) {
    return (
      <span className={cn("inline-flex items-center gap-1.5", className)}>
        <Badge variant="neutral">—</Badge>
        {showOrigin ? (
          <Badge variant={originVariant(classification.origen)}>
            {originLabels[classification.origen]}
          </Badge>
        ) : null}
      </span>
    );
  }
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <Badge variant={confidenceVariant(confidence)} dot>
        {Math.round(confidence * 100)}%
      </Badge>
      {showOrigin ? (
        <Badge variant={originVariant(classification.origen)}>
          {originLabels[classification.origen]}
        </Badge>
      ) : null}
    </span>
  );
}

const originIcons: Partial<Record<Classification["origen"], LucideIcon>> = {
  broker: Building2,
  rule: ListChecks,
  memory: BookMarked,
  embedding: Sparkles,
  decider: BrainCircuit,
  llm: Sparkles,
  user: UserRound,
};

const confidenceBar: Record<ReturnType<typeof confidenceVariant>, string> = {
  positive: "bg-positive",
  warning: "bg-warning",
  negative: "bg-negative",
  neutral: "bg-muted-foreground/30",
};

const confidenceText: Record<ReturnType<typeof confidenceVariant>, string> = {
  positive: "text-positive",
  warning: "text-warning",
  negative: "text-negative",
  neutral: "text-muted-foreground",
};

/** Barra de confianza compacta con el origen como icono. */
export function ConfidenceMeter({
  classification,
  className,
}: {
  classification: Classification | null;
  className?: string;
}) {
  if (!classification) {
    return <span className="text-[11px] text-muted-foreground/60">—</span>;
  }
  const confidence = classification.confianza;
  const variant = confidenceVariant(confidence);
  const Icon = originIcons[classification.origen] ?? Sparkles;
  const pct = confidence == null ? null : Math.round(confidence * 100);
  return (
    <span
      className={cn("inline-flex items-center gap-2", className)}
      title={`${originLabels[classification.origen] ?? classification.origen}${pct != null ? ` · ${pct}%` : ""}`}
    >
      <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <Icon className="size-3" aria-hidden />
      </span>
      {pct != null ? (
        <>
          <span className="h-1 w-12 overflow-hidden rounded-full bg-muted">
            <span
              className={cn("block h-full rounded-full", confidenceBar[variant])}
              style={{ width: `${pct}%` }}
            />
          </span>
          <span className={cn("num w-8 text-[11px] font-medium", confidenceText[variant])}>{pct}%</span>
        </>
      ) : (
        <span className="text-[11px] text-muted-foreground">
          {originLabels[classification.origen] ?? classification.origen}
        </span>
      )}
    </span>
  );
}

/** Indicador de estado como punto + etiqueta discreta. */
export function StateDot({ state }: { state: MovementState }) {
  const tone =
    state === "aprobado"
      ? "bg-positive"
      : state === "rechazado" || state === "duplicado"
        ? "bg-muted-foreground/50"
        : "bg-warning";
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground" title={stateLabels[state]}>
      <span className={cn("size-1.5 rounded-full", tone, state === "pendiente" && "ring-2 ring-warning/20")} aria-hidden />
      {stateLabels[state]}
    </span>
  );
}
