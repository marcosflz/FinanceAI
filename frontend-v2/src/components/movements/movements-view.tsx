"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Fragment,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
  useTransition,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  ChevronsLeft,
  ChevronsRight,
  Copy,
  Keyboard,
  ListChecks,
  RefreshCw,
  Undo2,
  X,
} from "lucide-react";
import {
  accountsApi,
  categoriesApi,
  dedupApi,
  isApiUnavailable,
  movementsApi,
} from "@/lib/api";
import { DEMO_MODE, withMock } from "@/lib/demo";
import {
  getMockMovements,
  mockAccounts,
  mockCategories,
  mockDedupCandidates,
  mockMovementSummary,
} from "@/lib/mock";
import type {
  Account,
  Category,
  DedupCandidate,
  Movement,
  MovementFilters as MovementFiltersType,
  MovementState,
  MovementUpdate,
} from "@/lib/types";
import { cn, formatDate, formatMoney, toNumber } from "@/lib/utils";
import { PageHeader, LinkTabs, type LinkTabItem } from "@/components/ui/page-header";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";
import {
  EmptyState,
  ErrorState,
  Skeleton,
  TableSkeleton,
} from "@/components/ui/feedback";
import {
  MovementFilters,
  type MovementFilterValues,
} from "@/components/movements/movement-filters";
import {
  ConfidenceMeter,
  KindBadge,
  StateDot,
} from "@/components/movements/movement-badges";
import { categoryPair } from "@/lib/categories";
import { kindLabels } from "@/components/movements/constants";
import { MovementDetail } from "@/components/movements/movement-detail";
import { BatchClassifyPanel } from "@/components/movements/batch-classify-panel";
import { CategoryPairSelect } from "@/components/movements/category-pair-select";

const PAGE_SIZE = 25;
const EMPTY_ACCOUNTS: Account[] = [];
const EMPTY_CATEGORIES: Category[] = [];
const VALID_TABS = ["todos", "por-revisar", "duplicados", "transferencias", "sin-categorizar"];

interface MovementOverride {
  estado?: MovementState;
  categoria_id?: number | null;
  categoria?: string | null;
}

function applyOverride(
  movement: Movement,
  override: MovementOverride | undefined,
  categories: Category[],
): Movement {
  if (!override) return movement;

  let classification = movement.classification;
  if (override.categoria_id !== undefined) {
    if (override.categoria_id === null) {
      classification = null;
    } else {
      const category =
        override.categoria ??
        categories.find((item) => item.id === override.categoria_id)?.path ??
        null;
      classification = {
        categoria_id: override.categoria_id,
        categoria: category,
        subtipo: movement.classification?.subtipo ?? null,
        origen: "user",
        confianza: 1,
        explicacion: "Corrección manual desde la bandeja de movimientos.",
        vigente: true,
      };
    }
  }

  return {
    ...movement,
    estado: override.estado ?? movement.estado,
    classification,
  };
}

function tabEmptyCopy(tab: string): { title: string; description: string } {
  switch (tab) {
    case "por-revisar":
      return {
        title: "Nada pendiente por revisar",
        description: "La bandeja está al día. Los movimientos nuevos aparecerán aquí.",
      };
    case "duplicados":
      return {
        title: "Sin duplicados candidatos",
        description: "No hay pares con similitud suficiente para revisar.",
      };
    case "transferencias":
      return {
        title: "Sin transferencias internas",
        description: "Cuando detectemos movimientos entre tus cuentas, se enlazarán aquí.",
      };
    case "sin-categorizar":
      return {
        title: "Todo tiene categoría",
        description: "No quedan movimientos sin clasificar en esta vista.",
      };
    default:
      return {
        title: "Sin movimientos",
        description: "No hay filas que coincidan con los filtros actuales.",
      };
  }
}



