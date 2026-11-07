"use client";

import { Loader2, Search, X } from "lucide-react";
import type { Account, Category, MovementKind } from "@/lib/types";
import { kindLabels } from "@/components/movements/constants";
import { childrenOf, rootCategories } from "@/lib/categories";
import { DateRangePicker } from "@/components/ui/date-picker";
import { SelectMenu } from "@/components/ui/select-menu";

export interface MovementFilterValues {
  account_id: string;
  kind: string;
  origen: string;
  categoria_id: string;
  subcategoria_id: string;
  from: string;
  to: string;
}

const origins: Array<{ value: string; label: string }> = [
  { value: "broker", label: "Broker" },
  { value: "rule", label: "Regla" },
  { value: "memory", label: "Memoria" },
  { value: "decider", label: "Jev" },
  { value: "llm", label: "LLM" },
  { value: "user", label: "Usuario" },
];

export function MovementFilters({
  search,
  onSearchChange,
  values,
  onFilterChange,
  onCategoryChange,
  onDateRangeChange,
  onClear,
  accounts,
  categories,
  hasFilters,
  isPending,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  values: MovementFilterValues;
  onFilterChange: (key: keyof MovementFilterValues, value: string) => void;
  onCategoryChange: (rootId: string, childId: string) => void;
  onDateRangeChange: (from: string, to: string) => void;
  onClear: () => void;
  accounts: Account[];
  categories: Category[];
  hasFilters: boolean;
  isPending: boolean;
}) {
  const subcategories = childrenOf(categories, Number(values.categoria_id) || null);
  const activeCount = [
    values.account_id,
    values.kind,
    values.origen,
    values.categoria_id,
    values.from || values.to,
  ].filter(Boolean).length;

  return (
    <div className="space-y-2.5">
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Buscar comercio, descripción o cuenta…"
          aria-label="Buscar movimientos"
          className="h-11 w-full rounded-xl border border-border bg-card pl-10 pr-10 text-[13px] shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:border-accent/50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/10"
        />
        <span className="absolute right-3 top-1/2 flex -translate-y-1/2 items-center">
          {isPending ? (
            <Loader2 className="size-4 animate-spin text-accent" aria-label="Actualizando" />
          ) : search ? (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              aria-label="Borrar búsqueda"
              className="flex size-6 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          ) : null}
        </span>
      </div>

      <div className="scrollbar-thin -mx-1 flex items-center gap-1.5 overflow-x-auto px-1 pb-0.5">
        <SelectMenu
          variant="pill"
          aria-label="Cuenta"
          placeholder="Cuenta"
          active={Boolean(values.account_id)}
          value={values.account_id}
          onValueChange={(value) => onFilterChange("account_id", value)}
          options={[
            { value: "", label: "Todas las cuentas" },
            ...accounts.map((account) => ({ value: String(account.id), label: account.nombre })),
          ]}
        />

        <SelectMenu
          variant="pill"
          aria-label="Tipo de movimiento"
          placeholder="Tipo"
          active={Boolean(values.kind)}
          value={values.kind}
          onValueChange={(value) => onFilterChange("kind", value)}
          options={[
            { value: "", label: "Todos los tipos" },
            ...(Object.keys(kindLabels) as MovementKind[]).map((kind) => ({
              value: kind,
              label: kindLabels[kind],
            })),
          ]}
        />

        <SelectMenu
          variant="pill"
          aria-label="Categoría"
          placeholder="Categoría"
          active={Boolean(values.categoria_id)}
          value={values.categoria_id}
          onValueChange={(value) => onCategoryChange(value, "")}
          options={[
            { value: "", label: "Todas las categorías" },
            ...rootCategories(categories).map((category) => ({
              value: String(category.id),
              label: category.nombre,
              color: category.color,
            })),
          ]}
        />

        {values.categoria_id && subcategories.length > 0 ? (
          <SelectMenu
            variant="pill"
            aria-label="Subcategoría"
            placeholder="Subcategoría"
            active={Boolean(values.subcategoria_id)}
            value={values.subcategoria_id}
            onValueChange={(value) => onCategoryChange(values.categoria_id, value)}
            options={[
              { value: "", label: "Todas las subcategorías" },
              ...subcategories.map((category) => ({
                value: String(category.id),
                label: category.nombre,
              })),
            ]}
          />
        ) : null}

        <SelectMenu
          variant="pill"
          aria-label="Origen de clasificación"
          placeholder="Origen"
          active={Boolean(values.origen)}
          value={values.origen}
          onValueChange={(value) => onFilterChange("origen", value)}
          options={[{ value: "", label: "Cualquier origen" }, ...origins]}
        />

        <DateRangePicker
          variant="pill"
          placeholder="Fechas"
          aria-label="Fechas"
          from={values.from}
          to={values.to}
          onChange={onDateRangeChange}
        />

        {hasFilters ? (
          <button
            type="button"
            onClick={onClear}
            className="inline-flex h-8 shrink-0 items-center gap-1 rounded-full px-3 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="size-3.5" aria-hidden />
            Limpiar{activeCount > 0 ? ` (${activeCount})` : ""}
          </button>
        ) : null}
      </div>
    </div>
  );
}
