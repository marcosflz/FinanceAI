"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Database,
  FileJson,
  Info,
  Loader2,
  RefreshCw,
  RotateCcw,
  Rows3,
  TriangleAlert,
} from "lucide-react";
import { importsApi } from "@/lib/api";
import { DEMO_MODE, sleep, withMock } from "@/lib/demo";
import { getMockImport } from "@/lib/mock";
import type { ImportIncidence, Movement } from "@/lib/types";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatNumber,
  toNumber,
} from "@/lib/utils";
import { PageHeader, LinkTabs, type LinkTabItem } from "@/components/ui/page-header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import {
  ImportStatusBadge,
  importSourceLabels,
} from "@/components/imports/import-status";
import { StateBadge } from "@/components/movements/movement-badges";
import {
  PendingActionCard,
  isBlockingAction,
} from "@/components/imports/pending-action-card";
import { cn } from "@/lib/utils";

const DETAIL_TABS = ["resumen", "transacciones", "incidencias", "raw"] as const;
type DetailTab = (typeof DETAIL_TABS)[number];

function MetadataRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right text-[11px] font-medium text-foreground">{value}</dd>
    </div>
  );
}

function IncidenceRow({ incidence }: { incidence: ImportIncidence }) {
  const config = {
    error: {
      icon: AlertOctagon,
      className: "bg-negative-soft text-negative",
      label: "Error",
    },
    warning: {
      icon: TriangleAlert,
      className: "bg-warning-soft text-warning",
      label: "Aviso",
    },
    info: {
      icon: Info,
      className: "bg-info-soft text-info",
      label: "Info",
    },
  }[incidence.severity];
  const Icon = config.icon;

  return (
    <div className="flex items-start gap-2.5 py-2.5">
      <span
        className={cn(
          "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md",
          config.className,
        )}
      >
        <Icon className="size-3" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-medium text-foreground">{incidence.message}</p>
        <p className="mt-0.5 text-[10px] text-muted-foreground">
          {config.label} · <span className="num">{incidence.code}</span>
          {incidence.row_index ? ` · fila ${incidence.row_index}` : ""}
        </p>
      </div>
    </div>
  );
}

function classificationParts(movement: Movement): {
  root: string;
  child: string;
} {
  const classification = movement.classification;
  if (!classification) return { root: "Sin categoría", child: "—" };
  if (classification.categoria_raiz_nombre) {
    return {
      root: classification.categoria_raiz_nombre,
      child: classification.subcategoria_nombre ?? "—",
    };
  }
  const parts = (classification.categoria ?? "").split(" › ");
  return {
    root: parts[0] || "Sin categoría",
    child: parts.slice(1).join(" › ") || "—",
  };
}

