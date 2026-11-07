"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Copy,
  Landmark,
  ListChecks,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { accountsApi, analyticsApi } from "@/lib/api";
import { withMock } from "@/lib/demo";
import { useAuth } from "@/lib/auth";
import {
  mockAccounts,
  mockAnalytics,
  mockCashflow,
  mockCategoryBreakdown,
  mockDataHealth,
} from "@/lib/mock";
import type { Account, CashflowGranularity, DataHealth } from "@/lib/types";
import {
  formatDate,
  formatMoney,
  formatPercent,
  relativeDate,
  toNumber,
} from "@/lib/utils";
import { PageHeader } from "@/components/ui/page-header";
import { Segmented } from "@/components/ui/segmented";
import { Card, CardContent, CardFooter, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ErrorState, PageSkeleton, Progress } from "@/components/ui/feedback";
import { PeriodPicker } from "@/components/dashboard/period-picker";
import {
  CashflowChart,
  type CashflowChartMode,
} from "@/components/dashboard/cashflow-chart";
import { cn } from "@/lib/utils";

const buttonLink =
  "inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[12px] font-medium transition-colors";
const secondaryLink = `${buttonLink} border border-border bg-card text-foreground hover:bg-muted`;

const cashflowChartModes: Array<{
  value: CashflowChartMode;
  label: string;
  hasNet: boolean;
}> = [
  { value: "grouped", label: "Barras comparadas", hasNet: true },
  { value: "flow", label: "Dirección del flujo", hasNet: false },
  { value: "area", label: "Áreas y neto", hasNet: true },
];

type PeriodValue =
  | "all"
  | "current_month"
  | "previous_month"
  | "last_3_months"
  | "last_12_months"
  | "current_year"
  | "previous_year"
  | "custom";

const periodPresets: Array<{ value: Exclude<PeriodValue, "custom">; label: string }> = [
  { value: "all", label: "Todo el histórico" },
  { value: "current_month", label: "Este mes" },
  { value: "previous_month", label: "Mes anterior" },
  { value: "last_3_months", label: "Últimos 3 meses" },
  { value: "last_12_months", label: "Últimos 12 meses" },
  { value: "current_year", label: "Este año" },
  { value: "previous_year", label: "Año anterior" },
];

interface PeriodSelection {
  desde?: string;
  hasta?: string;
  label: string;
}

function isoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function rangeForPeriod(
  value: PeriodValue,
  customFrom: string,
  customTo: string,
): PeriodSelection {
  if (value === "all") return { label: "Todo el histórico" };
  if (value === "custom") {
    return {
      desde: customFrom || undefined,
      hasta: customTo || undefined,
      label: customRangeLabel(customFrom, customTo),
    };
  }
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  const firstOfMonth = new Date(year, month, 1);
  const lastOfMonth = new Date(year, month + 1, 0);
  if (value === "current_month") {
    return {
      desde: isoDate(firstOfMonth),
      hasta: isoDate(lastOfMonth),
      label: monthYearLabel(year, month),
    };
  }
  if (value === "previous_month") {
    const previous = new Date(year, month - 1, 1);
    return {
      desde: isoDate(previous),
      hasta: isoDate(new Date(year, month, 0)),
      label: monthYearLabel(previous.getFullYear(), previous.getMonth()),
    };
  }
  if (value === "last_3_months") {
    return {
      desde: isoDate(new Date(year, month - 2, 1)),
      hasta: isoDate(lastOfMonth),
      label: "Últimos 3 meses",
    };
  }
  if (value === "last_12_months") {
    return {
      desde: isoDate(new Date(year, month - 11, 1)),
      hasta: isoDate(lastOfMonth),
      label: "Últimos 12 meses",
    };
  }
  if (value === "current_year") {
    return {
      desde: isoDate(new Date(year, 0, 1)),
      hasta: isoDate(lastOfMonth),
      label: String(year),
    };
  }
  if (value === "previous_year") {
    return {
      desde: isoDate(new Date(year - 1, 0, 1)),
      hasta: isoDate(new Date(year - 1, 11, 31)),
      label: String(year - 1),
    };
  }
  return {
    desde: customFrom || undefined,
    hasta: customTo || undefined,
    label: customRangeLabel(customFrom, customTo),
  };
}

