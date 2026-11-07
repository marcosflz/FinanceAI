"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderTree, Plus, RefreshCw, Tags } from "lucide-react";
import { categoriesApi, tagGroupsApi, tagsApi } from "@/lib/api";
import { DEMO_MODE, withMock } from "@/lib/demo";
import { mockCategories, mockTagGroups } from "@/lib/mock";
import type {
  Category,
  CategoryInput,
  Tag,
  TagGroup,
  TagGroupInput,
  TagGroupsResponse,
  TagInput,
} from "@/lib/types";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/feedback";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { CategoryTree } from "@/components/settings/category-tree";
import { TagTaxonomy } from "@/components/settings/tag-taxonomy";
import {
  CategoryEditor,
  TagEditor,
  TagGroupEditor,
  type CategoryDraft,
  type TagDraft,
  type TagGroupDraft,
} from "@/components/settings/taxonomy-editors";

const mockTagData: TagGroupsResponse = {
  items: mockTagGroups,
  ungrouped: [],
  total: mockTagGroups.reduce((sum, group) => sum + group.tags.length, 0),
};

const EMPTY_TAG_DATA: TagGroupsResponse = { items: [], ungrouped: [], total: 0 };

function defaultCategoryDraft(parent?: Category | null): CategoryDraft {
  const aplicaA = parent?.aplica_a ?? "gasto";
  return {
    nombre: "",
    parentId: parent ? String(parent.id) : "",
    aplicaA,
    tratamiento: parent?.tratamiento ?? "normal",
    color: parent?.color ?? "#6366f1",
    excluirKpis: parent
      ? parent.excluir_kpis || parent.tratamiento !== "normal"
      : false,
    orden: "100",
    systemKey: "",
    descripcion: "",
    activa: true,
  };
}

function collectDescendants(categories: Category[], categoryId: number): Set<number> {
  const children = new Map<number, number[]>();
  for (const category of categories) {
    if (category.parent_id == null) continue;
    const list = children.get(category.parent_id) ?? [];
    list.push(category.id);
    children.set(category.parent_id, list);
  }
  const blocked = new Set<number>([categoryId]);
  const stack = [categoryId];
  while (stack.length) {
    const current = stack.pop();
    if (current == null) continue;
    for (const child of children.get(current) ?? []) {
      if (!blocked.has(child)) {
        blocked.add(child);
        stack.push(child);
      }
    }
  }
  return blocked;
}

