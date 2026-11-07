"use client";

import { Pencil, Plus, Tags, Trash2 } from "lucide-react";
import type { Tag, TagGroup } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

function TagChip({
  tag,
  onEdit,
  onDelete,
}: {
  tag: Tag;
  onEdit: (tag: Tag) => void;
  onDelete: (tag: Tag) => void;
}) {
  return (
    <span
      className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-card py-0.5 pl-2 pr-1 text-[11px]"
      title={tag.descripcion ?? tag.nombre}
    >
      <span
        className="size-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: tag.color }}
        aria-hidden
      />
      <span className={tag.activa ? "truncate font-medium" : "truncate text-muted-foreground line-through"}>
        {tag.nombre}
      </span>
      {tag.usage_count > 0 ? (
        <span className="num text-[9px] text-muted-foreground">{tag.usage_count}</span>
      ) : null}
      <button
        type="button"
        className="flex size-4 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
        onClick={() => onEdit(tag)}
        aria-label={`Editar etiqueta ${tag.nombre}`}
        title="Editar"
      >
        <Pencil className="size-2.5" aria-hidden />
      </button>
      <button
        type="button"
        className="flex size-4 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-negative"
        onClick={() => onDelete(tag)}
        aria-label={`Borrar etiqueta ${tag.nombre}`}
        title="Borrar"
      >
        <Trash2 className="size-2.5" aria-hidden />
      </button>
    </span>
  );
}

export function TagTaxonomy({
  groups,
  ungrouped,
  onCreateGroup,
  onEditGroup,
  onDeleteGroup,
  onAddTag,
  onEditTag,
  onDeleteTag,
}: {
  groups: TagGroup[];
  ungrouped: Tag[];
  onCreateGroup: () => void;
  onEditGroup: (group: TagGroup) => void;
  onDeleteGroup: (group: TagGroup) => void;
  onAddTag: (group: TagGroup | null) => void;
  onEditTag: (tag: Tag) => void;
  onDeleteTag: (tag: Tag) => void;
}) {
  const totalTags = groups.reduce((sum, group) => sum + group.tags.length, 0) + ungrouped.length;

  if (groups.length === 0 && ungrouped.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
        <Tags className="size-5 text-muted-foreground" aria-hidden />
        <p className="text-[12px] font-medium">Todavía no hay etiquetas</p>
        <p className="text-[11px] text-muted-foreground">
          Crea un grupo y añade etiquetas libres para clasificar movimientos.
        </p>
        <div className="mt-2 flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={onCreateGroup}>
            <Plus className="size-3.5" aria-hidden />
            Nuevo grupo
          </Button>
          <Button variant="primary" size="sm" onClick={() => onAddTag(null)}>
            <Plus className="size-3.5" aria-hidden />
            Nueva etiqueta
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] text-muted-foreground">
          {totalTags} etiquetas en {groups.length} grupos. Los grupos son opcionales.
        </p>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={onCreateGroup}>
            <Plus className="size-3.5" aria-hidden />
            Nuevo grupo
          </Button>
          <Button variant="primary" size="sm" onClick={() => onAddTag(null)}>
            <Plus className="size-3.5" aria-hidden />
            Nueva etiqueta
          </Button>
        </div>
      </div>

      {groups.map((group) => (
        <div key={group.id} className="overflow-hidden rounded-lg border border-border bg-card">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-subtle/50 px-3 py-2">
            <div className="flex min-w-0 items-center gap-2">
              <span
                className="size-2.5 rounded-[3px]"
                style={{ backgroundColor: group.color }}
                aria-hidden
              />
              <span className="truncate text-[12px] font-semibold">{group.nombre}</span>
              <Badge variant="outline">{group.tags.length}</Badge>
            </div>
            <div className="flex items-center gap-0.5">
              <Button
                variant="ghost"
                size="icon"
                className="size-6"
                onClick={() => onAddTag(group)}
                aria-label={`Añadir etiqueta a ${group.nombre}`}
                title="Añadir etiqueta"
              >
                <Plus className="size-3" aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-6"
                onClick={() => onEditGroup(group)}
                aria-label={`Editar grupo ${group.nombre}`}
                title="Editar grupo"
              >
                <Pencil className="size-3" aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-6 hover:text-negative"
                onClick={() => onDeleteGroup(group)}
                aria-label={`Borrar grupo ${group.nombre}`}
                title="Borrar grupo (las etiquetas quedan sin grupo)"
              >
                <Trash2 className="size-3" aria-hidden />
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5 p-2.5">
            {group.tags.length === 0 ? (
              <p className="px-1 py-1 text-[10px] text-muted-foreground">
                Sin etiquetas todavía. Añade una con el botón +.
              </p>
            ) : (
              group.tags.map((tag) => (
                <TagChip
                  key={tag.id}
                  tag={tag}
                  onEdit={onEditTag}
                  onDelete={onDeleteTag}
                />
              ))
            )}
          </div>
        </div>
      ))}

      <div className="overflow-hidden rounded-lg border border-dashed border-border bg-card">
        <div className="flex items-center justify-between gap-2 border-b border-border/70 px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-semibold">Sin grupo</span>
            <Badge variant="outline">{ungrouped.length}</Badge>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="size-6"
            onClick={() => onAddTag(null)}
            aria-label="Añadir etiqueta sin grupo"
            title="Añadir etiqueta sin grupo"
          >
            <Plus className="size-3" aria-hidden />
          </Button>
        </div>
        <div className="flex flex-wrap gap-1.5 p-2.5">
          {ungrouped.length === 0 ? (
            <p className="px-1 py-1 text-[10px] text-muted-foreground">
              Las etiquetas sin grupo aparecerán aquí.
            </p>
          ) : (
            ungrouped.map((tag) => (
              <TagChip
                key={tag.id}
                tag={tag}
                onEdit={onEditTag}
                onDelete={onDeleteTag}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
