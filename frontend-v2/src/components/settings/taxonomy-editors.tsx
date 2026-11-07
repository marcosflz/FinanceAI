"use client";

import type { Category, CategoryAplicaA, CategoryTratamiento, TagGroup } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/form";
import { ColorField } from "@/components/ui/color-field";
import { cn } from "@/lib/utils";

export interface CategoryDraft {
  id?: number;
  nombre: string;
  parentId: string;
  aplicaA: CategoryAplicaA;
  tratamiento: CategoryTratamiento;
  color: string;
  excluirKpis: boolean;
  orden: string;
  systemKey: string;
  descripcion: string;
  activa: boolean;
}

export interface TagGroupDraft {
  id?: number;
  nombre: string;
  color: string;
  orden: string;
}

export interface TagDraft {
  id?: number;
  nombre: string;
  groupId: string;
  color: string;
  orden: string;
  descripcion: string;
  activa: boolean;
}

const labelClass = "inline-flex cursor-pointer items-center gap-2 text-[11px] text-muted-foreground";

export function CategoryEditor({
  draft,
  parentOptions,
  parentDisabled = false,
  saving,
  onChange,
  onCancel,
  onSubmit,
}: {
  draft: CategoryDraft;
  parentOptions: Category[];
  parentDisabled?: boolean;
  saving: boolean;
  onChange: (draft: CategoryDraft) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const set = <K extends keyof CategoryDraft>(key: K, value: CategoryDraft[K]) =>
    onChange({ ...draft, [key]: value });
  const parent = parentOptions.find(
    (category) => String(category.id) === draft.parentId,
  );
  const isChild = Boolean(draft.parentId);

  return (
    <form
      className="border-b border-border bg-subtle/40 px-4 py-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <p className="text-[12px] font-semibold">
            {draft.id ? "Editar categoría" : "Nueva categoría"}
          </p>
          <p className="text-[10px] text-muted-foreground">
            Máximo dos niveles: categoría y subcategoría. Las subcategorías
            heredan el tratamiento y la exclusión de KPIs de su categoría.
          </p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Nombre" className="sm:col-span-2">
          <Input
            value={draft.nombre}
            onChange={(event) => set("nombre", event.target.value)}
            placeholder="Ej. Supermercado"
            autoFocus
          />
        </Field>

        <Field
          label="Categoría raíz"
          className="sm:col-span-2"
          hint={
            parentDisabled
              ? "Esta categoría tiene subcategorías; no se puede convertir en subcategoría."
              : "Déjalo vacío para crear una categoría raíz."
          }
        >
          <Select
            value={draft.parentId}
            disabled={parentDisabled}
            onChange={(event) => {
              const nextParent = parentOptions.find(
                (category) => String(category.id) === event.target.value,
              );
              onChange({
                ...draft,
                parentId: event.target.value,
                aplicaA: nextParent?.aplica_a ?? draft.aplicaA,
                tratamiento: nextParent?.tratamiento ?? draft.tratamiento,
                excluirKpis: nextParent
                  ? nextParent.excluir_kpis ||
                    nextParent.tratamiento !== "normal"
                  : draft.excluirKpis,
              });
            }}
          >
            <option value="">Sin padre (categoría raíz)</option>
            {parentOptions.map((category) => (
              <option key={category.id} value={category.id}>
                {category.nombre}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Tipología">
          <Select
            value={draft.aplicaA}
            onChange={(event) => set("aplicaA", event.target.value as CategoryAplicaA)}
          >
            <option value="gasto">Gasto</option>
            <option value="ingreso">Ingreso</option>
            <option value="ambos">Compartida (gasto e ingreso)</option>
          </Select>
        </Field>

        <Field
          label="Tratamiento"
          hint={
            isChild
              ? `Heredado de ${parent?.nombre ?? "la raíz"}`
              : draft.tratamiento !== "normal"
                ? "Transferencias e inversiones se excluyen automáticamente de los KPIs."
                : undefined
          }
        >
          <Select
            value={draft.tratamiento}
            disabled={isChild}
            onChange={(event) => {
              const tratamiento = event.target.value as CategoryTratamiento;
              onChange({
                ...draft,
                tratamiento,
                // Al volver a Normal se incluye en KPIs por defecto; si se
                // quiere mantener excluida, se puede volver a marcar.
                excluirKpis: tratamiento !== "normal",
              });
            }}
          >
            <option value="normal">Normal</option>
            <option value="transferencia">Transferencia</option>
            <option value="inversion">Inversión</option>
          </Select>
        </Field>

        <Field label="Color">
          <ColorField
            value={draft.color}
            onChange={(value) => set("color", value)}
            aria-label="Color de la categoría"
          />
        </Field>

        <Field label="Orden">
          <Input
            type="number"
            value={draft.orden}
            onChange={(event) => set("orden", event.target.value)}
            min={0}
          />
        </Field>

        <Field label="Clave de sistema" hint="Opcional. No cambia al renombrar.">
          <Input
            value={draft.systemKey}
            onChange={(event) => set("systemKey", event.target.value)}
            placeholder="transferencias"
          />
        </Field>

        <Field label="Descripción" className="sm:col-span-2 lg:col-span-3">
          <Textarea
            value={draft.descripcion}
            onChange={(event) => set("descripcion", event.target.value)}
            placeholder="Para qué se usa esta categoría…"
            className="min-h-16"
          />
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <label className={labelClass}>
            <Checkbox
              checked={draft.excluirKpis}
              disabled={
                isChild || draft.tratamiento !== "normal"
              }
              onChange={(event) => set("excluirKpis", event.target.checked)}
            />
            Excluir de KPIs
            {isChild ? (
              <span className="text-[10px] text-muted-foreground">
                (heredado de la raíz)
              </span>
            ) : draft.tratamiento !== "normal" ? (
              <span className="text-[10px] text-muted-foreground">
                (automático por tratamiento)
              </span>
            ) : null}
          </label>
          <label className={labelClass}>
            <Checkbox
              checked={draft.activa}
              onChange={(event) => set("activa", event.target.checked)}
            />
            Activa
          </label>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={saving}>
            Cancelar
          </Button>
          <Button variant="primary" size="sm" type="submit" loading={saving}>
            Guardar categoría
          </Button>
        </div>
      </div>
    </form>
  );
}

export function TagGroupEditor({
  draft,
  saving,
  onChange,
  onCancel,
  onSubmit,
}: {
  draft: TagGroupDraft;
  saving: boolean;
  onChange: (draft: TagGroupDraft) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  return (
    <form
      className="rounded-lg border border-border bg-subtle/40 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <p className="mb-3 text-[12px] font-semibold">
        {draft.id ? "Editar grupo" : "Nuevo grupo de etiquetas"}
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Nombre">
          <Input
            value={draft.nombre}
            onChange={(event) => onChange({ ...draft, nombre: event.target.value })}
            placeholder="Ej. Viajes"
            autoFocus
          />
        </Field>
        <Field label="Color">
          <ColorField
            value={draft.color}
            onChange={(value) => onChange({ ...draft, color: value })}
            aria-label="Color del grupo"
          />
        </Field>
        <Field label="Orden">
          <Input
            type="number"
            value={draft.orden}
            onChange={(event) => onChange({ ...draft, orden: event.target.value })}
            min={0}
          />
        </Field>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={saving}>
          Cancelar
        </Button>
        <Button variant="primary" size="sm" type="submit" loading={saving}>
          Guardar grupo
        </Button>
      </div>
    </form>
  );
}

export function TagEditor({
  draft,
  groups,
  saving,
  onChange,
  onCancel,
  onSubmit,
}: {
  draft: TagDraft;
  groups: TagGroup[];
  saving: boolean;
  onChange: (draft: TagDraft) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  return (
    <form
      className="rounded-lg border border-border bg-subtle/40 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <p className="mb-3 text-[12px] font-semibold">
        {draft.id ? "Editar etiqueta" : "Nueva etiqueta"}
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Nombre">
          <Input
            value={draft.nombre}
            onChange={(event) => onChange({ ...draft, nombre: event.target.value })}
            placeholder="Ej. Korea 2026"
            autoFocus
          />
        </Field>
        <Field label="Grupo">
          <Select
            value={draft.groupId}
            onChange={(event) => onChange({ ...draft, groupId: event.target.value })}
          >
            <option value="">Sin grupo</option>
            {groups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.nombre}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Color">
          <ColorField
            value={draft.color}
            onChange={(value) => onChange({ ...draft, color: value })}
            aria-label="Color de la etiqueta"
          />
        </Field>
        <Field label="Orden">
          <Input
            type="number"
            value={draft.orden}
            onChange={(event) => onChange({ ...draft, orden: event.target.value })}
            min={0}
          />
        </Field>
        <Field label="Descripción" className="sm:col-span-2 lg:col-span-3">
          <Input
            value={draft.descripcion}
            onChange={(event) => onChange({ ...draft, descripcion: event.target.value })}
            placeholder="Opcional"
          />
        </Field>
        <label className={cn(labelClass, "self-end pb-2")}>
          <Checkbox
            checked={draft.activa}
            onChange={(event) => onChange({ ...draft, activa: event.target.checked })}
          />
          Activa
        </label>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={saving}>
          Cancelar
        </Button>
        <Button variant="primary" size="sm" type="submit" loading={saving}>
          Guardar etiqueta
        </Button>
      </div>
    </form>
  );
}