export function CategoriesSection() {
  const { toast } = useToast();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<"tree" | "tags">("tree");
  const [showInactive, setShowInactive] = useState(false);
  const [categoryDraft, setCategoryDraft] = useState<CategoryDraft | null>(null);
  const [groupDraft, setGroupDraft] = useState<TagGroupDraft | null>(null);
  const [tagDraft, setTagDraft] = useState<TagDraft | null>(null);
  const [saving, setSaving] = useState(false);

  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: () => withMock(() => categoriesApi.list(), { items: mockCategories }),
  });
  const tagGroupsQuery = useQuery({
    queryKey: ["tag-groups"],
    queryFn: () => withMock(() => tagGroupsApi.list(), mockTagData),
  });

  const categories = categoriesQuery.data?.items ?? [];
  const tagData = tagGroupsQuery.data ?? (DEMO_MODE ? mockTagData : EMPTY_TAG_DATA);
  const groups = tagData.items;
  const ungrouped = tagData.ungrouped;
  const totalTags = tagData.total;
  const refreshing = categoriesQuery.isFetching || tagGroupsQuery.isFetching;

  let parentOptions = categories.filter((category) => category.parent_id === null);
  if (categoryDraft?.id) {
    const blocked = collectDescendants(categories, categoryDraft.id);
    parentOptions = parentOptions.filter((category) => !blocked.has(category.id));
  }
  const editingHasChildren = Boolean(
    categoryDraft?.id &&
      categories.some((category) => category.parent_id === categoryDraft.id),
  );

  function refresh() {
    void categoriesQuery.refetch();
    void tagGroupsQuery.refetch();
  }

  function openCategoryCreate(parent?: Category | null) {
    setGroupDraft(null);
    setTagDraft(null);
    setCategoryDraft(defaultCategoryDraft(parent));
  }

  function openCategoryEdit(category: Category) {
    setGroupDraft(null);
    setTagDraft(null);
    setCategoryDraft({
      id: category.id,
      nombre: category.nombre,
      parentId: category.parent_id ? String(category.parent_id) : "",
      aplicaA: category.aplica_a,
      tratamiento: category.tratamiento,
      color: category.color,
      excluirKpis: category.excluir_kpis,
      orden: String(category.orden),
      systemKey: category.system_key ?? "",
      descripcion: category.descripcion ?? "",
      activa: category.activa,
    });
  }

  async function saveCategory() {
    if (!categoryDraft || saving) return;
    const name = categoryDraft.nombre.trim();
    if (!name) {
      toast({ title: "Falta el nombre", variant: "error" });
      return;
    }
    setSaving(true);
    const payload: CategoryInput = {
      nombre: name,
      parent_id: categoryDraft.parentId ? Number(categoryDraft.parentId) : null,
      aplica_a: categoryDraft.aplicaA,
      tratamiento: categoryDraft.tratamiento,
      color: categoryDraft.color,
      excluir_kpis: categoryDraft.excluirKpis,
      orden: Number(categoryDraft.orden) || 100,
      system_key: categoryDraft.systemKey.trim() || null,
      descripcion: categoryDraft.descripcion.trim() || null,
      activa: categoryDraft.activa,
    };
    try {
      if (categoryDraft.id) await categoriesApi.update(categoryDraft.id, payload);
      else await categoriesApi.create(payload);
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
      toast({
        title: categoryDraft.id ? "Categoría actualizada" : "Categoría creada",
        description: name,
        variant: "success",
      });
      setCategoryDraft(null);
    } catch (error) {
      toast({
        title: "No se pudo guardar la categoría",
        description: error instanceof Error ? error.message : "Error desconocido",
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  async function deleteCategory(category: Category) {
    const ok = await confirm({
      title: `¿Borrar la categoría «${category.path}»?`,
      description: "Solo es posible si ningún movimiento, regla o subcategoría la usa.",
      confirmLabel: "Borrar categoría",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await categoriesApi.remove(category.id);
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
      toast({ title: "Categoría borrada", description: category.nombre, variant: "success" });
    } catch (error) {
      toast({
        title: "No se pudo borrar la categoría",
        description: error instanceof Error ? error.message : "Error desconocido",
        variant: "error",
      });
    }
  }

  function openGroupCreate() {
    setCategoryDraft(null);
    setTagDraft(null);
    setGroupDraft({ nombre: "", color: "#6366f1", orden: "100" });
  }

  function openGroupEdit(group: TagGroup) {
    setCategoryDraft(null);
    setTagDraft(null);
    setGroupDraft({
      id: group.id,
      nombre: group.nombre,
      color: group.color,
      orden: String(group.orden),
    });
  }

  async function saveGroup() {
    if (!groupDraft || saving) return;
    const name = groupDraft.nombre.trim();
    if (!name) {
      toast({ title: "Falta el nombre del grupo", variant: "error" });
      return;
    }
    setSaving(true);
    const payload: TagGroupInput = {
      nombre: name,
      color: groupDraft.color,
      orden: Number(groupDraft.orden) || 100,
    };
    try {
      if (groupDraft.id) await tagGroupsApi.update(groupDraft.id, payload);
      else await tagGroupsApi.create(payload);
      await queryClient.invalidateQueries({ queryKey: ["tag-groups"] });
      toast({
        title: groupDraft.id ? "Grupo actualizado" : "Grupo creado",
        description: name,
        variant: "success",
      });
      setGroupDraft(null);
    } catch (error) {
      toast({
        title: "No se pudo guardar el grupo",
        description: error instanceof Error ? error.message : "Error desconocido",
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  async function deleteGroup(group: TagGroup) {
    const ok = await confirm({
      title: `¿Borrar el grupo «${group.nombre}»?`,
      description: "Sus etiquetas no se borran: quedarán sin grupo.",
      confirmLabel: "Borrar grupo",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await tagGroupsApi.remove(group.id);
      await queryClient.invalidateQueries({ queryKey: ["tag-groups"] });
      toast({ title: "Grupo borrado", description: group.nombre, variant: "success" });
    } catch (error) {
      toast({
        title: "No se pudo borrar el grupo",
        description: error instanceof Error ? error.message : "Error desconocido",
        variant: "error",
      });
    }
  }

  function openTagCreate(group: TagGroup | null) {
    setCategoryDraft(null);
    setGroupDraft(null);
    setTagDraft({
      nombre: "",
      groupId: group ? String(group.id) : "",
      color: group?.color ?? "#6366f1",
      orden: "100",
      descripcion: "",
      activa: true,
    });
  }

  function openTagEdit(tag: Tag) {
    setCategoryDraft(null);
    setGroupDraft(null);
    setTagDraft({
      id: tag.id,
      nombre: tag.nombre,
      groupId: tag.group_id ? String(tag.group_id) : "",
      color: tag.color,
      orden: String(tag.orden),
      descripcion: tag.descripcion ?? "",
      activa: tag.activa,
    });
  }

  async function saveTag() {
    if (!tagDraft || saving) return;
    const name = tagDraft.nombre.trim();
    if (!name) {
      toast({ title: "Falta el nombre de la etiqueta", variant: "error" });
      return;
    }
    setSaving(true);
    const payload: TagInput = {
      nombre: name,
      color: tagDraft.color,
      descripcion: tagDraft.descripcion.trim() || null,
      group_id: tagDraft.groupId ? Number(tagDraft.groupId) : null,
      orden: Number(tagDraft.orden) || 100,
      activa: tagDraft.activa,
    };
    try {
      if (tagDraft.id) await tagsApi.update(tagDraft.id, payload);
      else await tagsApi.create(payload);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["tag-groups"] }),
        queryClient.invalidateQueries({ queryKey: ["tags"] }),
      ]);
      toast({
        title: tagDraft.id ? "Etiqueta actualizada" : "Etiqueta creada",
        description: name,
        variant: "success",
      });
      setTagDraft(null);
    } catch (error) {
      toast({
        title: "No se pudo guardar la etiqueta",
        description: error instanceof Error ? error.message : "Error desconocido",
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  }

  async function deleteTag(tag: Tag) {
    const ok = await confirm({
      title: `¿Borrar la etiqueta «${tag.nombre}»?`,
      description: "Solo es posible si ningún movimiento la usa.",
      confirmLabel: "Borrar etiqueta",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await tagsApi.remove(tag.id);
      await queryClient.invalidateQueries({ queryKey: ["tag-groups"] });
      toast({ title: "Etiqueta borrada", description: tag.nombre, variant: "success" });
    } catch (error) {
      toast({
        title: "No se pudo borrar la etiqueta",
        description: error instanceof Error ? error.message : "Error desconocido",
        variant: "error",
      });
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader className="py-3">
        <div>
          <CardTitle>Categorías y etiquetas</CardTitle>
          <CardDescription>
            Taxonomía editable: tipología, jerarquía, tratamiento y etiquetas libres.
            Los cambios se aplican al instante; las reasignaciones de movimientos se
            harán después con vista previa.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={refresh}
            loading={refreshing}
            aria-label="Recargar taxonomía"
          >
            <RefreshCw className="size-3.5" aria-hidden />
          </Button>
          {activeTab === "tree" ? (
            <Button
              variant="primary"
              size="sm"
              onClick={() => openCategoryCreate(null)}
            >
              <Plus className="size-3.5" aria-hidden />
              Nueva raíz
            </Button>
          ) : (
            <Button variant="primary" size="sm" onClick={openGroupCreate}>
              <Plus className="size-3.5" aria-hidden />
              Nuevo grupo
            </Button>
          )}
        </div>
      </CardHeader>

      <div className="flex items-center gap-1 border-y border-border bg-subtle px-2 py-1.5">
        <button
          type="button"
          onClick={() => setActiveTab("tree")}
          aria-current={activeTab === "tree" ? "page" : undefined}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium transition-colors",
            activeTab === "tree"
              ? "bg-card text-foreground shadow-sm"
              : "text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          <FolderTree className="size-3.5" aria-hidden />
          Árbol
          <Badge variant="outline">{categories.length}</Badge>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("tags")}
          aria-current={activeTab === "tags" ? "page" : undefined}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium transition-colors",
            activeTab === "tags"
              ? "bg-card text-foreground shadow-sm"
              : "text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          <Tags className="size-3.5" aria-hidden />
          Etiquetas
          <Badge variant="outline">{totalTags}</Badge>
        </button>
        {activeTab === "tree" ? (
          <label className="ml-auto inline-flex cursor-pointer items-center gap-1.5 pr-1 text-[10px] text-muted-foreground">
            <Checkbox
              checked={showInactive}
              onChange={(event) => setShowInactive(event.target.checked)}
            />
            Ver archivadas
          </label>
        ) : null}
      </div>

      {activeTab === "tree" ? (
        <>
          {categoryDraft ? (
            <CategoryEditor
              draft={categoryDraft}
              parentOptions={parentOptions}
              parentDisabled={editingHasChildren}
              saving={saving}
              onChange={setCategoryDraft}
              onCancel={() => setCategoryDraft(null)}
              onSubmit={() => void saveCategory()}
            />
          ) : null}
          {categoriesQuery.isLoading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 8 }).map((_, index) => (
                <Skeleton key={index} className="h-8 w-full" />
              ))}
            </div>
          ) : (
            <CategoryTree
              categories={categories}
              showInactive={showInactive}
              onEdit={openCategoryEdit}
              onAddChild={(category) => openCategoryCreate(category)}
              onDelete={(category) => void deleteCategory(category)}
            />
          )}
        </>
      ) : (
        <div className="space-y-3 p-3">
          {groupDraft ? (
            <TagGroupEditor
              draft={groupDraft}
              saving={saving}
              onChange={setGroupDraft}
              onCancel={() => setGroupDraft(null)}
              onSubmit={() => void saveGroup()}
            />
          ) : null}
          {tagDraft ? (
            <TagEditor
              draft={tagDraft}
              groups={groups}
              saving={saving}
              onChange={setTagDraft}
              onCancel={() => setTagDraft(null)}
              onSubmit={() => void saveTag()}
            />
          ) : null}
          {tagGroupsQuery.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, index) => (
                <Skeleton key={index} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <TagTaxonomy
              groups={groups}
              ungrouped={ungrouped}
              onCreateGroup={openGroupCreate}
              onEditGroup={openGroupEdit}
              onDeleteGroup={(group) => void deleteGroup(group)}
              onAddTag={openTagCreate}
              onEditTag={openTagEdit}
              onDeleteTag={(tag) => void deleteTag(tag)}
            />
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-2.5 text-[10px] text-muted-foreground">
        <Tags className="size-3" aria-hidden />
        Las categorías con tratamiento transferencia o inversión quedan excluidas de los
        KPIs. Las etiquetas agrupan movimientos de forma transversal; no son categorías.
      </div>
    </Card>
  );
}
