import { AlertTriangle, CheckCircle2, Clock3, Loader2, XCircle } from "lucide-react";
import type { ImportStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export const importStatusConfig: Record<
  ImportStatus,
  {
    label: string;
    variant: "positive" | "warning" | "negative" | "accent" | "neutral";
    icon: typeof CheckCircle2;
  }
> = {
  parsed: { label: "Procesada", variant: "positive", icon: CheckCircle2 },
  parsed_with_overlap: {
    label: "Procesada con solape",
    variant: "positive",
    icon: CheckCircle2,
  },
  needs_review: { label: "Revisar", variant: "warning", icon: AlertTriangle },
  failed: { label: "Error", variant: "negative", icon: XCircle },
  queued: { label: "En cola", variant: "neutral", icon: Clock3 },
  processing: { label: "Procesando", variant: "accent", icon: Loader2 },
  parsing: { label: "Procesando", variant: "accent", icon: Loader2 },
  uploaded: { label: "Pendiente", variant: "neutral", icon: Clock3 },
};

export function ImportStatusBadge({
  status,
  className,
}: {
  status: ImportStatus;
  className?: string;
}) {
  const config = importStatusConfig[status] ?? importStatusConfig.uploaded;
  const Icon = config.icon;
  return (
    <Badge variant={config.variant} className={className}>
      <Icon
        className={cn("size-2.5", status === "parsing" && "animate-spin")}
        aria-hidden
      />
      {config.label}
    </Badge>
  );
}

export const importSourceLabels: Record<string, string> = {
  agentic_statement: "Extracto agéntico",
  trade_republic_csv: "Trade Republic · CSV",
  trade_republic_pdf: "Trade Republic · PDF",
  revolut_pdf: "Revolut · PDF",
  revolut_csv: "Revolut · CSV",
  image_receipt: "Imagen / recibo",
  generic_csv: "CSV genérico",
};
