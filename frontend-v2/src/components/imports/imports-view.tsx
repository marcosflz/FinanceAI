"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileSpreadsheet,
  FileText,
  Hourglass,
  Image as ImageIcon,
  Loader2,
  RotateCcw,
  Trash2,
  UploadCloud,
  XCircle,
} from "lucide-react";
import { importsApi } from "@/lib/api";
import { DEMO_MODE, sleep, withMock } from "@/lib/demo";
import { mockImports } from "@/lib/mock";
import type { ImportSummary } from "@/lib/types";
import { formatDate, formatDateTime, cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/page-header";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { Dropzone } from "@/components/imports/dropzone";
import {
  PendingActionCard,
  isBlockingAction,
  useDiscardImport,
} from "@/components/imports/pending-action-card";

type FileState = "uploading" | "queued" | "processing" | "approval" | "done" | "review" | "failed";

type Filter = "all" | "active" | "approval" | "done" | "failed";

const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: "all", label: "Todos" },
  { value: "active", label: "En curso" },
  { value: "approval", label: "Por aprobar" },
  { value: "done", label: "Importados" },
  { value: "failed", label: "Errores" },
];

const STATE_META: Record<
  FileState,
  {
    label: string;
    variant: "positive" | "warning" | "negative" | "accent" | "neutral";
    icon: typeof CheckCircle2;
    spin?: boolean;
  }
> = {
  uploading: { label: "Subiendo", variant: "accent", icon: Loader2, spin: true },
  queued: { label: "En cola", variant: "neutral", icon: Clock3 },
  processing: { label: "Procesando", variant: "accent", icon: Loader2, spin: true },
  approval: { label: "Esperando aprobación", variant: "warning", icon: Hourglass },
  done: { label: "Importado", variant: "positive", icon: CheckCircle2 },
  review: { label: "Importado · revisar", variant: "warning", icon: AlertTriangle },
  failed: { label: "Error", variant: "negative", icon: XCircle },
};

function fileState(item: ImportSummary): FileState {
  switch (item.status) {
    case "queued":
    case "uploaded":
      return "queued";
    case "processing":
    case "parsing":
      return "processing";
    case "failed":
      return "failed";
    case "needs_review":
      return isBlockingAction(item.pending_action) ? "approval" : "review";
    default:
      return "done";
  }
}

function matchesFilter(state: FileState, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "active") return state === "queued" || state === "processing" || state === "uploading";
  if (filter === "approval") return state === "approval";
  if (filter === "done") return state === "done" || state === "review";
  return state === "failed";
}

/** El backend serializa ``datetime.utcnow()`` sin zona: es UTC. */
function parseUtc(value?: string | null): number | null {
  if (!value) return null;
  const hasZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value);
  const time = Date.parse(hasZone ? value : `${value}Z`);
  return Number.isNaN(time) ? null : time;
}

function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatBytes(bytes?: number | null): string | null {
  if (bytes == null) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileTypeIcon({ name, mime, className }: { name: string; mime?: string; className?: string }) {
  const lower = name.toLowerCase();
  const Icon =
    mime?.startsWith("image/") || /\.(png|jpe?g|webp|heic)$/.test(lower)
      ? ImageIcon
      : /\.(csv|tsv|xlsx?|ofx|qif)$/.test(lower) || mime?.includes("csv") || mime?.includes("sheet")
        ? FileSpreadsheet
        : FileText;
  return <Icon className={className} aria-hidden />;
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [active]);
  return now;
}

function StateBadge({ state }: { state: FileState }) {
  const meta = STATE_META[state];
  const Icon = meta.icon;
  return (
    <Badge variant={meta.variant} className="whitespace-nowrap">
      <Icon className={cn("size-2.5", meta.spin && "animate-spin")} aria-hidden />
      {meta.label}
    </Badge>
  );
}

function statusDetail(item: ImportSummary, state: FileState, now: number): string | null {
  if (state === "queued") {
    return item.queue_position ? `Posición ${item.queue_position} en la cola` : "Esperando al worker";
  }
  if (state === "processing") {
    const started = parseUtc(item.started_at);
    return started ? `Extrayendo · ${formatElapsed(now - started)}` : "Extrayendo";
  }
  if (state === "approval") return "Revisa la acción propuesta arriba";
  if (state === "failed") return item.error;
  if (state === "done" || state === "review") {
    const parts = [`+${item.movement_new_count} movimientos`];
    if (item.movement_seen_count > 0) parts.push(`${item.movement_seen_count} ya vistos`);
    if (state === "review" && item.error) parts.push(item.error);
    return parts.join(" · ");
  }
  return null;
}