function monthYearLabel(year: number, monthIndex: number): string {
  return new Intl.DateTimeFormat("es-ES", {
    month: "long",
    year: "numeric",
  }).format(new Date(year, monthIndex, 1));
}

function customRangeLabel(from: string, to: string): string {
  if (!from || !to) return "Personalizado";
  const start = new Date(`${from}T00:00:00`);
  const end = new Date(`${to}T00:00:00`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return "Personalizado";
  }
  const sameMonth =
    start.getFullYear() === end.getFullYear() &&
    start.getMonth() === end.getMonth();
  const lastDayOfMonth = new Date(
    start.getFullYear(),
    start.getMonth() + 1,
    0,
  ).getDate();
  if (sameMonth && start.getDate() === 1 && end.getDate() === lastDayOfMonth) {
    return monthYearLabel(start.getFullYear(), start.getMonth());
  }
  const days = daysBetween(from, to);
  if (start.getDay() === 1 && end.getDay() === 0 && days === 7) {
    return `Semana del ${formatDate(start, "day")} ${start.getFullYear()}`;
  }
  return `${formatDate(from, "short")} – ${formatDate(to, "short")}`;
}

function daysBetween(start: string, end: string): number | null {
  if (!start || !end) return null;
  const from = new Date(`${start}T00:00:00`);
  const to = new Date(`${end}T00:00:00`);
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return null;
  return Math.round(Math.abs(to.getTime() - from.getTime()) / 86_400_000) + 1;
}

function defaultGranularityForSpan(days: number | null): CashflowGranularity {
  if (days === null) return "month";
  if (days <= 31) return "day";
  if (days <= 120) return "week";
  if (days <= 365 * 5) return "month";
  return "year";
}

function granularitiesForSpan(days: number | null): CashflowGranularity[] {
  const allowed: CashflowGranularity[] = [];
  if (days !== null && days <= 400) allowed.push("day");
  if (days !== null && days > 7 && days <= 400) allowed.push("week");
  if (days === null || days > 31) allowed.push("month");
  if (days === null || days > 366) allowed.push("year");
  return allowed;
}

function resolveGranularity(
  current: CashflowGranularity,
  days: number | null,
): CashflowGranularity {
  const allowed = granularitiesForSpan(days);
  if (allowed.includes(current)) return current;
  const fallback = defaultGranularityForSpan(days);
  if (allowed.includes(fallback)) return fallback;
  return allowed[0] ?? fallback;
}

const granularityLabels: Record<CashflowGranularity, string> = {
  day: "Día",
  week: "Semana",
  month: "Mes",
  year: "Año",
};

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "positive" | "negative" | "neutral";
}) {
  return (
    <div>
      <p className="text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          "num mt-1 text-[17px] font-medium leading-6",
          tone === "positive" && "text-positive",
          tone === "negative" && "text-negative",
        )}
      >
        {value}
      </p>
      {hint ? <p className="mt-0.5 text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function ReviewRow({
  href,
  label,
  count,
  icon: Icon,
  tone,
}: {
  href: string;
  label: string;
  count: number;
  icon: LucideIcon;
  tone: "warning" | "negative" | "accent" | "neutral";
}) {
  const toneClasses = {
    warning: "bg-warning-soft text-warning",
    negative: "bg-negative-soft text-negative",
    accent: "bg-accent-soft text-accent",
    neutral: "bg-muted text-muted-foreground",
  } as const;

  return (
    <Link
      href={href}
      className="group flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-muted"
    >
      <span
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-md",
          toneClasses[tone],
        )}
      >
        <Icon className="size-3.5" aria-hidden />
      </span>
      <span className="min-w-0 flex-1 text-[12px] font-medium text-foreground">{label}</span>
      <span className="num text-[13px] font-semibold text-foreground">{count}</span>
      <ArrowRight
        className="size-3 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
        aria-hidden
      />
    </Link>
  );
}

