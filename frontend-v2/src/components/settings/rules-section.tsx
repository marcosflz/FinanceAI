"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  FlaskConical,
  Play,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Zap,
} from "lucide-react";
import { rulesApi } from "@/lib/api";
import { withMock } from "@/lib/demo";
import { mockRules } from "@/lib/mock";
import type { ClassificationRule } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Switch } from "@/components/ui/form";
import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { formatDateTime, relativeDate } from "@/lib/utils";

export function RulesSection() {
  const { toast } = useToast();
  const [search, setSearch] = useState("");
  const [activeOverrides, setActiveOverrides] = useState<Record<number, boolean>>({});
  const [dryRunning, setDryRunning] = useState<number | null>(null);

  const rulesQuery = useQuery({
    queryKey: ["classification-rules"],
    queryFn: () => withMock(() => rulesApi.list(), { items: mockRules }),
  });
  const rules = useMemo(() => rulesQuery.data?.items ?? [], [rulesQuery.data?.items]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return rules;
    return rules.filter((rule) =>
      [rule.nombre, rule.descripcion, rule.valor, rule.set_categoria, rule.campo]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [rules, search]);

  const activeCount = rules.filter(
    (rule) => activeOverrides[rule.id] ?? rule.activa,
  ).length;
  const autoCount = rules.filter(
    (rule) => (activeOverrides[rule.id] ?? rule.activa) && rule.auto_aprobar,
  ).length;
  const hits = rules.reduce((sum, rule) => sum + rule.hit_count, 0);

  async function dryRun(rule: ClassificationRule) {
    setDryRunning(rule.id);
    await new Promise((resolve) => setTimeout(resolve, 500));
    setDryRunning(null);
    toast({
      title: `Dry-run: ${rule.nombre ?? `Regla #${rule.id}`}`,
      description:
        "Scaffold F5: se conectará a GET /api/v3/classify/preview. No se ha modificado ningún movimiento.",
      variant: "success",
    });
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Reglas", value: String(rules.length) },
          { label: "Activas", value: String(activeCount) },
          { label: "Auto-aprueban", value: String(autoCount) },
          { label: "Hits acumulados", value: String(hits) },
        ].map((stat) => (
          <div key={stat.label} className="card px-4 py-3">
            <p className="text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
              {stat.label}
            </p>
            <p className="num mt-1 text-[20px] font-semibold leading-6">{stat.value}</p>
          </div>
        ))}
      </div>

      <Card className="overflow-hidden">
        <CardHeader className="py-3">
          <div>
            <CardTitle>Reglas de clasificación</CardTitle>
            <CardDescription>
              Se evalúan antes de la memoria y del decisor. Prioridad menor = antes.
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              onClick={() => void rulesQuery.refetch()}
              loading={rulesQuery.isFetching}
              aria-label="Recargar reglas"
            >
              <RefreshCw className="size-3.5" aria-hidden />
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() =>
                toast({
                  title: "Autolearn",
                  description:
                    "Scaffold: se conectará a GET/POST /api/v2/classification-rules/autolearn con preview y consistencia por comercio.",
                })
              }
            >
              <Sparkles className="size-3.5" aria-hidden />
              Autolearn
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() =>
                toast({
                  title: "Nueva regla",
                  description: "Scaffold: editor de reglas pendiente de contrato API.",
                })
              }
            >
              <Plus className="size-3.5" aria-hidden />
              Nueva regla
            </Button>
          </div>
        </CardHeader>

        <div className="flex flex-wrap items-center justify-between gap-2 border-y border-border bg-subtle px-3 py-2">
          <div className="relative w-full sm:w-64">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Filtrar reglas…"
              aria-label="Filtrar reglas"
              className="h-8 pl-8 text-[11px]"
            />
          </div>
          <p className="inline-flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <Zap className="size-3 text-accent" aria-hidden />
            Dry-run antes de activar una regla nueva
          </p>
        </div>

        {rulesQuery.isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-9 w-full" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            title="Sin reglas"
            description="Crea una regla o ejecuta Autolearn sobre el histórico aprobado."
            icon={<FlaskConical className="size-4" aria-hidden />}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse text-left">
              <thead>
                <tr className="border-b border-border text-[10px] font-medium uppercase tracking-[0.06em] text-muted-foreground">
                  <th className="px-3 py-2">Regla</th>
                  <th className="px-2 py-2">Patrón</th>
                  <th className="px-2 py-2">Categoría</th>
                  <th className="px-2 py-2 text-right">Prioridad</th>
                  <th className="px-2 py-2 text-right">Hits</th>
                  <th className="hidden px-2 py-2 lg:table-cell">Última</th>
                  <th className="px-2 py-2">Modo</th>
                  <th className="px-2 py-2 text-right">Activa</th>
                  <th className="w-10 px-2 py-2" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((rule) => {
                  const active = activeOverrides[rule.id] ?? rule.activa;
                  return (
                    <tr
                      key={rule.id}
                      className="border-b border-border/70 text-[11px] transition-colors hover:bg-muted/40"
                    >
                      <td className="px-3 py-2">
                        <p className="max-w-[190px] truncate font-medium text-foreground">
                          {rule.nombre ?? `Regla #${rule.id}`}
                        </p>
                        <p className="max-w-[190px] truncate text-[10px] text-muted-foreground">
                          {rule.descripcion ?? rule.campo}
                        </p>
                      </td>
                      <td className="px-2 py-2">
                        <code className="num rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          {rule.campo} {rule.operador} {rule.valor}
                        </code>
                      </td>
                      <td className="px-2 py-2 text-[11px]">
                        {rule.set_categoria ?? "—"}
                        {rule.set_subtipo ? (
                          <span className="block text-[10px] text-muted-foreground">
                            {rule.set_subtipo}
                          </span>
                        ) : null}
                      </td>
                      <td className="num px-2 py-2 text-right">{rule.prioridad}</td>
                      <td className="num px-2 py-2 text-right">{rule.hit_count}</td>
                      <td className="hidden px-2 py-2 text-[10px] text-muted-foreground lg:table-cell">
                        <span title={formatDateTime(rule.last_hit_at)}>
                          {rule.last_hit_at ? relativeDate(rule.last_hit_at) : "—"}
                        </span>
                      </td>
                      <td className="px-2 py-2">
                        {rule.auto_aprobar ? (
                          <Badge variant="positive">Auto</Badge>
                        ) : (
                          <Badge variant="outline">Revisar</Badge>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        <div className="flex justify-end">
                          <Switch
                            checked={active}
                            label={`Activar ${rule.nombre ?? `regla ${rule.id}`}`}
                            hideLabel
                            onChange={(value) =>
                              setActiveOverrides((current) => ({
                                ...current,
                                [rule.id]: value,
                              }))
                            }
                          />
                        </div>
                      </td>
                      <td className="px-2 py-2">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-6"
                          onClick={() => void dryRun(rule)}
                          loading={dryRunning === rule.id}
                          aria-label={`Probar regla ${rule.nombre ?? rule.id}`}
                          title="Dry-run"
                        >
                          <Play className="size-3" aria-hidden />
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <CardContent className="border-t border-border py-2.5 text-[10px] leading-4 text-muted-foreground">
          Las reglas de merchant tienen prioridad sobre MCC y tipo de broker. Autolearn
          nunca pisa reglas creadas a mano y solo auto-aprueba si hay una decisión
          humana detrás.
        </CardContent>
      </Card>
    </div>
  );
}
