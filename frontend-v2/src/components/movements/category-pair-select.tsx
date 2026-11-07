"use client";

import type { Category } from "@/lib/types";
import {
  categoryPair,
  childrenOf,
  defaultChild,
  rootCategories,
} from "@/lib/categories";
import { SelectMenu } from "@/components/ui/select-menu";
import { cn } from "@/lib/utils";

export function CategoryPairSelect({
  categoryId,
  categories,
  onChange,
  ariaPrefix = "Movimiento",
  className,
  compact = false,
  disabled = false,
  part = "both",
}: {
  categoryId: number | null | undefined;
  categories: Category[];
  onChange: (categoryId: number | null) => void;
  ariaPrefix?: string;
  className?: string;
  compact?: boolean;
  disabled?: boolean;
  part?: "both" | "root" | "child";
}) {
  const pair = categoryPair(categories, categoryId);
  const roots = rootCategories(categories);
  const activeChildren = childrenOf(categories, pair.root?.id ?? null);
  const currentRoot = pair.root;
  const currentChild = pair.child;
  const rootOptions =
    currentRoot && !currentRoot.activa && !roots.some((item) => item.id === currentRoot.id)
      ? [currentRoot, ...roots]
      : roots;
  const childOptions =
    currentChild &&
    !currentChild.activa &&
    !activeChildren.some((item) => item.id === currentChild.id)
      ? [...activeChildren, currentChild]
      : activeChildren;

  function changeRoot(value: string) {
    if (!value) {
      onChange(null);
      return;
    }
    const rootId = Number(value);
    const children = childrenOf(categories, rootId);
    if (children.length === 0) {
      onChange(rootId);
      return;
    }
    const child = defaultChild(children) ?? children[0];
    onChange(child?.id ?? rootId);
  }

  function changeChild(value: string) {
    if (!value) return;
    onChange(Number(value));
  }

  const showRoot = part !== "child";
  const showChild = part !== "root";
  const archived = (category: Category) => (category.activa ? "" : " (archivada)");

  return (
    <div
      className={cn(
        "min-w-0",
        part === "both" ? "grid grid-cols-2 gap-1" : "flex",
        compact ? "text-[10px]" : "text-[11px]",
        className,
      )}
    >
      {showRoot ? (
        <SelectMenu
          variant="inline"
          value={currentRoot ? String(currentRoot.id) : ""}
          onValueChange={changeRoot}
          disabled={disabled}
          aria-label={`Categoría de ${ariaPrefix}`}
          title={currentRoot?.path}
          placeholder="Sin categoría"
          className={cn("flex-1", !currentRoot && "text-muted-foreground")}
          options={[
            { value: "", label: "Sin categoría" },
            ...rootOptions.map((category) => ({
              value: String(category.id),
              label: `${category.nombre}${archived(category)}`,
              color: category.color,
              disabled: !category.activa,
            })),
          ]}
        />
      ) : null}

      {showChild ? (
        <SelectMenu
          variant="inline"
          value={currentChild ? String(currentChild.id) : ""}
          onValueChange={changeChild}
          disabled={disabled || !currentRoot || childOptions.length === 0}
          aria-label={`Subcategoría de ${ariaPrefix}`}
          title={currentChild?.path ?? pair.root?.path}
          placeholder={currentRoot && childOptions.length === 0 ? "—" : "Subcategoría"}
          className={cn("flex-1", !currentChild && "text-muted-foreground")}
          options={childOptions.map((category) => ({
            value: String(category.id),
            label: `${category.nombre}${archived(category)}`,
            disabled: !category.activa,
          }))}
        />
      ) : null}
    </div>
  );
}
