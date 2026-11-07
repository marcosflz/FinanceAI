"use client";

import { useId } from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CashflowGranularity, CashflowPoint } from "@/lib/types";
import { formatDate, formatMoney, toNumber } from "@/lib/utils";

export type CashflowChartMode = "grouped" | "flow" | "area";

function labelForPeriod(period: string, granularity: CashflowGranularity): string {
  if (granularity === "year") return period;
  if (granularity === "month") return formatDate(`${period}-01`, "month");
  if (granularity === "week") return `sem ${formatDate(period, "day")}`;
  return formatDate(period, "day");
}

function tooltipValue(value: unknown, name: unknown): [string, string] {
  const numeric = Number(value ?? 0);
  const key = String(name ?? "");
  if (key === "gastos") return [formatMoney(Math.abs(numeric)), "Gastos"];
  if (key === "ingresos") return [formatMoney(numeric), "Ingresos"];
  return [formatMoney(numeric), "Neto"];
}

export function CashflowChart({
  data,
  granularity = "month",
  mode = "grouped",
}: {
  data: CashflowPoint[];
  granularity?: CashflowGranularity;
  mode?: CashflowChartMode;
}) {
  const gradientPrefix = useId().replace(/:/g, "");
  const isDiverging = mode !== "grouped";
  const chartData = data.map((point) => {
    const gastos = toNumber(point.gastos);
    return {
      ...point,
      label: labelForPeriod(point.month, granularity),
      ingresos: toNumber(point.ingresos),
      gastos: isDiverging ? -gastos : gastos,
      neto: toNumber(point.neto),
    };
  });
  const barSize =
    chartData.length > 120
      ? 1
      : chartData.length > 40
        ? 3
        : chartData.length > 24
          ? 6
          : 9;
  const barGap = chartData.length > 120 ? 0 : 2;
  const periodLabel =
    granularity === "day"
      ? "diario"
      : granularity === "week"
        ? "semanal"
        : granularity === "year"
          ? "anual"
          : "mensual";
  const chartLabel =
    mode === "flow"
      ? "Flujo por dirección"
      : mode === "area"
        ? "Áreas y neto"
        : "Barras comparadas";
  const ariaLabel = `${chartLabel}, flujo de caja ${periodLabel}`;

  return (
    <div className="h-[248px] w-full" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={chartData}
          barGap={barGap}
          stackOffset="sign"
          margin={{ top: 8, right: 4, bottom: 0, left: 0 }}
        >
          <defs>
            <linearGradient id={`${gradientPrefix}-income`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--positive)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--positive)" stopOpacity={0.02} />
            </linearGradient>
            <linearGradient id={`${gradientPrefix}-expense`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--negative)" stopOpacity={0.02} />
              <stop offset="100%" stopColor="var(--negative)" stopOpacity={0.35} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} strokeDasharray="2 4" />
          <XAxis
            dataKey="label"
            axisLine={false}
            tickLine={false}
            tick={{ fill: "var(--muted-foreground)", fontSize: 9 }}
            interval="preserveStartEnd"
            minTickGap={16}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            width={38}
            tick={{ fill: "var(--muted-foreground)", fontSize: 9 }}
            tickFormatter={(value: number) => `${Math.round(value / 1000)}k`}
          />
          <Tooltip
            cursor={{ fill: "var(--muted)", opacity: 0.5 }}
            contentStyle={{
              background: "var(--popover)",
              border: "1px solid var(--border)",
              borderRadius: 10,
              fontSize: 11,
              color: "var(--popover-foreground)",
              boxShadow: "0 8px 24px rgb(0 0 0 / 0.12)",
            }}
            labelStyle={{ color: "var(--muted-foreground)", marginBottom: 4 }}
            formatter={tooltipValue}
          />

          {mode === "grouped" ? (
            <>
              <Bar
                dataKey="ingresos"
                fill="var(--positive)"
                radius={[2, 2, 0, 0]}
                barSize={barSize}
              />
              <Bar
                dataKey="gastos"
                fill="var(--negative)"
                radius={[2, 2, 0, 0]}
                barSize={barSize}
              />
              <Line
                type="linear"
                dataKey="neto"
                stroke="var(--accent)"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 3, strokeWidth: 0 }}
              />
            </>
          ) : null}

          {mode === "flow" ? (
            <>
              <ReferenceLine y={0} stroke="var(--border)" />
              <Bar
                dataKey="ingresos"
                fill="var(--positive)"
                radius={[3, 3, 0, 0]}
                barSize={barSize}
                stackId="flow"
              />
              <Bar
                dataKey="gastos"
                fill="var(--negative)"
                radius={[0, 0, 3, 3]}
                barSize={barSize}
                stackId="flow"
              />
            </>
          ) : null}

          {mode === "area" ? (
            <>
              <ReferenceLine y={0} stroke="var(--border)" />
              <Area
                type="linear"
                dataKey="ingresos"
                stroke="var(--positive)"
                strokeWidth={1.5}
                fill={`url(#${gradientPrefix}-income)`}
                fillOpacity={1}
                baseValue={0}
                activeDot={{ r: 3, strokeWidth: 0 }}
              />
              <Area
                type="linear"
                dataKey="gastos"
                stroke="var(--negative)"
                strokeWidth={1.5}
                fill={`url(#${gradientPrefix}-expense)`}
                fillOpacity={1}
                baseValue={0}
                activeDot={{ r: 3, strokeWidth: 0 }}
              />
              <Line
                type="linear"
                dataKey="neto"
                stroke="var(--accent)"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 3, strokeWidth: 0 }}
              />
            </>
          ) : null}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
