"use client";

import { useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FolderTree,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import type { Category } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

function aplicaLabel(value: Category["aplica_a"]): string {
  if (value === "gasto") return "Gasto";
  if (value === "ingreso") return "Ingreso";
  return "Compartida";
}

function aplicaVariant(value: Category["aplica_a"]): "neutral" | "positive" | "info" {
  if (value === "gasto") return "neutral";
  if (value === "ingreso") return "positive";
  return "info";
}

export function CategoryTree({
  categories,
  showInactive,
  onEdit,
  onAddChild,
  onDelete,
}: {
  categories: Category[];
  showInactive: boolean;
  onEdit: (category: Category) => void;
  onAddChild: (category: Category) => void;
  onDelete: (category: Category) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());

  const visibleIds = useMemo(() => {
    if (showInactive) return new Set(categories.map((category) => category.id));
    const byId = new Map(categories.map((category) => [category.id, category]));
    const visible = new Set<number>();
    for (const category of categories) {
      if (!category.activa) continue;
      let current: Category | undefined = category;
      let guard = 0;
      while (current && guard < 32) {
        visible.add(current.id);
        current = current.parent_id ? byId.get(current.parent_id) : undefined;
        guard += 1;
      }
    }
    return visible;
  }, [categories, showInactive]);

  const visibleCategories = useMemo(
    () => categories.filter((category) => visibleIds.has(category.id)),
    [categories, visibleIds],
  );

  const byParent = useMemo(() => {
    const map = new Map<number | null, Category[]>();
    for (const category of visibleCategories) {
      const key = category.parent_id ?? null;
      const list = map.get(key) ?? [];
      list.push(category);
      map.set(key, list);
    }
    for (const list of map.values()) {
      list.sort((a, b) => a.orden - b.orden || a.nombre.localeCompare(b.nombre));
    }
    return map;
  }, [visibleCategories]);

  const visibleRoots = useMemo(() => {
    const roots = byParent.get(null) ?? [];
    const known = new Set(visibleCategories.map((category) => category.id));
    const orphanIds = visibleCategories.filter(
      (category) => category.parent_id !== null && !known.has(category.parent_id),
    );
    const extra = orphanIds.filter(
      (category) => !roots.some((root) => root.id === category.id),
    );
    return [...roots, ...extra];
  }, [byParent, visibleCategories]);

  if (visibleCategories.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
        <FolderTree className="size-5 text-muted-foreground" aria-hidden />
        <p className="text-[12px] font-medium">
          {categories.length === 0
            ? "Todavía no hay categorías"
            : "Todas las categorías están archivadas"}
        </p>
        <p className="text-[11px] text-muted-foreground">
          {categories.length === 0
            ? "Crea una categoría raíz para empezar a organizar la taxonomía."
            : "Activa «Ver archivadas» para gestionarlas o crear una nueva."}
        </p>
      </div>
    );
  }

  function toggle(categoryId: number) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(categoryId)) next.delete(categoryId);
      else next.add(categoryId);
      return next;
    });
  }

  function renderNode(category: Category) {
    const children = byParent.get(category.id) ?? [];
    const hasChildren = children.length > 0;
    const isCollapsed = collapsed.has(category.id);
    const isInactive = !category.activa;

    return (
      <div key={category.id} className="border-b border-border/70 last:border-b-0">
        <div className="group flex min-h-9 items-center gap-2 py-1 pr-2 transition-colors hover:bg-muted/40">
          <div
            className="flex min-w-0 flex-1 items-center gap-1.5"
            style={{ paddingLeft: `${category.depth * 18 + 8}px` }}
          >
            {hasChildren ? (
              <button
                type="button"
                onClick={() => toggle(category.id)}
                className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={isCollapsed ? `Expandir ${category.nombre}` : `Contraer ${category.nombre}`}
                aria-expanded={!isCollapsed}
              >
                {isCollapsed ? (
                  <ChevronRight className="size-3.5" aria-hidden />
                ) : (
                  <ChevronDown className="size-3.5" aria-hidden />
                )}
              </button>
            ) : (
              <span className="size-5 shrink-0" aria-hidden />
            )}

            <span
              className="size-2.5 shrink-0 rounded-[3px] border border-black/10"
              style={{ backgroundColor: category.color }}
              aria-hidden
            />

            <button
              type="button"
              onClick={() => onEdit(category)}
              className="min-w-0 truncate text-left text-[12px] font-medium text-foreground hover:underline"
              title={category.path}
            >
              {category.nombre}
            </button>

            <Badge variant={aplicaVariant(category.aplica_a)}>
              {aplicaLabel(category.aplica_a)}
            </Badge>
            {category.tratamiento !== "normal" ? (
              <Badge variant="warning">
                {category.tratamiento === "transferencia" ? "Transferencia" : "Inversión"}
              </Badge>
            ) : null}
            {category.es_default ? (
              <Badge variant="accent">Por defecto</Badge>
            ) : null}
            {!category.assignable && category.activa ? (
              <Badge variant="outline">Agrupadora</Badge>
            ) : null}
            {category.excluir_kpis ? (
              <Badge variant="outline" className="hidden sm:inline-flex">
                Sin KPIs
              </Badge>
            ) : null}
            {isInactive ? <Badge variant="outline">Archivada</Badge> : null}
            {category.system_key ? (
              <code className="num hidden rounded bg-muted px-1 py-0.5 text-[9px] text-muted-foreground lg:inline">
                {category.system_key}
              </code>
            ) : null}
          </div>

          <div className="flex shrink-0 items-center gap-3 text-[10px] text-muted-foreground">
            <span
              className="hidden text-right sm:inline"
              title={`${category.usage_count} directos · ${category.usage_total} incluyendo subcategorías`}
            >
              {category.usage_total} mov.
            </span>
            <span className="hidden text-right lg:inline" title="Reglas que apuntan a esta categoría">
              {category.rule_total} reglas
            </span>
            <div className="flex items-center gap-0.5">
              {category.depth === 0 ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-6"
                  onClick={() => onAddChild(category)}
                  aria-label={`Añadir subcategoría a ${category.nombre}`}
                  title="Añadir subcategoría"
                >
                  <Plus className="size-3" aria-hidden />
                </Button>
              ) : null}
              <Button
                variant="ghost"
                size="icon"
                className="size-6"
                onClick={() => onEdit(category)}
                aria-label={`Editar ${category.nombre}`}
                title="Editar"
              >
                <Pencil className="size-3" aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-6 hover:text-negative"
                onClick={() => onDelete(category)}
                aria-label={`Borrar ${category.nombre}`}
                title="Borrar"
              >
                <Trash2 className="size-3" aria-hidden />
              </Button>
            </div>
          </div>
        </div>

        {hasChildren && !isCollapsed
          ? children.map((child) => renderNode(child))
          : null}
      </div>
    );
  }

  return (
    <div role="tree" aria-label="Árbol de categorías" className="text-[12px]">
      {visibleRoots.map((category) => renderNode(category))}
    </div>
  );
}
