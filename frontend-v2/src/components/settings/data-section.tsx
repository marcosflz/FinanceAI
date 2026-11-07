"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Archive,
  Database,
  Download,
  FileJson,
  FileSpreadsheet,
  HardDriveDownload,
  RotateCcw,
  Trash2,
  UploadCloud,
  Waypoints,
} from "lucide-react";
import { analyticsApi } from "@/lib/api";
import { DEMO_MODE, withMock } from "@/lib/demo";
import { mockDataHealth, mockMovements } from "@/lib/mock";
import { formatDateTime, formatNumber } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";

function downloadFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function DataSection() {
  const { toast } = useToast();
  const [confirmText, setConfirmText] = useState("");
  const healthQuery = useQuery({
    queryKey: ["analytics", "data-health"],
    queryFn: () => withMock(() => analyticsApi.dataHealth(), mockDataHealth),
  });
  const health = healthQuery.data ?? (DEMO_MODE ? mockDataHealth : null);

  function exportCsv() {
    if (!DEMO_MODE) {
      toast({
        title: "Exportación pendiente",
        description:
          "Scaffold: se conectará a GET /api/v3/export?format=csv. No se ha descargado nada.",
        variant: "error",
      });
      return;
    }
    const header = "value_date,merchant,kind,amount,currency,category,state";
    const rows = mockMovements.map((movement) =>
      [
        movement.value_date,
        `"${(movement.merchant ?? "").replace(/"/g, '""')}"`,
        movement.kind,
        movement.amount,
        movement.currency,
        `"${movement.classification?.categoria ?? ""}"`,
        movement.estado,
      ].join(","),
    );
    downloadFile(
      "financial-tools-movimientos-demo.csv",
      [header, ...rows].join("\n"),
      "text/csv;charset=utf-8",
    );
    toast({
      title: "CSV de ejemplo descargado",
      description: `${mockMovements.length} movimientos del scaffold.`,
      variant: "success",
    });
  }

  function exportJson() {
    if (!DEMO_MODE) {
      toast({
        title: "Exportación pendiente",
        description:
          "Scaffold: se conectará a GET /api/v3/export?format=json. No se ha descargado nada.",
        variant: "error",
      });
      return;
    }
    downloadFile(
      "financial-tools-demo.json",
      JSON.stringify({ exported_at: new Date().toISOString(), movements: mockMovements }, null, 2),
      "application/json",
    );
    toast({
      title: "JSON de ejemplo descargado",
      description: "Incluye movimientos mock con clasificación y estado.",
      variant: "success",
    });
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="py-3">
          <div>
            <CardTitle>Salud de los datos</CardTitle>
            <CardDescription>Última importación, clasificación y conciliación</CardDescription>
          </div>
          <Waypoints className="size-4 text-muted-foreground" aria-hidden />
        </CardHeader>
        {!health ? (
          <CardContent className="pt-0 text-[12px] text-muted-foreground">
            {healthQuery.isError
              ? "No se pudo cargar el estado de los datos."
              : "Cargando…"}
          </CardContent>
        ) : (
        <CardContent className="grid gap-3 pt-0 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: "Última importación", value: formatDateTime(health.last_import_at) },
            {
              label: "Auto-clasificado",
              value: `${health.auto_classified_pct.toLocaleString("es-ES")} %`,
            },
            { label: "Pendientes", value: formatNumber(health.pending_count, 0) },
            {
              label: "Duplicados / sin categoría",
              value: `${health.duplicate_count} / ${health.uncategorized_count}`,
            },
          ].map((item) => (
            <div key={item.label} className="rounded-lg border border-border bg-subtle p-2.5">
              <p className="text-[10px] text-muted-foreground">{item.label}</p>
              <p className="num mt-1 text-[12px] font-medium">{item.value}</p>
            </div>
          ))}
          <p className="text-[10px] leading-4 text-muted-foreground sm:col-span-2 lg:col-span-4">
            Fichero más reciente:{" "}
            <span className="num">{health.last_import_filename ?? "—"}</span>
            {health.missing_opening_positions
              ? " · faltan posiciones de apertura de la cartera."
              : ""}
          </p>
        </CardContent>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="py-3">
            <div>
              <CardTitle>Exportar</CardTitle>
              <CardDescription>Movimientos y clasificaciones</CardDescription>
            </div>
            <Download className="size-4 text-muted-foreground" aria-hidden />
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            <button
              type="button"
              onClick={exportCsv}
              className="flex w-full items-center gap-2.5 rounded-lg border border-border px-3 py-2.5 text-left transition-colors hover:bg-muted"
            >
              <FileSpreadsheet className="size-4 text-positive" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block text-[12px] font-medium">CSV de movimientos</span>
                <span className="block text-[10px] text-muted-foreground">
                  Fecha, merchant, tipo, importe, categoría y estado
                </span>
              </span>
              <Download className="size-3.5 text-muted-foreground" aria-hidden />
            </button>
            <button
              type="button"
              onClick={exportJson}
              className="flex w-full items-center gap-2.5 rounded-lg border border-border px-3 py-2.5 text-left transition-colors hover:bg-muted"
            >
              <FileJson className="size-4 text-accent" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block text-[12px] font-medium">JSON completo</span>
                <span className="block text-[10px] text-muted-foreground">
                  Incluye clasificación, origen y confianza
                </span>
              </span>
              <Download className="size-3.5 text-muted-foreground" aria-hidden />
            </button>
            <p className="pt-1 text-[10px] leading-4 text-muted-foreground">
              {DEMO_MODE
                ? "Modo demo: las descargas usan los datos de ejemplo del scaffold."
                : "El endpoint de exportación está pendiente; los botones no descargan datos reales en F5."}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="py-3">
            <div>
              <CardTitle>Copias de seguridad</CardTitle>
              <CardDescription>PostgreSQL y ficheros de importación</CardDescription>
            </div>
            <Archive className="size-4 text-muted-foreground" aria-hidden />
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            <div className="rounded-lg border border-border bg-subtle p-2.5">
              <p className="flex items-center gap-1.5 text-[11px] font-medium">
                <HardDriveDownload className="size-3.5 text-muted-foreground" aria-hidden />
                Backup de base de datos
              </p>
              <p className="mt-0.5 text-[10px] leading-4 text-muted-foreground">
                Se ejecutará con <span className="num">pg_dump</span> desde el servidor.
                Nunca dentro del repositorio.
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() =>
                    toast({
                      title: "Backup no ejecutado",
                      description:
                        "Scaffold: se conectará al endpoint de backup del backend.",
                      variant: "error",
                    })
                  }
                >
                  <Database className="size-3.5" aria-hidden />
                  Crear copia
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    toast({
                      title: "Restauración no ejecutada",
                      description:
                        "Scaffold: requiere confirmación explícita y un backup validado.",
                      variant: "error",
                    })
                  }
                >
                  <UploadCloud className="size-3.5" aria-hidden />
                  Restaurar
                </Button>
              </div>
            </div>

            <div className="rounded-lg border border-border bg-subtle p-2.5">
              <p className="flex items-center gap-1.5 text-[11px] font-medium">
                <RotateCcw className="size-3.5 text-muted-foreground" aria-hidden />
                Reconstruir memoria de clasificación
              </p>
              <p className="mt-0.5 text-[10px] leading-4 text-muted-foreground">
                Índice derivado de las decisiones humanas vigentes. Reconstruible en
                cualquier momento.
              </p>
              <Button
                className="mt-2"
                variant="secondary"
                size="sm"
                onClick={() =>
                  toast({
                    title: "Reconstrucción pendiente",
                    description: "Se conectará a POST /api/v3/classification-memory/rebuild.",
                    variant: "success",
                  })
                }
              >
                Reconstruir
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-negative/25">
        <CardHeader className="py-3">
          <div>
            <CardTitle className="text-negative">Zona de riesgo</CardTitle>
            <CardDescription>
              Borrar importaciones o reiniciar datos requiere confirmación explícita.
            </CardDescription>
          </div>
          <Trash2 className="size-4 text-negative" aria-hidden />
        </CardHeader>
        <CardContent className="pt-0">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label
                htmlFor="confirm-reset"
                className="mb-1.5 block text-[11px] text-muted-foreground"
              >
                Escribe <span className="num font-medium text-foreground">BORRAR</span>{" "}
                para habilitar la acción
              </label>
              <Input
                id="confirm-reset"
                value={confirmText}
                onChange={(event) => setConfirmText(event.target.value)}
                placeholder="BORRAR"
                className="max-w-xs"
              />
            </div>
            <Button
              variant="danger"
              size="sm"
              disabled={confirmText !== "BORRAR"}
              onClick={() => {
                setConfirmText("");
                toast({
                  title: "Acción no ejecutada",
                  description:
                    "Scaffold: el borrado real se implementará con confirmación y backup previo.",
                  variant: "error",
                });
              }}
            >
              <Trash2 className="size-3.5" aria-hidden />
              Borrar datos
            </Button>
          </div>
          <p className="mt-2 text-[10px] leading-4 text-muted-foreground">
            Pendiente de F7: exportar antes de borrar, crear backup verificado y registrar
            la acción en <span className="num">audit_log</span>. También se puede borrar una
            importación concreta desde su detalle.
          </p>
          <Link
            href="/imports"
            className="mt-2 inline-flex items-center gap-1 text-[10px] font-medium text-muted-foreground hover:text-foreground"
          >
            Ir a importaciones
            <Download className="size-2.5 rotate-[-90deg]" aria-hidden />
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