function StatusActions({
  movement,
  onStatus,
  compact = false,
}: {
  movement: Movement;
  onStatus: (movement: Movement, state: MovementState) => void;
  compact?: boolean;
}) {
  const buttonClass = cn(
    "inline-flex items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-30",
    compact ? "size-6" : "size-7",
  );

  return (
    <div className="flex items-center justify-end gap-0.5">
      <button
        type="button"
        className={cn(buttonClass, "hover:text-positive")}
        title="Aprobar (A)"
        aria-label={`Aprobar ${movement.merchant ?? "movimiento"}`}
        disabled={movement.estado === "aprobado"}
        onClick={() => onStatus(movement, "aprobado")}
      >
        <Check className="size-3.5" aria-hidden />
      </button>
      <button
        type="button"
        className={cn(buttonClass, "hover:text-negative")}
        title="Rechazar (R)"
        aria-label={`Rechazar ${movement.merchant ?? "movimiento"}`}
        disabled={movement.estado === "rechazado"}
        onClick={() => onStatus(movement, "rechazado")}
      >
        <X className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}

export function MovementsView() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [isPending, startTransition] = useTransition();
  const [overrides, setOverrides] = useState<Record<number, MovementOverride>>({});
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [expanded, setExpanded] = useState<number | null>(null);
  const [focusedId, setFocusedId] = useState<number | null>(null);
  const [dedupResolved, setDedupResolved] = useState<Record<number, string>>({});
  const [bulkCategoryId, setBulkCategoryId] = useState<number | null>(null);

  const rawTab = searchParams.get("tab") ?? "todos";
  const tab = VALID_TABS.includes(rawTab) ? rawTab : "todos";
  const q = searchParams.get("q") ?? "";
  const [search, setSearch] = useState(q);
  const page = Math.max(1, Number(searchParams.get("page") ?? "1") || 1);

  const filterValues: MovementFilterValues = {
    account_id: searchParams.get("account_id") ?? "",
    kind: searchParams.get("kind") ?? "",
    origen: searchParams.get("origen") ?? "",
    categoria_id: searchParams.get("categoria_id") ?? "",
    subcategoria_id: searchParams.get("subcategoria_id") ?? "",
    from: searchParams.get("from") ?? "",
    to: searchParams.get("to") ?? "",
  };

  const updateParams = useCallback(
    (updates: Record<string, string | number | null>) => {
      const params = new URLSearchParams(searchParams.toString());
      if (!("page" in updates)) params.delete("page");
      for (const [key, value] of Object.entries(updates)) {
        if (value === null || value === "") params.delete(key);
        else params.set(key, String(value));
      }
      const queryString = params.toString();
      startTransition(() => {
        router.replace(queryString ? `${pathname}?${queryString}` : pathname, {
          scroll: false,
        });
      });
    },
    [pathname, router, searchParams, startTransition],
  );

  useEffect(() => {
    const urlQuery = searchParams.get("q") ?? "";
    if (search === urlQuery) return;
    const timer = setTimeout(() => {
      updateParams({ q: search.trim() || null, page: null });
    }, 350);
    return () => clearTimeout(timer);
  }, [search, searchParams, updateParams]);

  const filters: MovementFiltersType = useMemo(
    () => ({
      tab: tab === "todos" ? undefined : tab,
      q: q || undefined,
      estado: searchParams.get("estado") ?? undefined,
      kind: filterValues.kind || undefined,
      account_id: filterValues.account_id || undefined,
      categoria_id: filterValues.categoria_id || undefined,
      subcategoria_id: filterValues.subcategoria_id || undefined,
      origen: filterValues.origen || undefined,
      min_confidence: searchParams.get("min_confidence") ?? undefined,
      from: filterValues.from || undefined,
      to: filterValues.to || undefined,
      page,
      page_size: PAGE_SIZE,
    }),
    [tab, q, searchParams, filterValues.kind, filterValues.account_id, filterValues.categoria_id, filterValues.subcategoria_id, filterValues.origen, filterValues.from, filterValues.to, page],
  );

  const movementsQuery = useQuery({
    queryKey: ["movements", filters],
    queryFn: () =>
      withMock(() => movementsApi.list(filters), getMockMovements(filters)),
  });

  const tabCountsQuery = useQuery({
    queryKey: ["movements", "tab-counts"],
    queryFn: () =>
      withMock(
        async () => {
          const [review, duplicates, transfers, uncategorized] = await Promise.all([
            movementsApi.list({ tab: "por-revisar", page_size: 1 }),
            movementsApi.list({ tab: "duplicados", page_size: 1 }),
            movementsApi.list({ tab: "transferencias", page_size: 1 }),
            movementsApi.list({ tab: "sin-categorizar", page_size: 1 }),
          ]);
          return {
            pendientes: review.total,
            duplicados: duplicates.total,
            transferencias: transfers.total,
            sin_categoria: uncategorized.total,
          };
        },
        {
          pendientes: getMockMovements({ tab: "por-revisar", page_size: 1 }).total,
          duplicados: getMockMovements({ tab: "duplicados", page_size: 1 }).total,
          transferencias: getMockMovements({ tab: "transferencias", page_size: 1 }).total,
          sin_categoria: getMockMovements({ tab: "sin-categorizar", page_size: 1 }).total,
        },
      ),
  });

  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => withMock(() => accountsApi.list(), { items: mockAccounts }),
  });

  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: () => withMock(() => categoriesApi.list(), { items: mockCategories }),
  });

  const dedupQuery = useQuery({
    queryKey: ["dedup-candidates"],
    queryFn: () =>
      withMock(() => dedupApi.list(), { items: mockDedupCandidates }),
    enabled: tab === "duplicados",
  });

  // Nunca ofrecer cuentas/categorías de ejemplo fuera del modo demo: sus ids
  // se enviarían al backend al filtrar o clasificar.
  const accounts: Account[] =
    accountsQuery.data?.items ?? (DEMO_MODE ? mockAccounts : EMPTY_ACCOUNTS);
  const categories: Category[] =
    categoriesQuery.data?.items ?? (DEMO_MODE ? mockCategories : EMPTY_CATEGORIES);

  const data = movementsQuery.data;
  const items = useMemo(
    () =>
      (data?.items ?? []).map((movement) =>
        applyOverride(movement, overrides[movement.id], categories),
      ),
    [data?.items, overrides, categories],
  );

  const summary = data?.summary ??
    tabCountsQuery.data ??
    (DEMO_MODE
      ? mockMovementSummary
      : { pendientes: 0, sin_categoria: 0, duplicados: 0, transferencias: 0 });

  const selectedItems = items.filter((movement) => selected.has(movement.id));
  const dedupPairs = (dedupQuery.data?.items ?? []).filter(
    (pair) =>
      Boolean(pair.movement_a && pair.movement_b) && !dedupResolved[pair.id],
  );
  const allOnPageSelected =
    items.length > 0 && items.every((movement) => selected.has(movement.id));
  const hasFilters = Boolean(
    search ||
      q ||
      filterValues.account_id ||
      filterValues.kind ||
      filterValues.origen ||
      filterValues.categoria_id ||
      filterValues.subcategoria_id ||
      filterValues.from ||
      filterValues.to,
  );

  const tabItems: LinkTabItem[] = [
    { value: "todos", label: "Todos", href: tabHref("todos") },
    {
      value: "por-revisar",
      label: "Por revisar",
      href: tabHref("por-revisar"),
      count: summary.pendientes,
    },
    {
      value: "duplicados",
      label: "Duplicados",
      href: tabHref("duplicados"),
      count: summary.duplicados,
    },
    {
      value: "transferencias",
      label: "Transferencias",
      href: tabHref("transferencias"),
      count: summary.transferencias,
    },
    {
      value: "sin-categorizar",
      label: "Sin categorizar",
      href: tabHref("sin-categorizar"),
      count: summary.sin_categoria,
    },
  ];

  function tabHref(value: string): string {
    const params = new URLSearchParams(searchParams.toString());
    if (value === "todos") params.delete("tab");
    else params.set("tab", value);
    params.delete("page");
    const queryString = params.toString();
    return queryString ? `${pathname}?${queryString}` : pathname;
  }

  const restoreSnapshots = useCallback(
    (targets: Movement[], snapshots: Array<MovementOverride | undefined>) => {
      setOverrides((current) => {
        const next = { ...current };
        targets.forEach((movement, index) => {
          const snapshot = snapshots[index];
          if (snapshot) next[movement.id] = snapshot;
          else delete next[movement.id];
        });
        return next;
      });
    },
    [],
  );

  const changeStatus = useCallback(
    async (targets: Movement[], estado: MovementState) => {
    const applicable = targets.filter((movement) => movement.estado !== estado);
    if (applicable.length === 0) return;
    const snapshots = applicable.map((movement) => overrides[movement.id]);

    setOverrides((current) => {
      const next = { ...current };
      for (const movement of applicable) {
        next[movement.id] = { ...next[movement.id], estado };
      }
      return next;
    });

    try {
      if (!DEMO_MODE) {
        await Promise.all(
          applicable.map((movement) =>
            movementsApi.update(movement.id, { estado }),
          ),
        );
        await queryClient.invalidateQueries({ queryKey: ["movements"] });
      }

      toast({
        title:
          applicable.length === 1
            ? estado === "aprobado"
              ? "Movimiento aprobado"
              : "Movimiento rechazado"
            : `${applicable.length} movimientos actualizados`,
        description:
          applicable.length === 1
            ? applicable[0].merchant ?? `Movimiento #${applicable[0].id}`
            : `Estado: ${estado}`,
        variant: "success",
        action: {
          label: "Deshacer",
          onClick: () => {
            restoreSnapshots(applicable, snapshots);
            if (!DEMO_MODE) {
              void Promise.all(
                applicable.map((movement) =>
                  movementsApi.update(movement.id, { estado: movement.estado }),
                ),
              ).then(() => queryClient.invalidateQueries({ queryKey: ["movements"] }));
            }
          },
        },
      });
      } catch (error) {
        restoreSnapshots(applicable, snapshots);
        toast({
          title: "No se pudo actualizar el estado",
          description: isApiUnavailable(error)
            ? "La API v3 no está disponible. El cambio no se guardó."
            : "Revisa la sesión y vuelve a intentarlo.",
          variant: "error",
        });
      }
    },
    [overrides, queryClient, restoreSnapshots, toast],
  );

  async function changeCategory(targets: Movement[], rawValue: string) {
    const categoriaId = rawValue ? Number(rawValue) : null;
    const categoryName =
      categories.find((category) => category.id === categoriaId)?.path ?? null;
    const applicable = targets.filter(
      (movement) => (movement.classification?.categoria_id ?? null) !== categoriaId,
    );
    if (applicable.length === 0) return;
    const snapshots = applicable.map((movement) => overrides[movement.id]);

    setOverrides((current) => {
      const next = { ...current };
      for (const movement of applicable) {
        next[movement.id] = {
          ...next[movement.id],
          categoria_id: categoriaId,
          categoria: categoryName,
        };
      }
      return next;
    });

    try {
      if (!DEMO_MODE) {
        await Promise.all(
          applicable.map((movement) =>
            movementsApi.update(movement.id, { categoria_id: categoriaId }),
          ),
        );
        await queryClient.invalidateQueries({ queryKey: ["movements"] });
      }

      toast({
        title:
          applicable.length === 1
            ? "Categoría actualizada"
            : `${applicable.length} movimientos recategorizados`,
        description: categoryName ?? "Sin categoría",
        variant: "success",
        action: {
          label: "Deshacer",
          onClick: () => {
            restoreSnapshots(applicable, snapshots);
            if (!DEMO_MODE) {
              void Promise.all(
                applicable.map((movement) => {
                  const previous = movement.classification?.categoria_id ?? null;
                  return movementsApi.update(movement.id, {
                    categoria_id: previous,
                  } satisfies MovementUpdate);
                }),
              ).then(() => queryClient.invalidateQueries({ queryKey: ["movements"] }));
            }
          },
        },
      });
    } catch (error) {
      restoreSnapshots(applicable, snapshots);
      toast({
        title: "No se pudo cambiar la categoría",
        description: isApiUnavailable(error)
          ? "La API v3 no está disponible. El cambio no se guardó."
          : "Revisa la sesión y vuelve a intentarlo.",
        variant: "error",
      });
    }
  }

  async function resolveDedup(
    pair: DedupCandidate,
    resolution: "mismo" | "distinto",
  ) {
    setDedupResolved((current) => ({ ...current, [pair.id]: resolution }));
    try {
      if (!DEMO_MODE) {
        await dedupApi.resolve(pair.id, resolution);
        await queryClient.invalidateQueries({ queryKey: ["dedup-candidates"] });
      }
      toast({
        title:
          resolution === "mismo"
            ? "Par marcado como el mismo movimiento"
            : "Par marcado como distinto",
        description:
          resolution === "mismo"
            ? "No se borra nada: se conserva la trazabilidad y se enlazan las fuentes."
            : "El par no volverá a proponerse.",
        variant: "success",
      });
    } catch {
      setDedupResolved((current) => {
        const next = { ...current };
        delete next[pair.id];
        return next;
      });
      toast({
        title: "No se pudo resolver el duplicado",
        description: "La API v3 no está disponible.",
        variant: "error",
      });
    }
  }

  function toggleSelected(id: number) {    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAllOnPage() {
    setSelected((current) => {
      const next = new Set(current);
      if (allOnPageSelected) {
        for (const movement of items) next.delete(movement.id);
      } else {
        for (const movement of items) next.add(movement.id);
      }
      return next;
    });
  }

  function clearFilters() {
    setSearch("");
    const params = new URLSearchParams(searchParams.toString());
    for (const key of [
      "q",
      "account_id",
      "kind",
      "origen",
      "categoria_id",
      "subcategoria_id",
      "from",
      "to",
      "estado",
      "min_confidence",
      "page",
    ]) {
      params.delete(key);
    }
    const queryString = params.toString();
    startTransition(() => {
      router.replace(queryString ? `${pathname}?${queryString}` : pathname, {
        scroll: false,
      });
    });
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        target.closest(
          "input, textarea, select, button, a, [contenteditable='true'], [role='listbox'], [role='dialog'], [role='alertdialog']",
        )
      ) {
        return;
      }
      const key = event.key.toLowerCase();
      if (!["j", "k", "a", "r", "u"].includes(key) || items.length === 0) return;
      event.preventDefault();

      const currentIndex =
        focusedId !== null
          ? items.findIndex((movement) => movement.id === focusedId)
          : -1;

      if (key === "j" || key === "k") {
        let nextIndex: number;
        if (currentIndex === -1) {
          nextIndex = key === "j" ? 0 : items.length - 1;
        } else {
          nextIndex =
            key === "j"
              ? Math.min(items.length - 1, currentIndex + 1)
              : Math.max(0, currentIndex - 1);
        }
        const next = items[nextIndex];
        if (!next) return;
        setFocusedId(next.id);
        document
          .querySelector(`[data-movement-row="${next.id}"]`)
          ?.scrollIntoView({ block: "nearest" });
        return;
      }

      const current = items[currentIndex >= 0 ? currentIndex : 0];
      if (!current) return;
      if (key === "a") void changeStatus([current], "aprobado");
      else if (key === "r") void changeStatus([current], "rechazado");
      else void changeStatus([current], "pendiente");
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [items, focusedId, changeStatus]);

  const dayGroups = useMemo(() => groupByDay(items), [items]);

  const startRange = data && data.total > 0 ? (page - 1) * PAGE_SIZE + 1 : 0;
  const endRange = data ? Math.min(page * PAGE_SIZE, data.total) : 0;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-4">
      <PageHeader
        eyebrow="Bandeja global"
        title="Movimientos"
        description="Revisa, clasifica y aprueba todo lo que entra en tus cuentas. Los filtros viven en la URL y se pueden compartir."
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                void Promise.all([
                  movementsQuery.refetch(),
                  accountsQuery.refetch(),
                  categoriesQuery.refetch(),
                ]);
              }}
              loading={movementsQuery.isFetching}
            >
              <RefreshCw className="size-3.5" aria-hidden />
              Recargar
            </Button>
          </>
        }
      />

      <LinkTabs items={tabItems} active={tab} />

      <BatchClassifyPanel
        categories={categories}
        onDone={() => {
          void queryClient.invalidateQueries({ queryKey: ["movements"] });
        }}
      />

      <MovementFilters
        search={search}
        onSearchChange={setSearch}
        values={filterValues}
        onFilterChange={(key, value) => updateParams({ [key]: value || null, page: null })}
        onCategoryChange={(rootId, childId) =>
          updateParams({
            categoria_id: rootId || null,
            subcategoria_id: childId || null,
            page: null,
          })
        }
        onDateRangeChange={(from, to) =>
          updateParams({ from: from || null, to: to || null, page: null })
        }
        onClear={clearFilters}
        accounts={accounts}
        categories={categories}
        hasFilters={hasFilters}
        isPending={isPending || movementsQuery.isFetching}
      />

      {tab === "duplicados" ? (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-gradient-to-br from-warning-soft/60 via-card to-card px-5 py-4">
            <div className="flex items-start gap-3">
              <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl bg-warning-soft text-warning">
                <Copy className="size-4" aria-hidden />
              </span>
              <div>
                <p className="text-[13px] font-semibold tracking-tight text-foreground">
                  Cola de duplicados
                </p>
                <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">
                  Pares parecidos que necesitan una decisión humana. Nunca se fusionan
                  automáticamente.
                </p>
              </div>
            </div>
            <Badge variant={dedupPairs.length > 0 ? "warning" : "positive"}>
              {dedupPairs.length}{" "}
              {dedupPairs.length === 1 ? "par pendiente" : "pares pendientes"}
            </Badge>
          </div>
          {dedupQuery.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-16 w-full rounded-xl" />
              <Skeleton className="h-16 w-full rounded-xl" />
            </div>
          ) : dedupPairs.length === 0 ? (
            <EmptyState
              title="Cola vacía"
              description="No hay pares pendientes de resolver."
              icon={<Copy className="size-4" aria-hidden />}
            />
          ) : (
            <div className="space-y-2 p-3">
              {dedupPairs.map((pair) => {
                const pct = Math.round(pair.score * 100);
                return (
                  <div
                    key={pair.id}
                    className="animate-fade-in rounded-xl border border-border bg-card p-3 transition-shadow hover:shadow-sm"
                  >
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                      <div className="grid flex-1 items-center gap-2 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
                        {[pair.movement_a, pair.movement_b].map((movement, index) => (
                          <Fragment key={movement.id}>
                            {index === 1 ? (
                              <span
                                className="hidden size-7 items-center justify-center justify-self-center rounded-full border border-border bg-muted text-[12px] font-semibold text-muted-foreground sm:flex"
                                aria-hidden
                              >
                                ≈
                              </span>
                            ) : null}
                            <div className="flex min-w-0 items-center gap-2.5 rounded-lg bg-subtle px-2.5 py-2">
                              <MerchantAvatar
                                name={movement.merchant}
                                color={categoryColor(categories, movement)}
                              />
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center justify-between gap-2">
                                  <span className="truncate text-[12px] font-medium">
                                    {movement.merchant ?? "Sin comercio"}
                                  </span>
                                  <span className="num shrink-0 text-[12px] font-semibold">
                                    {formatMoney(movement.amount, {
                                      signDisplay: "always",
                                      currency: movement.currency,
                                    })}
                                  </span>
                                </div>
                                <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                                  {formatDate(movement.value_date, "medium")} ·{" "}
                                  {movement.account?.nombre ?? "Sin cuenta"} · {movement.estado}
                                </p>
                              </div>
                            </div>
                          </Fragment>
                        ))}
                      </div>
                      <div className="flex items-center justify-between gap-3 lg:w-[250px] lg:justify-end">
                        <div className="w-20" title="Similitud estimada">
                          <div className="flex items-baseline justify-between text-[10px]">
                            <span className="text-muted-foreground">Similitud</span>
                            <span
                              className={cn(
                                "num font-semibold",
                                pct >= 90 ? "text-warning" : "text-muted-foreground",
                              )}
                            >
                              {pct}%
                            </span>
                          </div>
                          <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
                            <div
                              className={cn(
                                "h-full rounded-full",
                                pct >= 90 ? "bg-warning" : "bg-muted-foreground/40",
                              )}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                        <div className="flex gap-1.5">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => void resolveDedup(pair, "mismo")}
                          >
                            <Check className="size-3 text-positive" aria-hidden />
                            Mismo
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => void resolveDedup(pair, "distinto")}
                          >
                            <X className="size-3" aria-hidden />
                            Distinto
                          </Button>
                        </div>
                      </div>
                    </div>
                    {pair.motivo ? (
                      <p className="mt-2 text-[10px] leading-4 text-muted-foreground">
                        {pair.motivo}
                      </p>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      ) : null}

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <span className="num font-medium text-foreground">
              {data ? `${startRange}–${endRange}` : "—"}
            </span>
            {data ? <span>de <span className="num">{data.total}</span> movimientos</span> : null}
            {movementsQuery.isFetching ? (
              <span className="inline-flex items-center gap-1 text-accent">
                <RefreshCw className="size-3 animate-spin" aria-hidden />
                actualizando
              </span>
            ) : null}
          </div>
          <p className="hidden items-center gap-1.5 text-[10px] text-muted-foreground sm:flex">
            <Keyboard className="size-3" aria-hidden />
            <Kbd>j</Kbd>
            <Kbd>k</Kbd> mover
            <Kbd>a</Kbd> aprobar
            <Kbd>r</Kbd> rechazar
            <Kbd>u</Kbd> pendiente
          </p>
        </div>

        {movementsQuery.isLoading ? (
          <TableSkeleton rows={9} />
        ) : movementsQuery.isError ? (
          <ErrorState
            className="rounded-none border-0"
            title="No se pudieron cargar los movimientos"
            description="La API v3 no respondió y no hay datos de respaldo para esta consulta."
            action={
              <Button variant="secondary" size="sm" onClick={() => movementsQuery.refetch()}>
                <RefreshCw className="size-3.5" aria-hidden />
                Reintentar
              </Button>
            }
          />
        ) : items.length === 0 ? (
          <EmptyState
            title={tabEmptyCopy(tab).title}
            description={tabEmptyCopy(tab).description}
            icon={<ListChecks className="size-4" aria-hidden />}
            action={
              hasFilters ? (
                <Button variant="secondary" size="sm" onClick={clearFilters}>
                  <Undo2 className="size-3.5" aria-hidden />
                  Limpiar filtros
                </Button>
              ) : (
                <Link
                  href="/imports"
                  className="inline-flex h-8 items-center rounded-lg border border-border bg-card px-3 text-[12px] font-medium transition-colors hover:bg-muted"
                >
                  Importar extracto
                </Link>
              )
            }
          />
        ) : (
          <>
            {/* Mobile list */}
            <div className="md:hidden">
              {dayGroups.map((group) => (
                <section key={group.key}>
                  <DayHeader group={group} />
                  <ul className="divide-y divide-border/70">
                    {group.items.map((movement) => {
                      const isExpanded = expanded === movement.id;
                      const amount = toNumber(movement.amount);
                      return (
                        <li
                          key={movement.id}
                          data-movement-row={movement.id}
                          className={cn(
                            "px-3 py-3 transition-colors",
                            selected.has(movement.id)
                              ? "bg-accent-soft/40"
                              : focusedId === movement.id && "bg-accent-soft/25",
                          )}
                        >
                          <div className="flex items-start gap-3">
                            <button
                              type="button"
                              onClick={() => toggleSelected(movement.id)}
                              aria-label={`Seleccionar ${movement.merchant ?? movement.id}`}
                              aria-pressed={selected.has(movement.id)}
                            >
                              <MerchantAvatar
                                name={movement.merchant}
                                color={categoryColor(categories, movement)}
                                selected={selected.has(movement.id)}
                                size="md"
                              />
                            </button>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                  <p className="truncate text-[13px] font-medium text-foreground">
                                    {movement.merchant ?? "Sin comercio"}
                                  </p>
                                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                                    {movement.account?.nombre ?? "Sin cuenta"} ·{" "}
                                    {kindLabels[movement.kind]}
                                  </p>
                                </div>
                                <p
                                  className={cn(
                                    "num shrink-0 text-[13px] font-semibold",
                                    movement.amount !== null && amount >= 0 && "text-positive",
                                  )}
                                >
                                  {movement.amount === null
                                    ? "—"
                                    : formatMoney(movement.amount, {
                                        signDisplay: "always",
                                        currency: movement.currency,
                                      })}
                                </p>
                              </div>

                              <div className="mt-2 flex items-center justify-between gap-2">
                                <CategoryPairSelect
                                  categoryId={movement.classification?.categoria_id}
                                  categories={categories}
                                  onChange={(value) =>
                                    void changeCategory(
                                      [movement],
                                      value == null ? "" : String(value),
                                    )
                                  }
                                  ariaPrefix={movement.merchant ?? "movimiento"}
                                  className="w-52 rounded-lg bg-muted/50"
                                  compact
                                />
                                <div className="flex items-center gap-1">
                                  <StateDot state={movement.estado} />
                                  <button
                                    type="button"
                                    onClick={() => setExpanded(isExpanded ? null : movement.id)}
                                    className="inline-flex size-6 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                                    aria-label={isExpanded ? "Contraer detalle" : "Expandir detalle"}
                                  >
                                    <ChevronDown
                                      className={cn("size-3.5 transition-transform", isExpanded && "rotate-180")}
                                      aria-hidden
                                    />
                                  </button>
                                  <StatusActions
                                    movement={movement}
                                    onStatus={(target, state) => void changeStatus([target], state)}
                                    compact
                                  />
                                </div>
                              </div>

                              {isExpanded ? (
                                <div className="animate-fade-in mt-3 rounded-xl border border-border bg-subtle p-3">
                                  <MovementDetail movement={movement} categories={categories} />
                                </div>
                              ) : null}
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))}
            </div>

            {/* Desktop table */}
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[860px] border-collapse text-left">
                <thead className="[&_th]:sticky [&_th]:top-0 [&_th]:z-10 [&_th]:bg-card">
                  <tr className="text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                    <th className="w-10 border-b border-border py-2 pl-4 pr-1">
                      <Checkbox
                        checked={allOnPageSelected}
                        onChange={toggleAllOnPage}
                        aria-label="Seleccionar todos los movimientos de la página"
                      />
                    </th>
                    <th scope="col" className="min-w-[240px] border-b border-border px-2 py-2">
                      Comercio
                    </th>
                    <th scope="col" className="hidden w-36 border-b border-border px-2 py-2 xl:table-cell">
                      Cuenta
                    </th>
                    <th scope="col" className="w-[260px] border-b border-border px-2 py-2">
                      Categoría
                    </th>
                    <th scope="col" className="hidden w-32 border-b border-border px-2 py-2 lg:table-cell">
                      Confianza
                    </th>
                    <th scope="col" className="w-28 border-b border-border px-2 py-2 text-right">
                      Importe
                    </th>
                    <th scope="col" className="w-36 border-b border-border py-2 pl-2 pr-4 text-right">
                      Estado
                    </th>
                  </tr>
                </thead>
                {dayGroups.map((group) => (
                  <tbody key={group.key}>
                    <tr>
                      <td colSpan={TABLE_COLUMNS} className="p-0">
                        <DayHeader group={group} />
                      </td>
                    </tr>
                    {group.items.map((movement) => {
                      const isExpanded = expanded === movement.id;
                      return (
                        <MovementRows
                          key={movement.id}
                          movement={movement}
                          categories={categories}
                          expanded={isExpanded}
                          selected={selected.has(movement.id)}
                          onToggleSelected={() => toggleSelected(movement.id)}
                          onToggleExpanded={() => setExpanded(isExpanded ? null : movement.id)}
                          onStatus={(state) => void changeStatus([movement], state)}
                          onCategory={(value) => void changeCategory([movement], value)}
                          focused={focusedId === movement.id}
                        />
                      );
                    })}
                  </tbody>
                ))}
              </table>
            </div>
          </>
        )}

        <Pagination
          page={page}
          totalPages={totalPages}
          onPage={(next) => updateParams({ page: next === 1 ? null : next })}
        />
      </Card>

      {selectedItems.length > 0 ? (
        <div className="animate-dialog-in fixed inset-x-3 bottom-[68px] z-50 mx-auto flex max-w-3xl flex-wrap items-center gap-2 rounded-2xl border border-border bg-popover/95 p-2 pl-3 shadow-2xl backdrop-blur sm:bottom-5">
          <span className="inline-flex items-center gap-2 text-[12px] font-medium">
            <span className="num flex h-6 min-w-6 items-center justify-center rounded-full bg-accent px-1.5 text-[11px] text-accent-foreground">
              {selectedItems.length}
            </span>
            seleccionados
            <span className="num text-muted-foreground">
              ·{" "}
              {formatMoney(
                selectedItems.reduce((sum, movement) => sum + eurAmount(movement), 0),
                { signDisplay: "always" },
              )}
            </span>
          </span>
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => void changeStatus(selectedItems, "aprobado")}
            >
              <Check className="size-3.5 text-positive" aria-hidden />
              Aprobar
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => void changeStatus(selectedItems, "rechazado")}
            >
              <X className="size-3.5 text-negative" aria-hidden />
              Rechazar
            </Button>
            <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />
            <CategoryPairSelect
              categoryId={bulkCategoryId}
              categories={categories}
              onChange={setBulkCategoryId}
              ariaPrefix="la selección"
              className="w-56 rounded-lg border border-border bg-card px-1"
              compact
            />
            <Button
              size="sm"
              variant="primary"
              disabled={bulkCategoryId == null}
              onClick={() => {
                if (bulkCategoryId == null) return;
                void changeCategory(selectedItems, String(bulkCategoryId));
                setBulkCategoryId(null);
                setSelected(new Set());
              }}
            >
              Aplicar
            </Button>
            <button
              type="button"
              onClick={() => {
                setBulkCategoryId(null);
                setSelected(new Set());
              }}
              aria-label="Quitar selección"
              className="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ piezas */

const TABLE_COLUMNS = 7;

interface DayGroup {
  key: string;
  date: string | null;
  items: Movement[];
  inflow: number;
  outflow: number;
}

function eurAmount(movement: Movement): number {
  return toNumber(movement.amount_eur ?? movement.amount ?? 0);
}

function groupByDay(items: Movement[]): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const movement of items) {
    const key = movement.value_date ?? "sin-fecha";
    let group = groups[groups.length - 1];
    if (!group || group.key !== key) {
      group = { key, date: movement.value_date ?? null, items: [], inflow: 0, outflow: 0 };
      groups.push(group);
    }
    group.items.push(movement);
    const amount = eurAmount(movement);
    if (amount >= 0) group.inflow += amount;
    else group.outflow += amount;
  }
  return groups;
}

function dayLabel(value: string | null): string {
  if (!value) return "Sin fecha";
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value);
  if (Number.isNaN(date.getTime())) return "Sin fecha";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((today.getTime() - date.getTime()) / 86_400_000);
  if (diff === 0) return "Hoy";
  if (diff === 1) return "Ayer";
  const label = new Intl.DateTimeFormat("es-ES", {
    weekday: "long",
    day: "numeric",
    month: "long",
    ...(date.getFullYear() !== today.getFullYear() ? { year: "numeric" } : {}),
  }).format(date);
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function DayHeader({ group }: { group: DayGroup }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/70 bg-subtle px-4 py-1.5">
      <span className="text-[11px] font-semibold text-foreground">
        {dayLabel(group.date)}
        <span className="ml-2 font-normal text-muted-foreground">
          {group.items.length} {group.items.length === 1 ? "movimiento" : "movimientos"}
        </span>
      </span>
      <span className="num flex items-center gap-3 text-[11px]">
        {group.inflow > 0 ? (
          <span className="text-positive">{formatMoney(group.inflow, { signDisplay: "always" })}</span>
        ) : null}
        {group.outflow < 0 ? (
          <span className="text-muted-foreground">{formatMoney(group.outflow, { signDisplay: "always" })}</span>
        ) : null}
      </span>
    </div>
  );
}

function categoryColor(categories: Category[], movement: Movement): string | null {
  const pair = categoryPair(categories, movement.classification?.categoria_id);
  return pair.child?.color || pair.root?.color || null;
}

function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const words = name
    .replace(/[^\p{L}\p{N} ]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

function MerchantAvatar({
  name,
  color,
  selected = false,
  size = "sm",
}: {
  name: string | null | undefined;
  color: string | null;
  selected?: boolean;
  size?: "sm" | "md";
}) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-lg font-semibold transition-colors",
        size === "md" ? "size-9 text-[12px]" : "size-8 text-[11px]",
        selected ? "bg-accent text-accent-foreground" : !color && "bg-muted text-muted-foreground",
      )}
      style={
        !selected && color
          ? { backgroundColor: `${color}1f`, color, boxShadow: `inset 0 0 0 1px ${color}33` }
          : undefined
      }
      aria-hidden
    >
      {selected ? <Check className="size-4" /> : initials(name)}
    </span>
  );
}

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-border bg-card px-1 font-sans text-[9px] font-medium text-foreground shadow-[0_1px_0_var(--border)]">
      {children}
    </kbd>
  );
}

function pageWindow(page: number, totalPages: number): Array<number | "…"> {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1);
  const pages = new Set([1, totalPages, page - 1, page, page + 1]);
  const sorted = [...pages].filter((value) => value >= 1 && value <= totalPages).sort((a, b) => a - b);
  const result: Array<number | "…"> = [];
  sorted.forEach((value, index) => {
    if (index > 0 && value - sorted[index - 1] > 1) result.push("…");
    result.push(value);
  });
  return result;
}

