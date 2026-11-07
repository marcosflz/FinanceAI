"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import {
  BookMarked,
  BrainCircuit,
  Check,
  ChevronDown,
  ChevronRight,
  CircleSlash,
  Keyboard,
  ListChecks,
  Pencil,
  Sparkles,
  Undo2,
  Wand2,
  X,
} from "lucide-react";
import { classifyApi, modelsApi, movementsApi } from "@/lib/api";
import type {
  Category,
  ClassificationBatchItem,
  ClassificationBatchResponse,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/feedback";
import { CategoryPairSelect } from "@/components/movements/category-pair-select";
import { useToast } from "@/components/ui/toast";
import { categoryPair } from "@/lib/categories";
import { cn, formatDate, formatMoney } from "@/lib/utils";

const DEFAULT_BATCH_SIZE = 10;
const BATCH_SIZE_PRESETS = [5, 10, 20, 30];
const HIGH_CONFIDENCE = 0.8;
const LOW_CONFIDENCE = 0.6;
const COLLAPSE_KEY = "ft.jev-panel.collapsed";

const collapseListeners = new Set<() => void>();

function subscribeCollapse(listener: () => void) {
  collapseListeners.add(listener);
  return () => {
    collapseListeners.delete(listener);
  };
}

function readCollapse(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

function setCollapsed(next: boolean) {
  try {
    window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
  } catch {
    /* localStorage no disponible */
  }
  collapseListeners.forEach((listener) => listener());
}

type Decision = "accept" | "skip";
type ViewFilter = "all" | "low" | "uncategorized";

interface ReviewItem extends ClassificationBatchItem {
  decision: Decision;
  edited: boolean;
}

interface MethodInfo {
  label: string;
  icon: typeof BrainCircuit;
  className: string;
}

function methodInfo(item: ClassificationBatchItem): MethodInfo {
  switch (item.method) {
    case "rule":
      return { label: "Regla", icon: ListChecks, className: "bg-positive-soft text-positive" };
    case "memory":
      return { label: "Memoria", icon: BookMarked, className: "bg-info-soft text-info" };
    case "decider":
    case "decider_auto":
    case "decider_review":
      return {
        label: item.method === "decider_review" ? "Jev · revisar" : "Jev",
        icon: BrainCircuit,
        className: "bg-accent-soft text-accent-soft-foreground",
      };
    default:
      return { label: "Sin sugerencia", icon: CircleSlash, className: "bg-muted text-muted-foreground" };
  }
}

function confidenceTone(value: number | null): "high" | "mid" | "low" | "none" {
  if (value == null) return "none";
  if (value >= HIGH_CONFIDENCE) return "high";
  if (value >= LOW_CONFIDENCE) return "mid";
  return "low";
}

const toneBar: Record<ReturnType<typeof confidenceTone>, string> = {
  high: "bg-positive",
  mid: "bg-warning",
  low: "bg-negative",
  none: "bg-muted-foreground/30",
};

const toneText: Record<ReturnType<typeof confidenceTone>, string> = {
  high: "text-positive",
  mid: "text-warning",
  low: "text-negative",
  none: "text-muted-foreground",
};

function toReview(item: ClassificationBatchItem): ReviewItem {
  return { ...item, decision: item.categoria_id != null ? "accept" : "skip", edited: false };
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || target.isContentEditable;
}

export function BatchClassifyPanel({
  categories,
  onDone,
}: {
  categories: Category[];
  onDone: () => void;
}) {
  const { toast } = useToast();
  const [batchSize, setBatchSize] = useState(DEFAULT_BATCH_SIZE);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [response, setResponse] = useState<ClassificationBatchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<{ done: number; total: number } | null>(null);
  const collapsed = useSyncExternalStore(subscribeCollapse, readCollapse, () => false);
  const [focusedRaw, setFocused] = useState(0);
  const [editing, setEditing] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState<ViewFilter>("all");
  const [session, setSession] = useState({ accepted: 0, auto: 0, batches: 0 });
  const [initialPending, setInitialPending] = useState<number | null>(null);
  const rowRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  useEffect(() => {
    void modelsApi
      .get()
      .then((settings) => setBatchSize(settings.classification_batch_size))
      .catch(() => setBatchSize(DEFAULT_BATCH_SIZE));
  }, []);

  function toggleCollapsed() {
    setCollapsed(!collapsed);
  }

  const nextBatch = useCallback(async () => {
    setLoading(true);
    setCollapsed(false);
    try {
      const result = await classifyApi.batch({ limit: batchSize });
      const reviewItems = result.items.filter((item) => !item.auto_approved);
      const autoApproved = result.items.length - reviewItems.length;
      setResponse(result);
      setItems(reviewItems.map(toReview));
      setFocused(0);
      setEditing(null);
      setExpanded(new Set());
      setFilter("all");
      setInitialPending((current) => current ?? result.remaining + result.items.length);
      setSession((current) => ({
        ...current,
        auto: current.auto + autoApproved,
        batches: current.batches + (result.items.length > 0 ? 1 : 0),
      }));
      if (autoApproved > 0) {
        toast({
          title: `${autoApproved} autoaprobados por Jev`,
          description:
            reviewItems.length > 0
              ? `Quedan ${reviewItems.length} en este lote para revisar.`
              : "No queda nada de este lote para revisar.",
          variant: "success",
        });
      } else if (result.items.length === 0) {
        toast({
          title: "No quedan movimientos que clasificar",
          description: "La cola está vacía o todo tiene ya categoría.",
          variant: "success",
        });
      }
    } catch {
      toast({
        title: "No se pudo preparar el lote",
        description: "Comprueba que Jev está configurado y la API v3 responde.",
        variant: "error",
      });
    } finally {
      setLoading(false);
    }
  }, [batchSize, toast]);

  function patchItem(movementId: number, patch: Partial<ReviewItem>) {
    setItems((current) =>
      current.map((item) => (item.movement_id === movementId ? { ...item, ...patch } : item)),
    );
  }

  function setCategory(movementId: number, categoryId: number | null) {
    const category = categories.find((item) => item.id === categoryId) ?? null;
    patchItem(movementId, {
      categoria_id: categoryId,
      categoria: category?.nombre ?? null,
      decision: categoryId != null ? "accept" : "skip",
      edited: true,
    });
  }

  function toggleDecision(item: ReviewItem) {
    if (item.categoria_id == null) {
      setEditing(item.movement_id);
      return;
    }
    patchItem(item.movement_id, { decision: item.decision === "accept" ? "skip" : "accept" });
  }

  function setAll(decision: Decision, predicate: (item: ReviewItem) => boolean = () => true) {
    setItems((current) =>
      current.map((item) =>
        predicate(item) && (decision === "skip" || item.categoria_id != null)
          ? { ...item, decision }
          : item,
      ),
    );
  }

  function toggleExpanded(movementId: number) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(movementId)) next.delete(movementId);
      else next.add(movementId);
      return next;
    });
  }

  const toAccept = items.filter((item) => item.decision === "accept" && item.categoria_id != null);

  async function saveAndNext() {
    if (saving) return;
    if (toAccept.length === 0) {
      setItems([]);
      await nextBatch();
      return;
    }
    setSaving({ done: 0, total: toAccept.length });
    let done = 0;
    try {
      for (const item of toAccept) {
        await movementsApi.update(item.movement_id, {
          categoria_id: item.categoria_id,
          estado: "aprobado",
        });
        done += 1;
        setSaving({ done, total: toAccept.length });
      }
      const skipped = items.length - toAccept.length;
      toast({
        title: `${done} movimientos aprobados`,
        description:
          skipped > 0
            ? `${skipped} omitidos quedan pendientes. Las decisiones se usarán como referencia.`
            : "Las decisiones se usarán como referencia en el siguiente lote.",
        variant: "success",
      });
      setSession((current) => ({ ...current, accepted: current.accepted + done }));
      onDone();
      setItems([]);
      await nextBatch();
    } catch {
      toast({
        title: "No se pudo guardar el lote",
        description: `Se guardaron ${done} de ${toAccept.length}. Revisa y vuelve a intentarlo.`,
        variant: "error",
      });
      if (done > 0) {
        const savedIds = new Set(toAccept.slice(0, done).map((item) => item.movement_id));
        setItems((current) => current.filter((item) => !savedIds.has(item.movement_id)));
        setSession((current) => ({ ...current, accepted: current.accepted + done }));
        onDone();
      }
    } finally {
      setSaving(null);
    }
  }

  function closeBatch() {
    setItems([]);
    setEditing(null);
  }

  const visibleItems = useMemo(() => {
    switch (filter) {
      case "low":
        return items.filter((item) => confidenceTone(item.confianza) !== "high");
      case "uncategorized":
        return items.filter((item) => item.categoria_id == null);
      default:
        return items;
    }
  }, [items, filter]);

  const focused = Math.max(0, Math.min(focusedRaw, visibleItems.length - 1));

  useEffect(() => {
    const item = visibleItems[focused];
    if (!item) return;
    rowRefs.current.get(item.movement_id)?.scrollIntoView({ block: "nearest" });
  }, [focused, visibleItems]);

  function onListKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (isTypingTarget(event.target)) {
      if (event.key === "Escape") {
        setEditing(null);
        (event.currentTarget as HTMLElement).focus();
      }
      return;
    }
    const item = visibleItems[focused];
    switch (event.key) {
      case "ArrowDown":
      case "j":
        event.preventDefault();
        setFocused(Math.min(focused + 1, visibleItems.length - 1));
        break;
      case "ArrowUp":
      case "k":
        event.preventDefault();
        setFocused(Math.max(focused - 1, 0));
        break;
      case " ":
      case "x":
        if (item) {
          event.preventDefault();
          toggleDecision(item);
        }
        break;
      case "e":
        if (item) {
          event.preventDefault();
          setEditing(item.movement_id);
        }
        break;
      case "i":
        if (item) {
          event.preventDefault();
          toggleExpanded(item.movement_id);
        }
        break;
      case "Enter":
        if (event.metaKey || event.ctrlKey) {
          event.preventDefault();
          void saveAndNext();
        }
        break;
      case "Escape":
        setEditing(null);
        break;
    }
  }

  const references = response?.reference_count ?? 0;
  const referenceCap = response?.reference_cap ?? 40;
  const referencePct = Math.min(100, Math.round((references / Math.max(referenceCap, 1)) * 100));
  const remaining = response?.remaining ?? null;
  const sessionDone = session.accepted + session.auto;
  const progressPct =
    initialPending && initialPending > 0
      ? Math.min(100, Math.round((sessionDone / initialPending) * 100))
      : 0;
  const counts = {
    rule: items.filter((item) => item.method === "rule").length,
    memory: items.filter((item) => item.method === "memory").length,
    jev: items.filter((item) => item.method.startsWith("decider")).length,
    low: items.filter((item) => confidenceTone(item.confianza) !== "high").length,
    uncategorized: items.filter((item) => item.categoria_id == null).length,
  };
  const reviewing = items.length > 0;

  return (
    <Card className="overflow-hidden">
      {/* Cabecera */}
      <div className="relative border-b border-border bg-gradient-to-br from-accent-soft/70 via-card to-card px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <button
            type="button"
            onClick={toggleCollapsed}
            className="group flex min-w-0 items-start gap-3 text-left"
            aria-expanded={!collapsed}
          >
            <span className="relative mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-foreground shadow-sm">
              <BrainCircuit className="size-4" aria-hidden />
              {loading ? (
                <span className="absolute inset-0 animate-ping rounded-xl bg-accent/40" aria-hidden />
              ) : null}
            </span>
            <span className="min-w-0">
              <span className="flex items-center gap-1.5 text-[13px] font-semibold tracking-tight">
                Clasificación asistida por Jev
                <ChevronDown
                  className={cn(
                    "size-3.5 text-muted-foreground transition-transform",
                    collapsed && "-rotate-90",
                  )}
                  aria-hidden
                />
              </span>
              <span className="mt-0.5 block text-[11px] leading-5 text-muted-foreground">
                {loading
                  ? "Jev está analizando el siguiente lote…"
                  : reviewing
                    ? `Revisando ${items.length} sugerencias · ${remaining ?? "?"} pendientes en cola`
                    : remaining != null
                      ? `${remaining} movimientos pendientes de clasificar`
                      : "Jev solo ve datos estructurados, nunca el extracto."}
              </span>
            </span>
          </button>

          <div className="flex items-center gap-4">
            <Meter
              label="Referencias"
              value={`${references}/${referenceCap}`}
              pct={referencePct}
              barClassName={referencePct >= 100 ? "bg-positive" : "bg-accent"}
              hint="Decisiones previas que se envían a Jev como ejemplo"
            />
            {initialPending ? (
              <Meter
                label="Sesión"
                value={`${sessionDone}/${initialPending}`}
                pct={progressPct}
                barClassName="bg-positive"
                hint={`${session.accepted} revisados · ${session.auto} autoaprobados · ${session.batches} lotes`}
              />
            ) : null}
            {reviewing ? (
              <Button variant="ghost" size="icon" onClick={closeBatch} aria-label="Cerrar lote">
                <X className="size-3.5" aria-hidden />
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      {collapsed ? null : loading && !reviewing ? (
        <LoadingState count={Math.min(batchSize, 5)} />
      ) : !reviewing ? (
        <IdleState
          batchSize={batchSize}
          onBatchSizeChange={setBatchSize}
          onStart={() => void nextBatch()}
          firstTime={!response}
          remaining={remaining}
        />
      ) : (
        <div className="animate-fade-in">
          {/* Barra de herramientas */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-2.5">
            <div className="flex items-center gap-1 rounded-lg bg-muted p-0.5 text-[11px]">
              <FilterTab active={filter === "all"} onClick={() => setFilter("all")}>
                Todos <Count>{items.length}</Count>
              </FilterTab>
              <FilterTab active={filter === "low"} onClick={() => setFilter("low")}>
                A revisar <Count>{counts.low}</Count>
              </FilterTab>
              <FilterTab
                active={filter === "uncategorized"}
                onClick={() => setFilter("uncategorized")}
              >
                Sin categoría <Count>{counts.uncategorized}</Count>
              </FilterTab>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
              {counts.rule > 0 ? <SourceChip item="rule" n={counts.rule} /> : null}
              {counts.memory > 0 ? <SourceChip item="memory" n={counts.memory} /> : null}
              {counts.jev > 0 ? <SourceChip item="decider" n={counts.jev} /> : null}
              <span className="mx-1 h-4 w-px bg-border" aria-hidden />
              <button
                type="button"
                className="rounded-md px-1.5 py-1 font-medium text-foreground hover:bg-muted"
                onClick={() => setAll("accept", (item) => confidenceTone(item.confianza) === "high")}
              >
                <Wand2 className="mr-1 inline size-3" aria-hidden />
                Aceptar ≥ {Math.round(HIGH_CONFIDENCE * 100)}%
              </button>
              <button
                type="button"
                className="rounded-md px-1.5 py-1 font-medium text-foreground hover:bg-muted"
                onClick={() => setAll("accept")}
              >
                Todos
              </button>
              <button
                type="button"
                className="rounded-md px-1.5 py-1 font-medium text-foreground hover:bg-muted"
                onClick={() => setAll("skip")}
              >
                Ninguno
              </button>
            </div>
          </div>

          {/* Lista */}
          <div
            role="listbox"
            aria-label="Sugerencias de clasificación"
            tabIndex={0}
            onKeyDown={onListKeyDown}
            className="max-h-[520px] space-y-1.5 overflow-y-auto p-3 outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:ring-inset"
          >
            {visibleItems.length === 0 ? (
              <p className="px-2 py-6 text-center text-[11px] text-muted-foreground">
                Nada en este filtro.
              </p>
            ) : (
              visibleItems.map((item, index) => (
                <SuggestionRow
                  key={item.movement_id}
                  ref={(node) => {
                    if (node) rowRefs.current.set(item.movement_id, node);
                    else rowRefs.current.delete(item.movement_id);
                  }}
                  item={item}
                  categories={categories}
                  focused={index === focused}
                  editing={editing === item.movement_id}
                  expanded={expanded.has(item.movement_id)}
                  onFocus={() => setFocused(index)}
                  onToggle={() => toggleDecision(item)}
                  onEdit={() =>
                    setEditing((current) =>
                      current === item.movement_id ? null : item.movement_id,
                    )
                  }
                  onExpand={() => toggleExpanded(item.movement_id)}
                  onCategory={(categoryId) => setCategory(item.movement_id, categoryId)}
                />
              ))
            )}
          </div>

          {/* Pie */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-muted/40 px-5 py-3">
            <div className="flex items-center gap-3 text-[11px]">
              <span className="inline-flex items-center gap-1 font-medium text-positive">
                <Check className="size-3" aria-hidden /> {toAccept.length} aceptar
              </span>
              <span className="inline-flex items-center gap-1 text-muted-foreground">
                <CircleSlash className="size-3" aria-hidden /> {items.length - toAccept.length}{" "}
                omitir
              </span>
              <span className="hidden items-center gap-1 text-muted-foreground md:inline-flex">
                <Keyboard className="size-3" aria-hidden />
                <Kbd>↑↓</Kbd> mover <Kbd>espacio</Kbd> aceptar/omitir <Kbd>e</Kbd> editar{" "}
                <Kbd>i</Kbd> detalle <Kbd>⌘↵</Kbd> guardar
              </span>
            </div>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void saveAndNext()}
              loading={saving != null || loading}
            >
              {saving ? (
                `Guardando ${saving.done}/${saving.total}`
              ) : (
                <>
                  <Check className="size-3.5" aria-hidden />
                  {toAccept.length > 0
                    ? `Aprobar ${toAccept.length} y siguiente lote`
                    : "Saltar al siguiente lote"}
                </>
              )}
            </Button>
          </div>
          {saving ? (
            <div className="h-0.5 bg-muted">
              <div
                className="h-full bg-accent transition-all"
                style={{ width: `${(saving.done / Math.max(saving.total, 1)) * 100}%` }}
              />
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}

/* ---------------------------------------------------------------- piezas */

function Meter({
  label,
  value,
  pct,
  barClassName,
  hint,
}: {
  label: string;
  value: string;
  pct: number;
  barClassName: string;
  hint?: string;
}) {
  return (
    <div className="hidden w-28 sm:block" title={hint}>
      <div className="flex items-baseline justify-between text-[10px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="num font-medium">{value}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all duration-500", barClassName)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function IdleState({
  batchSize,
  onBatchSizeChange,
  onStart,
  firstTime,
  remaining,
}: {
  batchSize: number;
  onBatchSizeChange: (value: number) => void;
  onStart: () => void;
  firstTime: boolean;
  remaining: number | null;
}) {
  const empty = remaining === 0;
  return (
    <div className="flex flex-col items-center gap-4 px-5 py-6 text-center sm:flex-row sm:text-left">
      <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-accent-soft text-accent">
        {empty ? <Check className="size-5" aria-hidden /> : <Sparkles className="size-5" aria-hidden />}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium">
          {empty
            ? "Todo clasificado"
            : firstTime
              ? "Deja que Jev proponga categorías"
              : "¿Seguimos con el siguiente lote?"}
        </p>
        <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">
          {empty
            ? "No quedan movimientos pendientes. Puedes volver a comprobar cuando importes más."
            : firstTime
              ? "Aplica reglas y memoria primero; Jev decide el resto. Tú revisas antes de aprobar."
              : "Cada lote aprobado mejora las referencias que recibe Jev."}
        </p>
      </div>
      <div className="flex flex-col items-center gap-2 sm:items-end">
        <div
          className="flex items-center gap-0.5 rounded-lg bg-muted p-0.5 text-[11px]"
          role="radiogroup"
          aria-label="Tamaño del lote"
        >
          {Array.from(new Set([...BATCH_SIZE_PRESETS, batchSize]))
            .sort((a, b) => a - b)
            .map((size) => (
              <button
                key={size}
                type="button"
                role="radio"
                aria-checked={size === batchSize}
                onClick={() => onBatchSizeChange(size)}
                className={cn(
                  "num h-6 min-w-8 rounded-md px-2 font-medium transition-colors",
                  size === batchSize
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {size}
              </button>
            ))}
        </div>
        <Button variant="primary" size="sm" onClick={onStart}>
          <Sparkles className="size-3.5" aria-hidden />
          {empty ? "Volver a comprobar" : firstTime ? "Clasificar con Jev" : "Siguiente lote"}
        </Button>
      </div>
    </div>
  );
}

function LoadingState({ count }: { count: number }) {
  return (
    <div className="space-y-1.5 p-3" aria-busy="true" aria-live="polite">
      {Array.from({ length: count }, (_, index) => (
        <div
          key={index}
          className="flex items-center gap-3 rounded-xl border border-border px-3 py-3"
          style={{ opacity: 1 - index * 0.15 }}
        >
          <Skeleton className="size-5 rounded-md" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3 w-40" />
            <Skeleton className="h-2.5 w-24" />
          </div>
          <Skeleton className="h-6 w-36 rounded-full" />
          <Skeleton className="h-3 w-16" />
        </div>
      ))}
    </div>
  );
}

function FilterTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-md px-2 font-medium transition-colors",
        active ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function Count({ children }: { children: ReactNode }) {
  return <span className="num text-[10px] text-muted-foreground">{children}</span>;
}

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-border bg-card px-1 font-sans text-[9px] font-medium text-foreground">
      {children}
    </kbd>
  );
}

function SourceChip({ item, n }: { item: string; n: number }) {
  const info = methodInfo({ method: item } as ClassificationBatchItem);
  const Icon = info.icon;
  return (
    <span className={cn("inline-flex h-5 items-center gap-1 rounded-md px-1.5 font-medium", info.className)}>
      <Icon className="size-3" aria-hidden />
      {n} {item === "decider" ? "Jev" : info.label.toLowerCase()}
    </span>
  );
}

function CategoryPill({ categories, categoryId }: { categories: Category[]; categoryId: number | null }) {
  const pair = categoryPair(categories, categoryId);
  if (!pair.root) {
    return (
      <span className="inline-flex h-6 items-center gap-1 rounded-full border border-dashed border-border px-2.5 text-[11px] text-muted-foreground">
        Elegir categoría
      </span>
    );
  }
  const color = pair.child?.color || pair.root.color;
  return (
    <span
      className="inline-flex h-6 max-w-full items-center gap-1.5 truncate rounded-full border px-2.5 text-[11px] font-medium"
      style={{
        borderColor: color ? `${color}55` : undefined,
        backgroundColor: color ? `${color}14` : undefined,
      }}
    >
      <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} aria-hidden />
      <span className="truncate">{pair.root.nombre}</span>
      {pair.child ? (
        <>
          <ChevronRight className="size-3 shrink-0 text-muted-foreground" aria-hidden />
          <span className="truncate text-muted-foreground">{pair.child.nombre}</span>
        </>
      ) : null}
    </span>
  );
}

const SuggestionRow = ({
  ref,
  item,
  categories,
  focused,
  editing,
  expanded,
  onFocus,
  onToggle,
  onEdit,
  onExpand,
  onCategory,
}: {
  ref: (node: HTMLDivElement | null) => void;
  item: ReviewItem;
  categories: Category[];
  focused: boolean;
  editing: boolean;
  expanded: boolean;
  onFocus: () => void;
  onToggle: () => void;
  onEdit: () => void;
  onExpand: () => void;
  onCategory: (categoryId: number | null) => void;
}) => {
  const accepted = item.decision === "accept" && item.categoria_id != null;
  const tone = confidenceTone(item.confianza);
  const info = methodInfo(item);
  const MethodIcon = info.icon;
  const amount = item.amount != null ? Number(item.amount) : null;
  const hasDetail = Boolean(item.explicacion || item.subtipo);

  return (
    <div
      ref={ref}
      role="option"
      aria-selected={focused}
      onMouseDown={onFocus}
      className={cn(
        "group rounded-xl border transition-all duration-150",
        accepted ? "border-border bg-card" : "border-dashed border-border bg-muted/30 opacity-70",
        focused && "ring-2 ring-accent/50 border-accent/50",
      )}
    >
      <div className="grid items-center gap-x-3 gap-y-2 px-3 py-2.5 sm:grid-cols-[auto_minmax(0,1fr)_minmax(0,220px)_88px_auto]">
        {/* Check */}
        <button
          type="button"
          onClick={onToggle}
          aria-label={accepted ? "Omitir" : "Aceptar"}
          className={cn(
            "flex size-5 items-center justify-center rounded-md border transition-colors",
            accepted
              ? "border-positive bg-positive text-white dark:text-background"
              : "border-border bg-card text-transparent hover:border-positive/60",
          )}
        >
          <Check className="size-3" aria-hidden />
        </button>

        {/* Merchant */}
        <div className="min-w-0">
          <p className={cn("truncate text-[12px] font-medium", !accepted && "line-through decoration-muted-foreground/40")}>
            {item.merchant ?? "Sin merchant"}
          </p>
          <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <span>{item.value_date ? formatDate(item.value_date, "short") : "—"}</span>
            <span aria-hidden>·</span>
            <span className="truncate">{item.kind}</span>
            <span className={cn("inline-flex items-center gap-1 rounded px-1 py-px font-medium", info.className)}>
              <MethodIcon className="size-2.5" aria-hidden />
              {info.label}
            </span>
            {item.edited ? (
              <span className="inline-flex items-center gap-0.5 text-info">
                <Pencil className="size-2.5" aria-hidden /> editado
              </span>
            ) : null}
          </div>
        </div>

        {/* Categoría */}
        <div className="min-w-0">
          {editing ? (
            <CategoryPairSelect
              categoryId={item.categoria_id}
              categories={categories}
              onChange={onCategory}
              ariaPrefix={item.merchant ?? "movimiento"}
              compact
            />
          ) : (
            <button type="button" onClick={onEdit} className="max-w-full text-left" title="Cambiar categoría (e)">
              <CategoryPill categories={categories} categoryId={item.categoria_id} />
            </button>
          )}
          {item.confianza != null ? (
            <div className="mt-1.5 flex items-center gap-1.5" title="Confianza de la sugerencia">
              <div className="h-1 w-16 overflow-hidden rounded-full bg-muted">
                <div
                  className={cn("h-full rounded-full", toneBar[tone])}
                  style={{ width: `${Math.round(item.confianza * 100)}%` }}
                />
              </div>
              <span className={cn("num text-[10px] font-medium", toneText[tone])}>
                {Math.round(item.confianza * 100)}%
              </span>
            </div>
          ) : null}
        </div>

        {/* Importe */}
        <span
          className={cn(
            "num text-right text-[12px] font-semibold",
            amount != null && amount > 0 ? "text-positive" : "text-foreground",
          )}
        >
          {item.amount != null ? formatMoney(item.amount, { signDisplay: "always" }) : "—"}
        </span>

        {/* Acciones */}
        <div className="flex items-center justify-end gap-0.5 opacity-60 transition-opacity group-hover:opacity-100">
          <IconAction label={editing ? "Cerrar edición" : "Editar categoría"} onClick={onEdit}>
            {editing ? <Undo2 className="size-3.5" aria-hidden /> : <Pencil className="size-3.5" aria-hidden />}
          </IconAction>
          {hasDetail ? (
            <IconAction label="Ver razonamiento" onClick={onExpand}>
              <ChevronDown className={cn("size-3.5 transition-transform", expanded && "rotate-180")} aria-hidden />
            </IconAction>
          ) : null}
        </div>
      </div>

      {expanded && hasDetail ? (
        <div className="animate-fade-in mx-3 mb-2.5 flex gap-2 rounded-lg bg-accent-soft/50 px-3 py-2 text-[11px] leading-5">
          <BrainCircuit className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
          <div className="min-w-0">
            {item.subtipo ? <p className="font-medium">Subtipo: {item.subtipo}</p> : null}
            {item.explicacion ? <p className="text-muted-foreground">{item.explicacion}</p> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
};

function IconAction({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      {children}
    </button>
  );
}
