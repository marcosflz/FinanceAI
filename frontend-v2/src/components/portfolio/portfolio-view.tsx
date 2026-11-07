"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  ChartNoAxesCombined,
  CircleDollarSign,
  PiggyBank,
  RefreshCw,
  ShieldAlert,
  TriangleAlert,
} from "lucide-react";
import { portfolioApi } from "@/lib/api";
import { withMock } from "@/lib/demo";
import { getMockPortfolio } from "@/lib/mock";
import type { AssetClass, Position } from "@/lib/types";
import {
  cn,
  formatDate,
  formatMoney,
  formatPercent,
  formatQuantity,
  toNumber,
} from "@/lib/utils";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { AllocationChart } from "@/components/portfolio/allocation-chart";

const classLabels: Record<AssetClass, string> = {
  stock: "Acciones",
  etf: "ETFs",
  fondo: "Fondos",
  cripto: "Cripto",
  otro: "Otros",
};

function Pnl({
  value,
  percent,
  className,
}: {
  value: number;
  percent?: number;
  className?: string;
}) {
  const positive = value >= 0;
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span
        className={cn(
          "num text-[11px] font-medium",
          positive ? "text-positive" : "text-negative",
        )}
      >
        {formatMoney(value, { signDisplay: "always" })}
      </span>
      {percent !== undefined ? (
        <Badge variant={positive ? "positive" : "negative"} className="tabular">
          {formatPercent(percent, { signDisplay: "always" })}
        </Badge>
      ) : null}
    </span>
  );
}

function PositionRow({ position }: { position: Position }) {
  return (
    <tr className="border-b border-border/70 text-[12px] transition-colors hover:bg-muted/40">
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-2">
          <div className="min-w-0">
            <p className="num text-[12px] font-medium">{position.symbol}</p>
            <p className="max-w-[220px] truncate text-[10px] text-muted-foreground">
              {position.nombre}
              {position.isin ? ` · ${position.isin}` : ""}
            </p>
          </div>
          {position.datos_incompletos ? (
            <Badge variant="warning" title="Faltan datos de precio o apertura">
              Incompleto
            </Badge>
          ) : null}
        </div>
      </td>
      <td className="hidden px-2 py-2.5 lg:table-cell">
        <Badge variant="outline">{classLabels[position.asset_class]}</Badge>
      </td>
      <td className="num px-2 py-2.5 text-right text-[11px]">
        {formatQuantity(position.cantidad)}
      </td>
      <td className="num hidden px-2 py-2.5 text-right text-[11px] text-muted-foreground xl:table-cell">
        {formatMoney(position.precio_medio)}
      </td>
      <td className="num hidden px-2 py-2.5 text-right text-[11px] text-muted-foreground xl:table-cell">
        <span title={position.precio_fecha ? `Precio de ${position.precio_fecha}` : undefined}>
          {position.precio_actual === null ? "—" : formatMoney(position.precio_actual)}
        </span>
      </td>
      <td className="num px-2 py-2.5 text-right text-[11px] font-medium">
        {formatMoney(position.valor_actual)}
      </td>
      <td className="px-2 py-2.5 text-right">
        {position.coste_completo === false ? (
          <span className="text-[10px] text-muted-foreground">Coste incompleto</span>
        ) : (
          <Pnl
            value={toNumber(position.pnl_no_realizado)}
            percent={position.pnl_no_realizado_pct}
          />
        )}
      </td>
      <td className="hidden px-2 py-2.5 text-right sm:table-cell">
        <div className="flex items-center justify-end gap-1.5">
          <div className="h-1 w-10 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-accent"
              style={{ width: `${Math.min(100, Math.max(1, position.peso))}%` }}
            />
          </div>
          <span className="num w-10 text-[10px] text-muted-foreground">
            {formatPercent(position.peso, { fractionDigits: 1 })}
          </span>
        </div>
      </td>
    </tr>
  );
}