function Pagination({
  page,
  totalPages,
  onPage,
}: {
  page: number;
  totalPages: number;
  onPage: (page: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5">
      <p className="text-[11px] text-muted-foreground">
        Página <span className="num font-medium text-foreground">{page}</span> de{" "}
        <span className="num">{totalPages}</span>
      </p>
      <nav className="flex items-center gap-0.5" aria-label="Paginación">
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
          aria-label="Página anterior"
        >
          <ChevronsLeft className="size-3.5" aria-hidden />
        </Button>
        {pageWindow(page, totalPages).map((value, index) =>
          value === "…" ? (
            <span key={`gap-${index}`} className="px-1 text-[11px] text-muted-foreground">
              …
            </span>
          ) : (
            <button
              key={value}
              type="button"
              onClick={() => onPage(value)}
              aria-current={value === page ? "page" : undefined}
              className={cn(
                "num h-7 min-w-7 rounded-md px-1.5 text-[11px] font-medium transition-colors",
                value === page
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {value}
            </button>
          ),
        )}
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          disabled={page >= totalPages}
          onClick={() => onPage(page + 1)}
          aria-label="Página siguiente"
        >
          <ChevronsRight className="size-3.5" aria-hidden />
        </Button>
      </nav>
    </div>
  );
}

function MovementRows({
  movement,
  categories,
  expanded,
  selected,
  focused,
  onToggleSelected,
  onToggleExpanded,
  onStatus,
  onCategory,
}: {
  movement: Movement;
  categories: Category[];
  expanded: boolean;
  selected: boolean;
  focused: boolean;
  onToggleSelected: () => void;
  onToggleExpanded: () => void;
  onStatus: (state: MovementState) => void;
  onCategory: (value: string) => void;
}) {
  const amount = toNumber(movement.amount);
  const reasons = movement.review_reasons ?? [];
  const subtitle =
    movement.description && movement.description !== movement.merchant
      ? movement.description
      : movement.classification?.subtipo ?? null;

  return (
    <>
      <tr
        data-movement-row={movement.id}
        className={cn(
          "group border-b border-border/60 text-[12px] transition-colors",
          selected
            ? "bg-accent-soft/40"
            : focused
              ? "bg-accent-soft/25 shadow-[inset_2px_0_0_var(--accent)]"
              : "hover:bg-muted/40",
          expanded && !selected && "bg-muted/30",
        )}
      >
        <td className="py-2.5 pl-4 pr-1 align-middle">
          <Checkbox
            checked={selected}
            onChange={onToggleSelected}
            aria-label={`Seleccionar ${movement.merchant ?? movement.id}`}
          />
        </td>
        <td className="px-2 py-2.5 align-middle">
          <button
            type="button"
            onClick={onToggleExpanded}
            className="flex w-full min-w-0 items-center gap-3 text-left"
            aria-expanded={expanded}
            aria-label={`${expanded ? "Contraer" : "Expandir"} detalle de ${movement.merchant ?? "movimiento"}`}
          >
            <MerchantAvatar name={movement.merchant} color={categoryColor(categories, movement)} />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1.5">
                <span className="truncate font-medium text-foreground">
                  {movement.merchant ?? "Sin comercio"}
                </span>
                {movement.duplicate_of ? (
                  <Badge variant="warning" className="h-4 shrink-0 px-1 text-[9px]">
                    <Copy className="size-2.5" aria-hidden /> Dup
                  </Badge>
                ) : null}
                {reasons.length > 0 ? (
                  <span
                    className="size-1.5 shrink-0 rounded-full bg-warning ring-2 ring-warning/20"
                    title={reasons.join(" · ")}
                    aria-label={reasons.join(" · ")}
                  />
                ) : null}
              </span>
              <span className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                <KindBadge kind={movement.kind} className="h-4 px-1 text-[9px]" />
                {subtitle ? <span className="truncate">{subtitle}</span> : null}
              </span>
            </span>
            <ChevronDown
              className={cn(
                "size-3.5 shrink-0 text-muted-foreground opacity-0 transition-all group-hover:opacity-100",
                expanded && "rotate-180 opacity-100",
              )}
              aria-hidden
            />
          </button>
        </td>
        <td className="hidden px-2 py-2.5 align-middle text-[11px] text-muted-foreground xl:table-cell">
          <span className="block truncate">{movement.account?.nombre ?? "—"}</span>
          {movement.account_destino ? (
            <span className="block truncate text-[10px] text-accent">
              → {movement.account_destino.nombre}
            </span>
          ) : null}
        </td>
        <td className="px-2 py-2.5 align-middle">
          <CategoryPairSelect
            categoryId={movement.classification?.categoria_id}
            categories={categories}
            onChange={(value) => onCategory(value == null ? "" : String(value))}
            ariaPrefix={movement.merchant ?? "movimiento"}
            className="w-[250px] rounded-lg bg-muted/40 transition-colors group-hover:bg-muted/70"
          />
        </td>
        <td className="hidden px-2 py-2.5 align-middle lg:table-cell">
          <ConfidenceMeter classification={movement.classification} />
        </td>
        <td
          className={cn(
            "num whitespace-nowrap px-2 py-2.5 text-right align-middle text-[13px] font-semibold",
            movement.amount !== null && amount >= 0 ? "text-positive" : "text-foreground",
          )}
        >
          {movement.amount === null
            ? "—"
            : formatMoney(amount, { signDisplay: "always", currency: movement.currency })}
        </td>
        <td className="py-2.5 pl-2 pr-4 align-middle">
          <div className="relative flex h-7 items-center justify-end">
            <span className="transition-opacity group-focus-within:opacity-0 group-hover:opacity-0">
              <StateDot state={movement.estado} />
            </span>
            <span className="absolute inset-y-0 right-0 flex items-center rounded-lg bg-card opacity-0 shadow-sm ring-1 ring-border transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
              <StatusActions movement={movement} onStatus={(_, state) => onStatus(state)} />
            </span>
          </div>
        </td>
      </tr>
      {expanded ? (
        <tr className="border-b border-border bg-subtle">
          <td colSpan={TABLE_COLUMNS} className="px-5 py-4">
            <div className="animate-fade-in">
              <MovementDetail movement={movement} categories={categories} />
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
