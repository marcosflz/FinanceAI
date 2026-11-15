"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSeries } from "@/lib/agent-types";
import { formatMoney } from "@/lib/utils";

const PALETTE = ["var(--accent)", "var(--positive)", "var(--warning)", "var(--negative)", "#0ea5e9", "#a855f7"];

export interface ChartSpec {
  title: string;
  kind: "bar" | "line" | "pie";
  labels: string[];
  series: ChartSeries[];
}

export function isChartSpec(value: unknown): value is ChartSpec {
  if (!value || typeof value !== "object") return false;
  const spec = value as Partial<ChartSpec>;
  return (
    typeof spec.title === "string" &&
    Array.isArray(spec.labels) &&
    Array.isArray(spec.series) &&
    ["bar", "line", "pie"].includes(String(spec.kind))
  );
}

function money(value: unknown): string {
  return formatMoney(Number(value ?? 0));
}

/** Widget de gráfico que el asistente pinta con ``show_chart``. */
export function ChartWidget({ spec }: { spec: ChartSpec }) {
  const rows = spec.labels.map((label, index) => {
    const row: Record<string, string | number> = { label };
    for (const serie of spec.series) row[serie.name] = Number(serie.values[index] ?? 0);
    return row;
  });

  return (
    <figure className="rounded-xl border border-border bg-card p-3">
      <figcaption className="mb-2 text-[12px] font-medium">{spec.title}</figcaption>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {spec.kind === "pie" ? (
            <PieChart>
              <Pie
                data={rows}
                dataKey={spec.series[0]?.name ?? "value"}
                nameKey="label"
                innerRadius="45%"
                outerRadius="80%"
              >
                {rows.map((row, index) => (
                  <Cell key={String(row.label)} fill={PALETTE[index % PALETTE.length]} />
                ))}
              </Pie>
              <Tooltip formatter={money} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          ) : spec.kind === "line" ? (
            <LineChart data={rows}>
              <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} width={56} />
              <Tooltip formatter={money} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {spec.series.map((serie, index) => (
                <Line
                  key={serie.name}
                  type="monotone"
                  dataKey={serie.name}
                  stroke={PALETTE[index % PALETTE.length]}
                  strokeWidth={2}
                  dot={false}
                />
              ))}
            </LineChart>
          ) : (
            <BarChart data={rows}>
              <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} width={56} />
              <Tooltip formatter={money} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {spec.series.map((serie, index) => (
                <Bar
                  key={serie.name}
                  dataKey={serie.name}
                  fill={PALETTE[index % PALETTE.length]}
                  radius={[3, 3, 0, 0]}
                />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