function AccountRow({ account }: { account: Account }) {
  const difference = toNumber(account.reconciliacion_diferencia);
  return (
    <div className="flex items-center gap-2.5 py-1.5">
      <span
        className="size-2 shrink-0 rounded-full"
        style={{ backgroundColor: account.color }}
        aria-hidden
      />
      <span className="min-w-0 flex-1 truncate text-[12px] text-muted-foreground">
        {account.nombre}
      </span>
      {difference !== 0 && account.reconciliacion_diferencia !== null ? (
        <span title="Diferencia de conciliación">
          <AlertTriangle className="size-3 text-warning" aria-hidden />
        </span>
      ) : null}
      <span className="num text-[12px] font-medium text-foreground">
        {formatMoney(account.balance)}
      </span>
    </div>
  );
}

function HealthRow({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "positive" | "warning" | "negative";
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span
        className={cn(
          "num text-right text-[11px] font-medium",
          tone === "positive" && "text-positive",
          tone === "warning" && "text-warning",
          tone === "negative" && "text-negative",
          tone === "neutral" && "text-foreground",
        )}
      >
        {value}
      </span>
    </div>
  );
}

export function DashboardView() {
  const { user } = useAuth();
  const [periodValue, setPeriodValue] = useState<PeriodValue>("all");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const period = rangeForPeriod(periodValue, customFrom, customTo);
  const periodKey = `${period.desde ?? "all"}:${period.hasta ?? "all"}`;
  const periodDays =
    period.desde && period.hasta
      ? daysBetween(period.desde, period.hasta)
      : null;
  const periodGranularities = granularitiesForSpan(periodDays);
  const [chartGranularity, setChartGranularity] = useState<CashflowGranularity>("month");
  const [chartModeIndex, setChartModeIndex] = useState(0);
  const chartGranularityValue = resolveGranularity(chartGranularity, periodDays);
  const chartMode = cashflowChartModes[chartModeIndex];
  const chartKey = `${periodKey}:${chartGranularityValue}`;

  function applyCustomPeriod(nextFrom: string, nextTo: string) {
    if (!nextFrom || !nextTo) return;
    const days = daysBetween(nextFrom, nextTo);
    setCustomFrom(nextFrom);
    setCustomTo(nextTo);
    setPeriodValue("custom");
    setChartGranularity((current) => resolveGranularity(current, days));
  }

  function handlePeriodChange(next: Exclude<PeriodValue, "custom">) {
    const nextPeriod = rangeForPeriod(next, customFrom, customTo);
    const nextDays =
      nextPeriod.desde && nextPeriod.hasta
        ? daysBetween(nextPeriod.desde, nextPeriod.hasta)
        : null;
    setPeriodValue(next);
    setChartGranularity((current) => resolveGranularity(current, nextDays));
  }


  const summaryQuery = useQuery({
    queryKey: ["analytics", "summary", periodKey],
    queryFn: () =>
      withMock(
        () => analyticsApi.summary({ desde: period.desde, hasta: period.hasta }),
        mockAnalytics,
      ),
  });
  const cashflowQuery = useQuery({
    queryKey: ["analytics", "cashflow", chartKey],
    queryFn: () =>
      withMock(
        () =>
          analyticsApi
            .cashflow(12, {
              desde: period.desde,
              hasta: period.hasta,
              granularity: chartGranularityValue,
              all: !period.desde && !period.hasta,
            })
            .then((response) => response.items),
        mockCashflow,
      ),
  });
  const categoriesQuery = useQuery({
    queryKey: ["analytics", "by-category", periodKey],
    queryFn: () =>
      withMock(
        () =>
          analyticsApi
            .byCategory({ desde: period.desde, hasta: period.hasta })
            .then((response) => response.items),
        mockCategoryBreakdown,
      ),
  });
  const healthQuery = useQuery({
    queryKey: ["analytics", "data-health"],
    queryFn: () => withMock(() => analyticsApi.dataHealth(), mockDataHealth),
  });
  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => withMock(() => accountsApi.list(), { items: mockAccounts }),
  });

  const isLoading =
    summaryQuery.isLoading ||
    cashflowQuery.isLoading ||
    categoriesQuery.isLoading ||
    healthQuery.isLoading ||
    accountsQuery.isLoading;

  const firstError =
    summaryQuery.error ?? cashflowQuery.error ?? categoriesQuery.error ?? healthQuery.error;

  if (isLoading) return <PageSkeleton />;

  if (firstError) {
    return (
      <ErrorState
        title="No se pudo cargar el dashboard"
        description="La API v3 no respondió y no hay datos de respaldo disponibles."
        action={
          <button
            type="button"
            onClick={() => {
              void Promise.all([
                summaryQuery.refetch(),
                cashflowQuery.refetch(),
                categoriesQuery.refetch(),
                healthQuery.refetch(),
                accountsQuery.refetch(),
              ]);
            }}
            className={secondaryLink}
          >
            <RefreshCw className="size-3.5" aria-hidden />
            Reintentar
          </button>
        }
      />
    );
  }

  const summary = summaryQuery.data ?? mockAnalytics;
  const cashflow = cashflowQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];
  const health: DataHealth = healthQuery.data ?? mockDataHealth;
  const accounts = accountsQuery.data?.items ?? [];
  const firstName =
    (user?.name ?? user?.email?.split("@")[0] ?? "de nuevo").split(" ")[0];

  const netDelta =
    toNumber(summary.flujo_neto_prev) !== 0
      ? ((toNumber(summary.flujo_neto) - toNumber(summary.flujo_neto_prev)) /
          Math.abs(toNumber(summary.flujo_neto_prev))) *
        100
      : 0;
  const netPositive = toNumber(summary.flujo_neto) >= 0;
  const incomeTotal = toNumber(summary.ingresos);
  const expenseTotal = toNumber(summary.gastos);
  const flowBase = incomeTotal + expenseTotal;
  const incomeShare = flowBase > 0 ? (incomeTotal / flowBase) * 100 : 0;
  const expenseShare = flowBase > 0 ? (expenseTotal / flowBase) * 100 : 0;
  const reviewTotal =
    summary.pendientes + summary.sin_categoria + summary.duplicados + summary.transferencias_sugeridas;
  const maxCategory = Math.max(...categories.map((item) => toNumber(item.total)), 1);
  const accountsTotal = accounts.reduce((sum, account) => sum + toNumber(account.balance), 0);
  const chartGranularityLabel =
    chartGranularityValue === "day"
      ? "diario"
      : chartGranularityValue === "week"
        ? "semanal"
        : chartGranularityValue === "year"
          ? "anual"
          : "mensual";

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow={`Dashboard · ${period.label}`}
        title={`Hola, ${firstName}`}
        description="Flujo del periodo, patrimonio y estado de la clasificación. Todo lo que necesita tu atención, en una sola vista."
        actions={
          <>
            <PeriodPicker
              presets={periodPresets}
              value={periodValue}
              label={period.label}
              from={period.desde}
              to={period.hasta}
              onPreset={handlePeriodChange}
              onCustom={applyCustomPeriod}
            />
            <Link href="/movements?tab=por-revisar" className={secondaryLink}>
              <ListChecks className="size-3.5" aria-hidden />
              Revisar
              <span className="num rounded bg-warning-soft px-1 text-[10px] font-semibold text-warning">
                {reviewTotal}
              </span>
            </Link>
          </>
        }
      />

      <div className="grid gap-4 xl:grid-cols-12">
        <Card className="overflow-hidden xl:col-span-8">
          <CardContent className="p-5 sm:p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  Flujo neto · {period.label}
                </p>
                <p
                  className={cn(
                    "num mt-2 text-[34px] font-semibold leading-none tracking-[-0.03em] sm:text-[40px]",
                    netPositive ? "text-positive" : "text-negative",
                  )}
                >
                  {formatMoney(summary.flujo_neto, { signDisplay: "always" })}
                </p>
                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                  <Badge variant={netDelta >= 0 ? "positive" : "negative"}>
                    {netDelta >= 0 ? (
                      <ArrowUpRight className="size-3" aria-hidden />
                    ) : (
                      <span aria-hidden>↓</span>
                    )}
                    {formatPercent(Math.abs(netDelta), { signDisplay: "never" })}
                  </Badge>
                  <span className="text-[11px] text-muted-foreground">
                    frente a {formatMoney(summary.flujo_neto_prev)} el mes anterior
                  </span>
                </div>
              </div>
              <div className="hidden size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-muted text-muted-foreground sm:flex">
                <TrendingUp className="size-5" aria-hidden />
              </div>
            </div>

            <div className="mt-6 grid grid-cols-2 gap-4 border-t border-border pt-4 sm:grid-cols-4">
              <Metric
                label="Ingresos"
                value={formatMoney(summary.ingresos)}
                hint={`${formatMoney(toNumber(summary.ingresos) - toNumber(summary.ingresos_prev), {
                  signDisplay: "always",
                })} vs mes anterior`}
                tone="positive"
              />
              <Metric
                label="Gastos"
                value={formatMoney(summary.gastos)}
                hint={`${formatMoney(toNumber(summary.gastos) - toNumber(summary.gastos_prev), {
                  signDisplay: "always",
                })} vs mes anterior`}
                tone="negative"
              />
              <Metric
                label="Tasa de ahorro"
                value={formatPercent(toNumber(summary.tasa_ahorro) * 100)}
                hint="Objetivo 30 %"
              />
              <Metric
                label="Aportes netos"
                value={formatMoney(
                  summary.transferencias_netas ?? summary.aportes_netos ?? 0,
                  { signDisplay: "always" },
                )}
                hint="Transferencias e inversiones excluidas"
              />
            </div>

            <div className="mt-5">
              <div className="flex items-center justify-between gap-3 text-[10px]">
                <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                  <span className="size-1.5 rounded-full bg-positive" aria-hidden />
                  Ingresos
                  <span className="num font-medium text-foreground">
                    {formatPercent(incomeShare)}
                  </span>
                </span>
                <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                  Gastos
                  <span className="num font-medium text-foreground">
                    {formatPercent(expenseShare)}
                  </span>
                  <span className="size-1.5 rounded-full bg-negative" aria-hidden />
                </span>
              </div>
              <div
                className="mt-1.5 flex h-2 w-full overflow-hidden rounded-full bg-muted"
                role="img"
                aria-label={`Reparto ingresos/gastos: ${formatPercent(incomeShare)} de ingresos y ${formatPercent(expenseShare)} de gastos`}
              >
                <div
                  className="h-full bg-positive transition-[width] duration-300"
                  style={{ width: `${incomeShare}%` }}
                />
                <div
                  className="h-full bg-negative transition-[width] duration-300"
                  style={{ width: `${expenseShare}%` }}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-4">
          <CardHeader>
            <div>
              <CardTitle>Saldo en cuentas</CardTitle>
              <CardDescription>Extractos importados + saldo inicial</CardDescription>
            </div>
            <Link
              href="/accounts"
              className="text-muted-foreground transition-colors hover:text-foreground"
              aria-label="Ver cuentas"
            >
              <ArrowUpRight className="size-4" aria-hidden />
            </Link>
          </CardHeader>
          <CardContent className="pt-3">
            <p className="num text-[26px] font-semibold leading-7 tracking-[-0.02em]">
              {formatMoney(summary.patrimonio_neto)}
            </p>
            <p className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="num text-positive">
                {formatMoney(
                  toNumber(summary.patrimonio_neto) - toNumber(summary.patrimonio_neto_prev),
                  { signDisplay: "always" },
                )}
              </span>
              desde el mes anterior
            </p>

            <div className="mt-4 space-y-0.5 border-t border-border pt-3">
              {accounts.slice(0, 4).map((account) => (
                <AccountRow key={account.id} account={account} />
              ))}
              {accounts.length === 0 ? (
                <p className="py-3 text-center text-[11px] text-muted-foreground">
                  Sin cuentas configuradas.
                </p>
              ) : null}
            </div>
            {accountsTotal > 0 ? (
              <p className="mt-2 border-t border-border pt-2 text-[10px] text-muted-foreground">
                Suma de cuentas:{" "}
                <span className="num text-foreground">{formatMoney(accountsTotal)}</span>
              </p>
            ) : null}
          </CardContent>
        </Card>

        <Card className="xl:col-span-4">
          <CardHeader>
            <div>
              <CardTitle>Por revisar</CardTitle>
              <CardDescription>Cola priorizada por incertidumbre</CardDescription>
            </div>
            <Badge variant={reviewTotal > 0 ? "warning" : "positive"}>
              {reviewTotal > 0 ? `${reviewTotal} pendientes` : "Al día"}
            </Badge>
          </CardHeader>
          <CardContent className="space-y-0.5 px-2.5 py-2">
            <ReviewRow
              href="/movements?tab=por-revisar"
              label="Pendientes de aprobar"
              count={summary.pendientes}
              icon={Clock3}
              tone="warning"
            />
            <ReviewRow
              href="/movements?tab=sin-categorizar"
              label="Sin categoría"
              count={summary.sin_categoria}
              icon={Sparkles}
              tone="negative"
            />
            <ReviewRow
              href="/movements?tab=duplicados"
              label="Duplicados candidatos"
              count={summary.duplicados}
              icon={Copy}
              tone="accent"
            />
            <ReviewRow
              href="/movements?tab=transferencias"
              label="Transferencias sugeridas"
              count={summary.transferencias_sugeridas}
              icon={Landmark}
              tone="neutral"
            />
          </CardContent>
          <CardFooter className="py-2.5">
            <Link
              href="/movements?tab=por-revisar"
              className="flex w-full items-center justify-between text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Abrir bandeja de revisión
              <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </CardFooter>
        </Card>

        <Card className="xl:col-span-8">
          <CardHeader className="flex-wrap gap-3">
            <div>
              <CardTitle>Flujo de caja</CardTitle>
              <CardDescription>
                {period.label} · Ingresos, gastos y neto {chartGranularityLabel}
              </CardDescription>
            </div>
            <div className="flex max-w-full flex-wrap items-center justify-end gap-2">
              <Segmented
                aria-label="Subdividir el gráfico de flujo de caja"
                value={chartGranularityValue}
                onChange={setChartGranularity}
                options={(Object.keys(granularityLabels) as CashflowGranularity[]).map(
                  (granularity) => ({
                    value: granularity,
                    label: granularityLabels[granularity],
                    disabled: !periodGranularities.includes(granularity),
                    title: periodGranularities.includes(granularity)
                      ? undefined
                      : "No disponible para este periodo",
                  }),
                )}
              />
            </div>
          </CardHeader>
          <CardContent className="px-3 pb-3 pt-1 sm:px-4">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <Segmented
                aria-label="Tipo de gráfico"
                value={String(chartModeIndex)}
                onChange={(next) => setChartModeIndex(Number(next))}
                options={cashflowChartModes.map((mode, index) => ({
                  value: String(index),
                  label: mode.label,
                }))}
              />
              <div className="flex flex-wrap items-center justify-end gap-3 text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="size-1.5 rounded-full bg-positive" aria-hidden /> Ingresos
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="size-1.5 rounded-full bg-negative" aria-hidden /> Gastos
                </span>
                {chartMode.hasNet ? (
                  <span className="flex items-center gap-1.5">
                    <span className="h-0.5 w-3 rounded bg-accent" aria-hidden /> Neto
                  </span>
                ) : (
                  <span className="hidden sm:inline">
                    Verde arriba · rojo abajo
                  </span>
                )}
              </div>
            </div>
            {cashflow.length > 0 ? (
              <CashflowChart
                data={cashflow}
                granularity={chartGranularityValue}
                mode={chartMode.value}
              />
            ) : (
              <div className="flex h-[248px] items-center justify-center text-[12px] text-muted-foreground">
                No hay datos en el periodo seleccionado.
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="xl:col-span-7">
          <CardHeader>
            <div>
              <CardTitle>Desglose por categoría</CardTitle>
              <CardDescription>{period.label} · gasto e ingreso</CardDescription>
            </div>
            <Link
              href="/movements"
              className="text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Ver movimientos
            </Link>
          </CardHeader>
          <CardContent className="space-y-3 pt-3">
            {categories.slice(0, 7).map((category) => {
              const total = toNumber(category.total);
              const delta = category.delta_pct;
              return (
                <Link
                  key={category.categoria_id}
                  href={`/movements?categoria_id=${category.categoria_id}`}
                  className="group block"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex min-w-0 items-center gap-2">
                      <span
                        className="size-2 shrink-0 rounded-[3px]"
                        style={{ backgroundColor: category.color }}
                        aria-hidden
                      />
                      <span className="truncate text-[12px] font-medium text-foreground">
                        {category.categoria}
                      </span>
                      <span className="hidden text-[10px] text-muted-foreground sm:inline">
                        {category.movimientos} mov.
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="num text-[12px] font-medium">{formatMoney(total)}</span>
                      <Badge
                        variant={
                          delta === 0 ? "neutral" : delta > 0 ? "negative" : "positive"
                        }
                        className="tabular w-14 justify-center"
                      >
                        {delta === 0
                          ? "0 %"
                          : formatPercent(delta, {
                              signDisplay: "always",
                              fractionDigits: 1,
                            })}
                      </Badge>
                    </span>
                  </div>
                  <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full transition-all group-hover:opacity-80"
                      style={{
                        width: `${Math.max(2, (total / maxCategory) * 100)}%`,
                        backgroundColor: category.color,
                      }}
                    />
                  </div>
                </Link>
              );
            })}
            {categories.length === 0 ? (
              <p className="py-8 text-center text-[12px] text-muted-foreground">
                Sin gastos clasificados este mes.
              </p>
            ) : null}
          </CardContent>
        </Card>

        <Card className="xl:col-span-5">
          <CardHeader>
            <div>
              <CardTitle>Salud de datos</CardTitle>
              <CardDescription>Calidad de la clasificación y conciliación</CardDescription>
            </div>
            <Badge variant={health.negative_positions > 0 ? "warning" : "positive"} dot>
              {health.negative_positions > 0 ? "Revisar" : "Estable"}
            </Badge>
          </CardHeader>
          <CardContent className="pt-3">
            <div className="flex items-end justify-between gap-3">
              <div>
                <p className="text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
                  Auto-clasificado
                </p>
                <p className="num mt-1 text-[24px] font-semibold leading-6">
                  {formatPercent(health.auto_classified_pct)}
                </p>
              </div>
              <p className="text-right text-[10px] leading-4 text-muted-foreground">
                {health.corrections_last_week} correcciones
                <br />
                en los últimos 7 días
              </p>
            </div>
            <Progress
              className="mt-3"
              value={health.auto_classified_pct}
              tone={health.auto_classified_pct >= 85 ? "positive" : "warning"}
              label="Porcentaje auto-clasificado"
            />

            <div className="mt-4 divide-y divide-border border-t border-border">
              <HealthRow
                label="Última importación"
                value={
                  health.last_import_at
                    ? relativeDate(health.last_import_at)
                    : "Sin importaciones"
                }
                tone={health.last_import_at ? "neutral" : "warning"}
              />
              <HealthRow
                label="Cuentas sin conciliar"
                value={`${health.accounts_unreconciled} / ${health.accounts_total}`}
                tone={health.accounts_unreconciled > 0 ? "warning" : "positive"}
              />
              <HealthRow
                label="Pendientes obsoletos"
                value={String(health.stale_movements_without_classification)}
                tone={health.stale_movements_without_classification > 0 ? "warning" : "neutral"}
              />
              <HealthRow
                label="Posiciones negativas"
                value={String(health.negative_positions)}
                tone={health.negative_positions > 0 ? "negative" : "positive"}
              />
            </div>

            {health.last_import_filename ? (
              <p className="mt-3 truncate rounded-md bg-muted px-2 py-1.5 text-[10px] text-muted-foreground">
                {health.last_import_filename} ·{" "}
                {formatDate(health.last_import_at, "medium")}
              </p>
            ) : null}

            {health.missing_opening_positions ? (
              <p className="mt-2 flex items-start gap-1.5 rounded-md bg-warning-soft px-2 py-1.5 text-[10px] leading-4 text-warning">
                <ShieldAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
                Faltan posiciones de apertura: el P&amp;L histórico puede estar incompleto.
              </p>
            ) : null}
          </CardContent>
          <CardFooter className="py-2.5">
            <Link
              href="/settings?section=datos"
              className="flex w-full items-center justify-between text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Revisar datos y copias
              <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </CardFooter>
        </Card>
      </div>

      <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2.5 text-[11px] text-muted-foreground">
        <CheckCircle2 className="size-3.5 shrink-0 text-positive" aria-hidden />
        <span>
          Los importes excluyen transferencias internas y operaciones de inversión según la
          configuración de categorías.
        </span>
        <Wallet className="ml-auto hidden size-3.5 shrink-0 sm:block" aria-hidden />
      </div>
    </div>
  );
}