function ImportTransactions({ transactions }: { transactions: Movement[] }) {
  if (transactions.length === 0) {
    return (
      <EmptyState
        title="Sin transacciones vinculadas"
        description="La importación se procesó pero no generó movimientos nuevos."
        icon={<Rows3 className="size-4" aria-hidden />}
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-left">
        <thead>
          <tr className="border-b border-border text-[10px] font-medium uppercase tracking-[0.06em] text-muted-foreground">
            <th className="px-3 py-2">Fecha</th>
            <th className="px-2 py-2">Merchant</th>
            <th className="hidden px-2 py-2 sm:table-cell">Categoría</th>
            <th className="hidden px-2 py-2 sm:table-cell">Subcategoría</th>
            <th className="px-2 py-2">Estado</th>
            <th className="px-2 py-2 text-right">Importe</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((movement) => {
            const parts = classificationParts(movement);
            return (
            <tr key={movement.id} className="border-b border-border/70 text-[12px]">
              <td className="whitespace-nowrap px-3 py-2 text-[11px] text-muted-foreground">
                {formatDate(movement.value_date, "short")}
              </td>
              <td className="px-2 py-2">
                <p className="max-w-[220px] truncate font-medium">
                  {movement.merchant ?? "Sin merchant"}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  {movement.description ?? movement.kind}
                </p>
              </td>
              <td className="hidden px-2 py-2 text-[11px] text-muted-foreground sm:table-cell">
                {parts.root}
              </td>
              <td className="hidden px-2 py-2 text-[11px] text-muted-foreground sm:table-cell">
                {parts.child}
              </td>
              <td className="px-2 py-2">
                <StateBadge state={movement.estado} />
              </td>
              <td
                className={cn(
                  "num whitespace-nowrap px-2 py-2 text-right font-medium",
                  movement.amount !== null && toNumber(movement.amount) >= 0 && "text-positive",
                )}
              >
                {movement.amount === null
                  ? "—"
                  : formatMoney(movement.amount, {
                      signDisplay: "always",
                      currency: movement.currency,
                    })}
              </td>
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ImportDetailView() {
  const params = useParams();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [reprocessing, setReprocessing] = useState(false);
  const id = Array.isArray(params.id) ? params.id[0] : (params.id ?? "");

  const tabParam = searchParams.get("tab") ?? "resumen";
  const activeTab: DetailTab = DETAIL_TABS.includes(tabParam as DetailTab)
    ? (tabParam as DetailTab)
    : "resumen";

  const importQuery = useQuery({
    queryKey: ["imports", id],
    queryFn: () =>
      withMock(() => importsApi.get(id), getMockImport(Number(id))),
    enabled: Boolean(id),
  });

  const detail = importQuery.data;
  useEffect(() => {
    if (!detail) return;
    if (!["queued", "processing", "parsing"].includes(detail.status)) return;
    const interval = window.setInterval(() => {
      void importQuery.refetch();
    }, 2500);
    return () => window.clearInterval(interval);
  }, [detail, importQuery]);

  async function reprocess() {
    if (!detail || reprocessing) return;
    setReprocessing(true);
    try {
      if (DEMO_MODE) await sleep(600);
      else await importsApi.reprocess(detail.id);
      await queryClient.invalidateQueries({ queryKey: ["imports", id] });
      toast({
        title: "Reprocesando",
        description: DEMO_MODE
          ? "Simulado en modo demo: no se ha vuelto a parsear el fichero."
          : "El fichero vuelve a la cola y se extraerá de nuevo.",
        variant: "success",
      });
    } catch (error) {
      toast({
        title: "No se pudo reprocesar",
        description:
          error instanceof Error && error.message
            ? error.message
            : "Comprueba que el fichero sigue disponible en el servidor.",
        variant: "error",
      });
    } finally {
      setReprocessing(false);
    }
  }

  if (importQuery.isLoading) return <PageSkeleton />;

  if (importQuery.isError || !detail) {
    return (
      <ErrorState
        title="No se pudo abrir la importación"
        description="Puede que el identificador no exista o que la API v3 no esté disponible."
        action={
          <Button variant="secondary" size="sm" onClick={() => importQuery.refetch()}>
            <RefreshCw className="size-3.5" aria-hidden />
            Reintentar
          </Button>
        }
      />
    );
  }

  const transactions = detail.transactions ?? [];
  const incidences = detail.incidences ?? [];
  const rawRows = detail.raw_rows ?? [];
  const visibleTransactions = transactions.slice(0, 100);

  const tabItems: LinkTabItem[] = [
    {
      value: "resumen",
      label: "Resumen",
      href: `/imports/${id}?tab=resumen`,
    },
    {
      value: "transacciones",
      label: "Transacciones",
      href: `/imports/${id}?tab=transacciones`,
      count: transactions.length,
    },
    {
      value: "incidencias",
      label: "Incidencias",
      href: `/imports/${id}?tab=incidencias`,
      count: incidences.length,
    },
    {
      value: "raw",
      label: "Raw",
      href: `/imports/${id}?tab=raw`,
      count: rawRows.length,
    },
  ];

  const balanceDifference = toNumber(detail.reconciliation_report?.balance_difference);
  const hasBalanceWarning = Math.abs(balanceDifference) > 0.005;
  return (
    <div className="space-y-4">
      <Link
        href="/imports"
        className="inline-flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        Importaciones
      </Link>

      <PageHeader
        eyebrow={importSourceLabels[detail.source] ?? detail.source}
        title={detail.filename}
        description={
          detail.period_start && detail.period_end
            ? `Periodo ${formatDate(detail.period_start, "medium")} – ${formatDate(detail.period_end, "medium")} · ${detail.row_count} filas · ${detail.account?.nombre ?? "cuenta sin asignar"}`
            : `${detail.row_count} filas · ${detail.account?.nombre ?? "cuenta sin asignar"}`
        }
        actions={
          <>
            <ImportStatusBadge status={detail.status} />
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void reprocess()}
              loading={reprocessing}
              disabled={["queued", "processing", "parsing"].includes(detail.status)}
            >
              <RotateCcw className="size-3.5" aria-hidden />
              Reprocesar
            </Button>
          </>
        }
      />

      {["queued", "processing", "parsing"].includes(detail.status) ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-accent/25 bg-accent-soft px-3 py-2.5">
          <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-accent" aria-hidden />
          <div>
            <p className="text-[12px] font-medium text-accent">Procesando extracto</p>
            <p className="mt-0.5 text-[11px] leading-5 text-accent/90">
              El worker está extrayendo y validando los movimientos. Esta página
              se actualizará automáticamente.
            </p>
          </div>
        </div>
      ) : null}

      {detail.status === "failed" && detail.error ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-negative/25 bg-negative-soft px-3 py-2.5">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-negative" aria-hidden />
          <div>
            <p className="text-[12px] font-medium text-negative">La importación falló</p>
            <p className="mt-0.5 text-[11px] leading-5 text-negative/90">{detail.error}</p>
          </div>
        </div>
      ) : null}

      {isBlockingAction(detail.pending_action) ? (
        <PendingActionCard item={detail} showFile={false} />
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-6">
        {[
          { label: "Filas", value: formatNumber(detail.row_count, 0) },
          { label: "Nuevos", value: `+${detail.movement_new_count}` },
          { label: "Ya vistos", value: String(detail.movement_seen_count) },
          { label: "Duplicados", value: String(detail.duplicate_count) },
          { label: "Sin categoría", value: String(detail.uncategorized_count) },
          {
            label: "Enlaces auto",
            value: String(detail.internal_transfer_links?.linked ?? 0),
          },
        ].map((stat) => (
          <div key={stat.label} className="card px-4 py-3">
            <p className="text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
              {stat.label}
            </p>
            <p className="num mt-1 text-[20px] font-semibold leading-6">{stat.value}</p>
          </div>
        ))}
      </div>

      <LinkTabs items={tabItems} active={activeTab} />

      {activeTab === "resumen" ? (
        <div className="grid gap-4 xl:grid-cols-12">
          <Card className="xl:col-span-7">
            <CardHeader>
              <div>
                <CardTitle>Ficha de la importación</CardTitle>
                <CardDescription>Trazabilidad del fichero y del parser</CardDescription>
              </div>
              <FileJson className="size-4 text-muted-foreground" aria-hidden />
            </CardHeader>
            <CardContent className="pt-1">
              <dl className="divide-y divide-border">
                <MetadataRow
                  label="Fuente"
                  value={importSourceLabels[detail.source] ?? detail.source}
                />
                <MetadataRow label="Cuenta" value={detail.account?.nombre ?? "Sin asignar"} />
                <MetadataRow
                  label="Cuenta detectada"
                  value={
                    detail.account_match?.detected
                      ? [
                          detail.account_match.detected.bank,
                          detail.account_match.detected.product,
                          detail.account_match.detected.account_iban
                            ? `…${detail.account_match.detected.account_iban.slice(-4)}`
                            : null,
                        ]
                          .filter(Boolean)
                          .join(" · ") || "No detectada"
                      : "No detectada"
                  }
                />
                <MetadataRow
                  label="Validación de cuenta"
                  value={
                    <span className="flex items-center justify-end gap-1.5">
                      <Badge
                        variant={
                          detail.account_match?.status === "match" ||
                          detail.account_match?.status === "match_weak"
                            ? "positive"
                            : detail.account_match?.status === "unknown"
                              ? "outline"
                              : "warning"
                        }
                      >
                        {detail.account_match?.status ?? "sin validar"}
                      </Badge>
                    </span>
                  }
                />
                <MetadataRow
                  label="Saldo inicial detectado"
                  value={
                    detail.balance_start != null
                      ? `${formatMoney(detail.balance_start)} ${
                          detail.balance_start_date
                            ? `· ${formatDate(detail.balance_start_date, "medium")}`
                            : ""
                        }`
                      : "No detectado"
                  }
                />
                <MetadataRow label="Parser" value={detail.parser_version} />
                <MetadataRow
                  label="Hash del fichero"
                  value={<span className="num break-all">{detail.file_hash}</span>}
                />
                <MetadataRow label="Subida" value={formatDateTime(detail.created_at)} />
                <MetadataRow
                  label="Procesada"
                  value={detail.parsed_at ? formatDateTime(detail.parsed_at) : "—"}
                />
                <MetadataRow
                  label="Rango detectado"
                  value={
                    detail.period_start && detail.period_end
                      ? `${formatDate(detail.period_start, "medium")} – ${formatDate(detail.period_end, "medium")}`
                      : "No detectado"
                  }
                />
                <MetadataRow
                  label="MIME"
                  value={<span className="num">{detail.mime_type}</span>}
                />
              </dl>
            </CardContent>
          </Card>

          <Card className="xl:col-span-5">
            <CardHeader>
              <div>
                <CardTitle>Reconciliación</CardTitle>
                <CardDescription>Sumas y balance del extracto</CardDescription>
              </div>
              {detail.reconciliation_report ? (
                <Badge variant={hasBalanceWarning ? "warning" : "positive"} dot>
                  {hasBalanceWarning ? "Descuadre" : "Cuadra"}
                </Badge>
              ) : (
                <Badge variant="neutral">No disponible</Badge>
              )}
            </CardHeader>
            <CardContent className="pt-2">
              {detail.reconciliation_report ? (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-lg border border-border bg-subtle p-3">
                      <p className="text-[10px] text-muted-foreground">Total movimientos</p>
                      <p className="num mt-1 text-[15px] font-medium">
                        {formatMoney(detail.reconciliation_report.total_amount)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-subtle p-3">
                      <p className="text-[10px] text-muted-foreground">Diferencia de balance</p>
                      <p
                        className={cn(
                          "num mt-1 text-[15px] font-medium",
                          hasBalanceWarning ? "text-warning" : "text-positive",
                        )}
                      >
                        {formatMoney(detail.reconciliation_report.balance_difference, {
                          signDisplay: "always",
                        })}
                      </p>
                    </div>
                  </div>
                  <div className="mt-3 flex items-start gap-2 rounded-lg bg-muted px-2.5 py-2 text-[10px] leading-4 text-muted-foreground">
                    {detail.reconciliation_report.rows_ok ? (
                      <CheckCircle2 className="mt-0.5 size-3 shrink-0 text-positive" aria-hidden />
                    ) : (
                      <AlertTriangle className="mt-0.5 size-3 shrink-0 text-warning" aria-hidden />
                    )}
                    <p>
                      {detail.reconciliation_report.rows_ok
                        ? "Todas las filas del fichero tienen un evento normalizado."
                        : "Hay filas sin evento normalizado; revisa las incidencias."}
                    </p>
                  </div>
                </>
              ) : (
                <p className="py-4 text-[11px] leading-5 text-muted-foreground">
                  Este fichero no tiene datos de conciliación. Puede ser una imagen o una
                  importación fallida.
                </p>
              )}

              <div className="mt-4 border-t border-border pt-2">
                <p className="mb-1 text-[11px] font-medium">Incidencias</p>
                {incidences.length > 0 ? (
                  incidences.slice(0, 3).map((incidence) => (
                    <IncidenceRow key={incidence.id} incidence={incidence} />
                  ))
                ) : (
                  <p className="py-2 text-[10px] text-muted-foreground">
                    Sin incidencias registradas.
                  </p>
                )}
              </div>
            </CardContent>
          </Card>

          <div className="xl:col-span-12">
            <Card>
              <CardHeader className="py-3">
                <div>
                  <CardTitle>Acciones</CardTitle>
                  <CardDescription>Continúa el flujo de importación</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2 pt-0">
                <Link
                  href="/movements?tab=por-revisar"
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-[12px] font-medium text-accent-foreground transition-colors hover:bg-accent/90"
                >
                  Revisar movimientos
                  <ArrowRight className="size-3.5" aria-hidden />
                </Link>
                <Link
                  href="/imports"
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-[12px] font-medium transition-colors hover:bg-muted"
                >
                  <Database className="size-3.5" aria-hidden />
                  Volver al historial
                </Link>
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}

      {activeTab === "transacciones" ? (
        <Card className="overflow-hidden">
          <CardHeader className="py-3">
            <div>
              <CardTitle>Transacciones normalizadas</CardTitle>
              <CardDescription>
                Primeras {visibleTransactions.length} de {transactions.length} filas
                vinculadas a esta importación
              </CardDescription>
            </div>
            <Link
              href="/movements"
              className="text-[11px] font-medium text-muted-foreground hover:text-foreground"
            >
              Ver bandeja
            </Link>
          </CardHeader>
          <ImportTransactions transactions={visibleTransactions} />
        </Card>
      ) : null}

      {activeTab === "incidencias" ? (
        <Card>
          <CardHeader className="py-3">
            <div>
              <CardTitle>Incidencias</CardTitle>
              <CardDescription>
                Problemas detectados durante el parseo y la reconciliación
              </CardDescription>
            </div>
            <Badge variant={incidences.length > 0 ? "warning" : "positive"}>
              {incidences.length}
            </Badge>
          </CardHeader>
          <CardContent className="pt-0">
            {incidences.length > 0 ? (
              <div className="divide-y divide-border">
                {incidences.map((incidence) => (
                  <IncidenceRow key={incidence.id} incidence={incidence} />
                ))}
              </div>
            ) : (
              <EmptyState
                title="Sin incidencias"
                description="El fichero se procesó sin avisos ni errores."
                icon={<CheckCircle2 className="size-4" aria-hidden />}
              />
            )}
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "raw" ? (
        <Card>
          <CardHeader className="py-3">
            <div>
              <CardTitle>Filas raw</CardTitle>
              <CardDescription>
                JSON original conservado para auditoría ·{" "}
                {DEMO_MODE ? "datos de ejemplo" : "sin redacción adicional"}
              </CardDescription>
            </div>
            <FileJson className="size-4 text-muted-foreground" aria-hidden />
          </CardHeader>
          <CardContent className="pt-0">
            {rawRows.length === 0 ? (
              <EmptyState
                title="Sin filas raw"
                description="Este tipo de fichero no conserva filas crudas."
                icon={<FileJson className="size-4" aria-hidden />}
              />
            ) : (
              <div className="divide-y divide-border">
                {rawRows.map((row) => (
                  <details key={row.id} className="group py-2">
                    <summary className="flex cursor-pointer list-none items-center gap-2 text-[11px]">
                      <span className="num rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        fila {row.row_index}
                      </span>
                      <span className="num text-[10px] text-muted-foreground">
                        hash {row.row_hash}
                      </span>
                      <span className="ml-auto text-[10px] text-muted-foreground group-open:hidden">
                        ver JSON
                      </span>
                      <span className="ml-auto hidden text-[10px] text-muted-foreground group-open:block">
                        ocultar
                      </span>
                    </summary>
                    <pre className="num mt-2 max-h-64 overflow-auto rounded-lg border border-border bg-subtle p-3 text-[10px] leading-5 text-foreground scrollbar-thin">
                      {JSON.stringify(row.payload, null, 2)}
                    </pre>
                  </details>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
