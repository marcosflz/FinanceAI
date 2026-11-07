import type {
  ClassificationOrigin,
  MovementKind,
  MovementState,
} from "@/lib/types";

export const kindLabels: Record<MovementKind, string> = {
  gasto: "Gasto",
  ingreso: "Ingreso",
  transferencia_interna: "Interna",
  cambio_divisa: "Cambio divisa",
  inversion_compra: "Compra",
  inversion_venta: "Venta",
  dividendo: "Dividendo",
  interes: "Interés",
  cashback: "Cashback",
  fee: "Comisión",
  impuesto: "Impuesto",
  aporte_activo: "Aporte",
  ajuste: "Ajuste",
};

export const originLabels: Record<ClassificationOrigin, string> = {
  broker: "Broker",
  rule: "Regla",
  memory: "Memoria",
  embedding: "Embedding",
  decider: "Jev",
  llm: "LLM",
  user: "Usuario",
};

export const stateLabels: Record<MovementState, string> = {
  pendiente: "Pendiente",
  aprobado: "Aprobado",
  rechazado: "Rechazado",
  duplicado: "Duplicado",
};

export function confidenceVariant(
  confidence: number | null | undefined,
): "positive" | "warning" | "negative" | "neutral" {
  if (confidence === null || confidence === undefined) return "neutral";
  if (confidence >= 0.9) return "positive";
  if (confidence >= 0.75) return "warning";
  return "negative";
}

export function originVariant(
  origin: ClassificationOrigin | null | undefined,
): "accent" | "info" | "neutral" | "warning" | "positive" {
  switch (origin) {
    case "broker":
      return "accent";
    case "rule":
      return "info";
    case "memory":
      return "positive";
    case "decider":
    case "llm":
      return "warning";
    case "user":
      return "positive";
    default:
      return "neutral";
  }
}
