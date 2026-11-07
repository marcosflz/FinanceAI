"use client";

import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import type { PortfolioSummary } from "@/lib/types";
import { formatMoney, formatPercent, toNumber } from "@/lib/utils";

const classColors: Record<string, string> = {
  etf: "#6366f1",
  ETFs: "#6366f1",
  cripto: "#f59e0b",
  Cripto: "#f59e0b",
  stock: "#0f766e",
  Acciones: "#0f766e",
  fondo: "#0ea5e9",
  Fondos: "#0ea5e9",
  otro: "#94a3b8",
  Otros: "#94a3b8",
};

const classLabels: Record<string, string> = {
  etf: "ETFs",
  cripto: "Cripto",
  stock: "Acciones",
  fondo: "Fondos",
  otro: "Otros",
};

export function AllocationChart({ summary }: { summary: PortfolioSummary }) {
  const total = toNumber(summary.valor_total);
  const data = summary.asignacion.map((item) => ({
    ...item,
    label: classLabels[item.label.toLowerCase()] ?? item.label,
    value: toNumber(item.value),
    color:
      classColors[item.label] ??
      classColors[item.label.toLowerCase()] ??
      "#64748b",
  }));

  return (
    <div>
      <div className="relative h-[190px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="label"
              innerRadius={58}
              outerRadius={82}
              paddingAngle={2}
              strokeWidth={0}
              isAnimationActive={false}
            >
              {data.map((entry) => (
                <Cell key={entry.label} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 10,
                fontSize: 11,
                color: "var(--popover-foreground)",
              }}
              formatter={(value) => formatMoney(Number(value))}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="num text-[16px] font-semibold leading-5">
            {formatMoney(total, { compact: true })}
          </span>
          <span className="text-[9px] uppercase tracking-[0.1em] text-muted-foreground">
            valor
          </span>
        </div>
      </div>

      <div className="mt-1 space-y-1.5">
        {summary.asignacion.map((item) => (
          <div key={item.label} className="flex items-center gap-2 text-[11px]">
            <span
              className="size-2 rounded-[3px]"
              style={{
              backgroundColor:
                classColors[item.label] ??
                classColors[item.label.toLowerCase()] ??
                "#64748b",
            }}
              aria-hidden
            />
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{classLabels[item.label.toLowerCase()] ?? item.label}</span>
            <span className="num text-[10px] text-muted-foreground">
              {formatPercent(item.peso)}
            </span>
            <span className="num w-20 text-right font-medium">{formatMoney(item.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
