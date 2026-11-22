"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { memoryApi } from "@/lib/agent-api";
import type { AgentMemory } from "@/lib/agent-types";
import { ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import { utc } from "@/components/assistant/recommendations-widget";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { SkeletonText } from "@/components/ui/feedback";
import { Input, Textarea } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";

const CATEGORY_LABEL: Record<AgentMemory["category"], string> = {
  profile: "Perfil",
  preference: "Preferencia",
  goal: "Objetivo",
  asset: "Activo",
  fact: "Nota",
};

const EXAMPLES = [
  ["perfil.riesgo", "Moderado: acepto caídas del 20 % sin vender"],
  ["perfil.horizonte", "Largo plazo, jubilación en 2050"],
  ["objetivos.colchon", "Mantener 6 meses de gastos en liquidez"],
];

function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : "Inténtalo de nuevo";
}

function MemoryRow({ memory }: { memory: AgentMemory }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(memory.value);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["agent", "memories"] });
  const save = useMutation({
    mutationFn: () => memoryApi.update(memory.id, value.trim()),
    onSuccess: () => {
      setEditing(false);
      refresh();
    },
    onError: (error) => toast({ title: "No se pudo guardar", description: errorText(error), variant: "error" }),
  });
  const remove = useMutation({ mutationFn: () => memoryApi.remove(memory.id), onSuccess: refresh });

  return (
    <li className="group py-2.5">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <code className="text-[12px] font-medium">{memory.key}</code>
            <Badge variant={memory.source === "user" ? "info" : "accent"}>
              {CATEGORY_LABEL[memory.category]}
            </Badge>
          </div>
          {editing ? (
            <div className="mt-1.5 space-y-1.5">
              <Textarea className="min-h-16" value={value} rows={2} onChange={(event) => setValue(event.target.value)} />
              <div className="flex gap-1.5">
                <Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
                  <Check className="size-3.5" aria-hidden />
                  Guardar
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                  Cancelar
                </Button>
              </div>
            </div>
          ) : (
            <p className="mt-0.5 text-[13px] leading-5">{memory.value}</p>
          )}
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {memory.source === "user" ? "Añadido por ti" : "Guardado por el asistente"} ·{" "}
            {formatDateTime(utc(memory.updated_at))}
            {memory.source_thread_id ? (
              <>
                {" · "}
                <Link
                  href={`/ai/assistant?thread=${memory.source_thread_id}`}
                  className="underline-offset-2 hover:underline"
                >
                  ver conversación
                </Link>
              </>
            ) : null}
          </p>
        </div>
        {!editing ? (
          <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
            <Button size="icon" variant="ghost" aria-label={`Editar ${memory.key}`} onClick={() => setEditing(true)}>
              <Pencil className="size-3.5" aria-hidden />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Olvidar ${memory.key}`}
              loading={remove.isPending}
              onClick={() => remove.mutate()}
            >
              <Trash2 className="size-3.5" aria-hidden />
            </Button>
          </div>
        ) : null}
      </div>
    </li>
  );
}

function AddMemory({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [key, setKey] = useState("perfil.");
  const [value, setValue] = useState("");
  const create = useMutation({
    mutationFn: () => memoryApi.create(key.trim(), value.trim()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent", "memories"] });
      onDone();
    },
    onError: (error) => toast({ title: "No se pudo guardar", description: errorText(error), variant: "error" }),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (key.trim() && value.trim()) create.mutate();
  }
  return (
    <form onSubmit={submit} className="space-y-2 rounded-lg border border-border p-3">
      <Input
        aria-label="Clave"
        value={key}
        onChange={(event) => setKey(event.target.value)}
        placeholder="perfil.riesgo"
        className="font-mono text-[12px]"
      />
      <Textarea
        aria-label="Valor"
        rows={2}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Moderado: acepto caídas del 20 % sin vender"
      />
      <p className="text-[11px] text-muted-foreground">
        La clave empieza por perfil., preferencias., objetivos., activos.&lt;ticker&gt;. o notas.
        — p. ej. {EXAMPLES.map(([k]) => k).join(", ")}.
      </p>
      <div className="flex gap-1.5">
        <Button type="submit" size="sm" variant="primary" loading={create.isPending}>
          Guardar
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          <X className="size-3.5" aria-hidden />
          Cancelar
        </Button>
      </div>
    </form>
  );
}

/** Memoria del asistente: lo que recuerda entre conversaciones (en tu BD cifrada). */
export function MemoryCard() {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [adding, setAdding] = useState(false);
  const memories = useQuery({ queryKey: ["agent", "memories"], queryFn: () => memoryApi.list() });
  const clear = useMutation({
    mutationFn: () => memoryApi.clear(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent", "memories"] }),
  });
  const items = memories.data?.items ?? [];

  async function onClear() {
    const ok = await confirm({
      title: "¿Borrar toda la memoria?",
      description: "El asistente olvidará tu perfil, objetivos y notas. Las conversaciones se conservan.",
      confirmLabel: "Borrar todo",
      tone: "danger",
    });
    if (ok) clear.mutate();
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <div>
          <CardTitle>Memoria del asistente</CardTitle>
          <CardDescription>
            Lo que el asistente recuerda de ti entre conversaciones: perfil inversor, objetivos,
            preferencias y notas por activo. Se guarda cifrado en tu base de datos.
          </CardDescription>
        </div>
        <Brain className="size-4 text-muted-foreground" aria-hidden />
      </CardHeader>
      <CardContent className="space-y-2 pt-0">
        {memories.isLoading ? <SkeletonText lines={3} /> : null}
        {memories.isSuccess && !items.length && !adding ? (
          <p className="rounded-lg bg-muted px-3 py-2 text-[12px] text-muted-foreground">
            Aún no hay recuerdos. Cuéntale al asistente tu perfil de riesgo y tu horizonte, o
            añádelos aquí: el asesor de cartera los usa para adaptar sus consejos.
          </p>
        ) : null}
        {items.length ? (
          <ul className="divide-y divide-border">
            {items.map((memory) => (
              <MemoryRow key={`${memory.id}-${memory.updated_at}`} memory={memory} />
            ))}
          </ul>
        ) : null}
        {adding ? <AddMemory onDone={() => setAdding(false)} /> : null}
        <div className="flex flex-wrap gap-2 pt-1">
          {!adding ? (
            <Button size="sm" onClick={() => setAdding(true)}>
              <Plus className="size-3.5" aria-hidden />
              Añadir recuerdo
            </Button>
          ) : null}
          {items.length ? (
            <Button size="sm" variant="ghost" loading={clear.isPending} onClick={onClear}>
              <Trash2 className="size-3.5" aria-hidden />
              Borrar todo
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
