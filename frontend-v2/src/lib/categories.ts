import type { Category } from "@/lib/types";

export interface CategoryPair {
  root: Category | null;
  child: Category | null;
}

export function categoryById(
  categories: Category[],
  id: number | null | undefined,
): Category | null {
  if (id == null) return null;
  return categories.find((category) => category.id === id) ?? null;
}

export function rootCategories(
  categories: Category[],
  includeInactive = false,
): Category[] {
  return categories
    .filter(
      (category) =>
        category.parent_id === null && (includeInactive || category.activa),
    )
    .sort((a, b) => a.orden - b.orden || a.nombre.localeCompare(b.nombre));
}

export function childrenOf(
  categories: Category[],
  rootId: number | null | undefined,
  includeInactive = false,
): Category[] {
  if (rootId == null) return [];
  return categories
    .filter(
      (category) =>
        category.parent_id === rootId && (includeInactive || category.activa),
    )
    .sort((a, b) => a.orden - b.orden || a.nombre.localeCompare(b.nombre));
}

export function categoryPair(
  categories: Category[],
  categoryId: number | null | undefined,
): CategoryPair {
  const category = categoryById(categories, categoryId);
  if (!category) return { root: null, child: null };
  if (category.parent_id === null) {
    return { root: category, child: null };
  }
  return {
    root: categoryById(categories, category.parent_id),
    child: category,
  };
}

export function defaultChild(children: Category[]): Category | null {
  return (
    children.find((category) => category.es_default && category.activa) ??
    children.find((category) => category.activa) ??
    null
  );
}

export function categoryLabel(
  category: Category | null | undefined,
  fallback = "—",
): string {
  return category?.nombre ?? fallback;
}