function FileRow({
  item,
  now,
  onRetry,
  retrying,
}: {
  item: ImportSummary;
  now: number;
  onRetry: (item: ImportSummary) => void;
  retrying: boolean;
}) {
  const discard = useDiscardImport();
  const state = fileState(item);
  const detail = statusDetail(item, state, now);
  const hasData = item.movement_new_count > 0 || item.movement_seen_count > 0;
  const canDiscard = state !== "processing" && !hasData && state !== "done";
  const meta = [
    formatBytes(item.size_bytes),
    item.period_start && item.period_end
      ? `${formatDate(item.period_start, "short")} – ${formatDate(item.period_end, "short")}`
      : null,
    `Subido ${formatDateTime(item.created_at)}`,
  ].filter(Boolean);

  return (
    <li className="group flex flex-col gap-2 px-4 py-3 transition-colors hover:bg-muted/40 sm:flex-row sm:items-center sm:gap-3">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
          <FileTypeIcon name={item.filename} mime={item.mime_type} className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <Link
            href={`/imports/${item.id}`}
            className="block truncate text-[12px] font-medium text-foreground hover:text-accent"
          >
            {item.filename}
          </Link>
          <p className="truncate text-[10px] text-muted-foreground">{meta.join(" · ")}</p>
        </div>
      </div>

      <div className="min-w-0 sm:w-44">
        <p className="truncate text-[11px] text-foreground">
          {item.account?.nombre ?? <span className="text-muted-foreground">Sin cuenta</span>}
        </p>
      </div>

      <div className="min-w-0 sm:w-64">
        <StateBadge state={state} />
        {detail ? (
          <p
            className={cn(
              "mt-1 truncate text-[10px]",
              state === "failed" ? "text-negative" : "text-muted-foreground",
            )}
            title={detail}
          >
            {detail}
          </p>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center justify-end gap-1 sm:w-24">
        {state === "failed" ? (
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Reintentar ${item.filename}`}
            title="Reintentar"
            onClick={() => onRetry(item)}
            loading={retrying}
          >
            <RotateCcw className="size-3.5" aria-hidden />
          </Button>
        ) : null}
        {canDiscard ? (
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Descartar ${item.filename}`}
            title="Descartar"
            onClick={() => void discard(item)}
          >
            <Trash2 className="size-3.5" aria-hidden />
          </Button>
        ) : null}
        <Link
          href={`/imports/${item.id}`}
          aria-label={`Abrir ${item.filename}`}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <ChevronRight className="size-3.5" aria-hidden />
        </Link>
      </div>
    </li>
  );
}

export function ImportsView() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [uploading, setUploading] = useState<File[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [retryingId, setRetryingId] = useState<number | null>(null);

  const importsQuery = useQuery({
    queryKey: ["imports"],
    queryFn: () =>
      withMock(() => importsApi.list(), {
        items: mockImports,
        total: mockImports.length,
        next_cursor: null,
      }),
  });
  const imports = useMemo(() => importsQuery.data?.items ?? [], [importsQuery.data?.items]);

  const active = imports.some((item) => {
    const state = fileState(item);
    return state === "queued" || state === "processing";
  });
  const now = useNow(active);

  const { refetch } = importsQuery;
  useEffect(() => {
    if (!active) return;
    const interval = window.setInterval(() => void refetch(), 2500);
    return () => window.clearInterval(interval);
  }, [active, refetch]);

  const pending = imports.filter((item) => isBlockingAction(item.pending_action));
  const counts = useMemo(() => {
    const result: Record<Filter, number> = { all: 0, active: 0, approval: 0, done: 0, failed: 0 };
    for (const item of imports) {
      const state = fileState(item);
      for (const option of FILTERS) {
        if (matchesFilter(state, option.value)) result[option.value] += 1;
      }
    }
    return result;
  }, [imports]);
  const visible = imports.filter((item) => matchesFilter(fileState(item), filter));

  async function upload(files: File[]) {
    setUploading((current) => [...current, ...files]);
    try {
      const result = DEMO_MODE
        ? await sleep(700).then(() => ({ import: mockImports[0], imports: [], duplicate: false }))
        : await importsApi.upload(files);
      const batch = result.imports?.length ? result.imports : [result.import];
      const duplicates = batch.filter((item) => item.status !== "queued").length;
      toast({
        title:
          files.length === 1 ? "Archivo subido" : `${files.length} archivos subidos`,
        description:
          duplicates > 0
            ? `${duplicates} ya estaba${duplicates === 1 ? "" : "n"} en la lista; no se duplican movimientos.`
            : "Se procesarán automáticamente. Te avisaremos aquí si hay algo que aprobar.",
        variant: "success",
      });
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
    } catch (error) {
      toast({
        title: "No se pudo subir",
        description:
          error instanceof Error && error.message
            ? error.message
            : "Comprueba el formato del archivo.",
        variant: "error",
      });
    } finally {
      setUploading((current) => current.filter((file) => !files.includes(file)));
    }
  }

  async function retry(item: ImportSummary) {
    setRetryingId(item.id);
    try {
      if (DEMO_MODE) await sleep(500);
      else await importsApi.reprocess(item.id);
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
    } catch (error) {
      toast({
        title: "No se pudo reintentar",
        description: error instanceof Error ? error.message : undefined,
        variant: "error",
      });
    } finally {
      setRetryingId(null);
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Ingesta"
        title="Importar"
        description="Sube extractos (CSV, XLSX, PDF o imágenes). Se procesan solos; si el agente necesita crear o confirmar una cuenta, lo deja aquí para que lo apruebes antes de importar los movimientos."
      />

      <Dropzone onFiles={(files) => void upload(files)} pending={false} />

      {pending.length > 0 ? (
        <section aria-labelledby="pending-title" className="space-y-2">
          <div className="flex items-center gap-2">
            <h2 id="pending-title" className="text-[13px] font-semibold text-foreground">
              Pendiente de tu aprobación
            </h2>
            <Badge variant="warning">{pending.length}</Badge>
          </div>
          <div className="space-y-2">
            {pending.map((item) => (
              <PendingActionCard key={item.id} item={item} />
            ))}
          </div>
        </section>
      ) : null}

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <h2 className="text-[13px] font-semibold text-foreground">Archivos</h2>
          <Segmented
            aria-label="Filtrar archivos"
            value={filter}
            onChange={setFilter}
            options={FILTERS.map((option) => ({
              value: option.value,
              label: counts[option.value] ? `${option.label} ${counts[option.value]}` : option.label,
            }))}
          />
        </div>

        {uploading.length > 0 ? (
          <ul className="divide-y divide-border border-b border-border">
            {uploading.map((file, index) => (
              <li key={`${file.name}-${file.size}-${index}`} className="flex items-center gap-3 px-4 py-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
                  <FileTypeIcon name={file.name} mime={file.type} className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[12px] font-medium">{file.name}</p>
                  <p className="text-[10px] text-muted-foreground">{formatBytes(file.size)}</p>
                </div>
                <StateBadge state="uploading" />
              </li>
            ))}
          </ul>
        ) : null}

        {importsQuery.isLoading ? (
          <TableSkeleton rows={4} />
        ) : importsQuery.isError ? (
          <ErrorState
            className="rounded-none border-0"
            title="No se pudieron cargar los archivos"
            action={
              <Button variant="secondary" size="sm" onClick={() => void refetch()}>
                Reintentar
              </Button>
            }
          />
        ) : visible.length === 0 && uploading.length === 0 ? (
          <EmptyState
            title={filter === "all" ? "Todavía no has subido archivos" : "Nada en esta vista"}
            description={
              filter === "all"
                ? "Arrastra un extracto arriba para empezar."
                : "Prueba otro filtro."
            }
            icon={<UploadCloud className="size-4" aria-hidden />}
          />
        ) : (
          <ul className="divide-y divide-border">
            {visible.map((item) => (
              <FileRow
                key={item.id}
                item={item}
                now={now}
                onRetry={(target) => void retry(target)}
                retrying={retryingId === item.id}
              />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