export function PortfolioView() {
  const portfolioQuery = useQuery({
    queryKey: ["portfolio"],
    queryFn: () => withMock(() => portfolioApi.summary(), getMockPortfolio()),
  });

  if (portfolioQuery.isLoading) return <PageSkeleton />;

  if (portfolioQuery.isError || !portfolioQuery.data) {
    return (
      <ErrorState
        title="No se pudo cargar la cartera"
        description="La API /api/v3/portfolio no respondió y no hay datos de respaldo."
        action={
          <Button variant="secondary" size="sm" onClick={() => portfolioQuery.refetch()}>
            <RefreshCw className="size-3.5" aria-hidden />
            Reintentar
          </Button>
        }
      />
    );
  }

  const portfolio = portfolioQuery.data;
  const pnlTotal = toNumber(portfolio.pnl_no_realizado);
  const visiblePositions = portfolio.posiciones.filter(
    (position) => toNumber(position.cantidad) > 0,
  );
  // El P&L no realizado solo existe para posiciones con coste completo y
  // valoración; el % se calcula sobre ese mismo coste y no sobre el total
  // (que incluye posiciones sin P&L y lo infravaloraba).
  const pnlCostBase = visiblePositions
    .filter((position) => !position.datos_incompletos)
    .reduce((sum, position) => sum + toNumber(position.coste_total), 0);
  const pnlPct = pnlCostBase > 0 ? (pnlTotal / pnlCostBase) * 100 : 0;
  const hiddenNegatives = portfolio.posiciones.filter(
    (position) =>
      toNumber(position.cantidad) <= 0 &&
      !portfolio.posiciones_negativas.some(
        (negative) => negative.asset_id === position.asset_id,
      ),
  );
  const incomplete = visiblePositions.filter((position) => position.datos_incompletos);
  const negativeCount =
    portfolio.posiciones_negativas.length + hiddenNegatives.length;
  const hasWarnings =
    portfolio.avisos.length > 0 ||
    negativeCount > 0 ||
    incomplete.length > 0;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Inversión"
        title="Cartera"
        description="Posiciones, coste y rendimiento. Los datos vienen del modelo v2: activos, transacciones y snapshots de posición."
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void portfolioQuery.refetch()}
              loading={portfolioQuery.isFetching}
            >
              <RefreshCw className="size-3.5" aria-hidden />
              Recargar
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="card px-4 py-3">
          <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            <ChartNoAxesCombined className="size-3" aria-hidden />
            Valor actual
          </p>
          <p className="num mt-1 text-[22px] font-semibold leading-7">
            {formatMoney(portfolio.valor_total)}
          </p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            Coste {formatMoney(portfolio.coste_total)}
          </p>
        </div>
        <div className="card px-4 py-3">
          <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            <CircleDollarSign className="size-3" aria-hidden />
            P&amp;L no realizado
          </p>
          <p
            className={cn(
              "num mt-1 text-[22px] font-semibold leading-7",
              pnlTotal >= 0 ? "text-positive" : "text-negative",
            )}
          >
            {formatMoney(pnlTotal, { signDisplay: "always" })}
          </p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            {formatPercent(pnlPct, { signDisplay: "always" })} sobre coste
          </p>
        </div>
        <div className="card px-4 py-3">
          <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            <PiggyBank className="size-3" aria-hidden />
            P&amp;L realizado
          </p>
          <p
            className={cn(
              "num mt-1 text-[22px] font-semibold leading-7",
              toNumber(portfolio.pnl_realizado) >= 0 ? "text-positive" : "text-negative",
            )}
          >
            {formatMoney(portfolio.pnl_realizado, { signDisplay: "always" })}
          </p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            Dividendos {formatMoney(portfolio.dividendos)}
          </p>
        </div>
        <div className="card px-4 py-3">
          <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            <ShieldAlert className="size-3" aria-hidden />
            Cobertura
          </p>
          <p className="num mt-1 text-[22px] font-semibold leading-7">
            {visiblePositions.length}
          </p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            {incomplete.length} con datos incompletos
          </p>
        </div>
      </div>

      {hasWarnings ? (
        <Card className="border-warning/30 bg-warning-soft/60">
          <CardContent className="flex flex-col gap-2 p-3.5 sm:flex-row sm:items-start">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-[12px] font-medium text-warning">Avisos de datos</p>
              <ul className="mt-1 space-y-1">
                {portfolio.avisos.map((warning) => (
                  <li key={warning} className="text-[11px] leading-4 text-warning/90">
                    {warning}
                  </li>
                ))}
                {portfolio.posiciones_negativas.map((position) => (
                  <li key={position.asset_id} className="text-[11px] leading-4 text-warning/90">
                    {position.symbol}: {formatQuantity(position.cantidad)} participaciones
                    (negativo). Oculto hasta conciliar la posición de apertura.
                  </li>
                ))}
                {hiddenNegatives.map((position) => (
                  <li key={`hidden-${position.asset_id}`} className="text-[11px] leading-4 text-warning/90">
                    {position.symbol}: cantidad {formatQuantity(position.cantidad)}. No se
                    muestra en la tabla hasta corregir el dato.
                  </li>
                ))}
                {incomplete.length > 0 ? (
                  <li className="text-[11px] leading-4 text-warning/90">
                    {incomplete.length} posición
                    {incomplete.length === 1 ? "" : "es"} con precio o apertura incompletos.
                  </li>
                ) : null}
              </ul>
            </div>
            <Link
              href="/imports"
              className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-warning hover:underline"
            >
              Importar posiciones
              <ArrowUpRight className="size-3" aria-hidden />
            </Link>
          </CardContent>
        </Card>
      ) : null}

      <Card className="overflow-hidden">
        <CardHeader className="py-3">
          <div>
            <CardTitle>Posiciones</CardTitle>
            <CardDescription>
              Valor, coste y P&amp;L no realizado ·{" "}
              {portfolio.calculado_en
                ? formatDate(portfolio.calculado_en, "medium")
                : "sin fecha de cálculo"}
            </CardDescription>
          </div>
          <Badge variant="outline">{portfolio.moneda}</Badge>
        </CardHeader>

        {visiblePositions.length === 0 ? (
          <EmptyState
            title="Sin posiciones"
            description="Importa un extracto de valores o una compra para empezar a calcular la cartera."
            icon={<ChartNoAxesCombined className="size-4" aria-hidden />}
          />
        ) : (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[760px] border-collapse text-left">
                <thead>
                  <tr className="border-b border-border text-[10px] font-medium uppercase tracking-[0.06em] text-muted-foreground">
                    <th className="px-3 py-2">Activo</th>
                    <th className="hidden px-2 py-2 lg:table-cell">Clase</th>
                    <th className="px-2 py-2 text-right">Cantidad</th>
                    <th className="hidden px-2 py-2 text-right xl:table-cell">Precio medio</th>
                    <th className="hidden px-2 py-2 text-right xl:table-cell">Precio actual</th>
                    <th className="px-2 py-2 text-right">Valor</th>
                    <th className="px-2 py-2 text-right">P&amp;L</th>
                    <th className="hidden px-2 py-2 text-right sm:table-cell">Peso</th>
                  </tr>
                </thead>
                <tbody>
                  {visiblePositions.map((position) => (
                    <PositionRow key={position.asset_id} position={position} />
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-border text-[11px]">
                    <td colSpan={5} className="px-3 py-2.5 text-muted-foreground">
                      Total cartera
                    </td>
                    <td className="num px-2 py-2.5 text-right font-semibold">
                      {formatMoney(portfolio.valor_total)}
                    </td>
                    <td className="px-2 py-2.5 text-right">
                      <Pnl value={pnlTotal} percent={pnlPct} />
                    </td>
                    <td className="hidden px-2 py-2.5 text-right sm:table-cell">
                      <span className="num text-[10px] text-muted-foreground">100 %</span>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>

            <div className="divide-y divide-border md:hidden">
              {visiblePositions.map((position) => (
                <div key={position.asset_id} className="px-4 py-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="num text-[12px] font-medium">{position.symbol}</p>
                      <p className="truncate text-[10px] text-muted-foreground">
                        {position.nombre}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="num text-[12px] font-medium">
                        {formatMoney(position.valor_actual)}
                      </p>
                      {position.coste_completo === false ? (
                        <span className="text-[10px] text-muted-foreground">
                          Coste incompleto
                        </span>
                      ) : (
                        <Pnl
                          value={toNumber(position.pnl_no_realizado)}
                          percent={position.pnl_no_realizado_pct}
                        />
                      )}
                    </div>
                  </div>
                  <div className="mt-2 flex items-center gap-2 text-[10px] text-muted-foreground">
                    <Badge variant="outline">{classLabels[position.asset_class]}</Badge>
                    <span className="num">
                      {formatQuantity(position.cantidad)} uds.
                    </span>
                    <span className="num ml-auto">
                      Peso {formatPercent(position.peso)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>

      <div className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-4">
          <CardHeader className="py-3">
            <div>
              <CardTitle>Asignación</CardTitle>
              <CardDescription>Por clase de activo</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            <AllocationChart summary={portfolio} />
          </CardContent>
        </Card>

        <Card className="xl:col-span-4">
          <CardHeader className="py-3">
            <div>
              <CardTitle>Rentabilidad y costes</CardTitle>
              <CardDescription>Acumulado del periodo disponible</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            <dl className="divide-y divide-border">
              {[
                { label: "Valor actual", value: formatMoney(portfolio.valor_total) },
                { label: "Coste restante", value: formatMoney(portfolio.coste_total) },
                {
                  label: "Plusvalía no realizada",
                  value: formatMoney(portfolio.pnl_no_realizado, { signDisplay: "always" }),
                  tone: pnlTotal >= 0 ? "positive" : "negative",
                },
                {
                  label: "Plusvalía realizada",
                  value: formatMoney(portfolio.pnl_realizado, { signDisplay: "always" }),
                  tone: toNumber(portfolio.pnl_realizado) >= 0 ? "positive" : "negative",
                },
                { label: "Dividendos", value: formatMoney(portfolio.dividendos) },
                { label: "Comisiones", value: formatMoney(portfolio.comisiones) },
              ].map((row) => (
                <div key={row.label} className="flex items-center justify-between gap-3 py-1.5">
                  <dt className="text-[11px] text-muted-foreground">{row.label}</dt>
                  <dd
                    className={cn(
                      "num text-[11px] font-medium",
                      row.tone === "positive" && "text-positive",
                      row.tone === "negative" && "text-negative",
                    )}
                  >
                    {row.value}
                  </dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>

        <Card className="xl:col-span-4">
          <CardHeader className="py-3">
            <div>
              <CardTitle>Cobertura de datos</CardTitle>
              <CardDescription>Qué falta para cuadrar la cartera</CardDescription>
            </div>
            <AlertTriangle
              className={cn(
                "size-4",
                hasWarnings ? "text-warning" : "text-positive",
              )}
              aria-hidden
            />
          </CardHeader>
          <CardContent className="space-y-2 pt-0 text-[11px] leading-5">
            <div className="flex items-center justify-between gap-2 border-b border-border pb-1.5">
              <span className="text-muted-foreground">Posiciones visibles</span>
              <span className="num font-medium">{visiblePositions.length}</span>
            </div>
            <div className="flex items-center justify-between gap-2 border-b border-border pb-1.5">
              <span className="text-muted-foreground">Datos incompletos</span>
              <span className="num font-medium text-warning">{incomplete.length}</span>
            </div>
            <div className="flex items-center justify-between gap-2 border-b border-border pb-1.5">
              <span className="text-muted-foreground">Posiciones negativas</span>
              <span className="num font-medium text-warning">
                {negativeCount}
              </span>
            </div>
            <div className="flex items-start justify-between gap-2 border-b border-border pb-1.5">
              <span className="text-muted-foreground">Posiciones de apertura</span>
              <Badge variant={portfolio.avisos.some((w) => w.includes("apertura")) ? "warning" : "positive"}>
                {portfolio.avisos.some((w) => w.includes("apertura")) ? "Faltan" : "Completas"}
              </Badge>
            </div>
            <p className="pt-1 text-[10px] leading-4 text-muted-foreground">
              El FIFO y las posiciones de apertura se calcularán en el backend v2 a
              partir de <span className="num">asset_transactions</span> y{" "}
              <span className="num">position_snapshots</span>. Esta pantalla no oculta
              las cantidades negativas del aviso, pero no las mezcla con el total.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
