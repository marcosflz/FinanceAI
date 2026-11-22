"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePen, Sparkles, Trash2, Upload, Wand2 } from "lucide-react";
import { skillsApi } from "@/lib/agent-api";
import { ApiError } from "@/lib/api";
import { cn, formatDateTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { EmptyState, ErrorState, SkeletonText } from "@/components/ui/feedback";
import { Switch } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { Segmented } from "@/components/ui/segmented";
import { useToast } from "@/components/ui/toast";

type Tab = "library" | "drafts";

export function SkillsLibrary() {
  const router = useRouter();
  const confirm = useConfirm();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("library");
  const fileRef = useRef<HTMLInputElement>(null);
  const skills = useQuery({ queryKey: ["agent", "skills"], queryFn: () => skillsApi.list() });
  const drafts = useQuery({ queryKey: ["agent", "skill-drafts"], queryFn: () => skillsApi.drafts() });

  const create = useMutation({
    mutationFn: () => skillsApi.createDraft(),
    onSuccess: ({ id }) => router.push(`/ai/skills/drafts/${id}`),
    onError: () => toast({ title: "No se pudo crear el borrador", variant: "error" }),
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      skillsApi.update(id, { enabled_in_chat: enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent", "skills"] }),
  });
  const removeDraft = useMutation({
    mutationFn: (id: number) => skillsApi.deleteDraft(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agent", "skill-drafts"] }),
    onError: (error) =>
      toast({ title: "No se pudo borrar", description: error instanceof ApiError ? error.message : undefined, variant: "error" }),
  });
  const importZip = useMutation({
    mutationFn: (file: File) => skillsApi.importZip(file),
    onSuccess: ({ items }) => {
      queryClient.invalidateQueries({ queryKey: ["agent", "skill-drafts"] });
      if (items.length === 1) router.push(`/ai/skills/drafts/${items[0].draft_id}`);
      else {
        setTab("drafts");
        toast({ title: `${items.length} skills importadas como borradores`, variant: "success" });
      }
    },
    onError: (error) =>
      toast({
        title: "No se pudo importar",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  async function onDeleteDraft(id: number, name: string | null) {
    const ok = await confirm({
      title: "¿Borrar el borrador?",
      description: `Se elimina «${name ?? "Nueva skill"}» y su conversación con el creador. Las versiones publicadas se conservan.`,
      confirmLabel: "Borrar",
      tone: "danger",
    });
    if (ok) removeDraft.mutate(id);
  }

  const items = skills.data?.items ?? [];
  const draftItems = drafts.data?.items ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="IA"
        title="Skills"
        description="Procedimientos reutilizables que el asistente y tus automatizaciones activan cuando hacen falta. Créalos conversando: el creador escribe la skill por ti."
        actions={
          <>
            <input
              ref={fileRef}
              type="file"
              accept=".zip,application/zip"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) importZip.mutate(file);
                event.target.value = "";
              }}
            />
            <Button size="sm" onClick={() => fileRef.current?.click()} loading={importZip.isPending}>
              <Upload className="size-3.5" aria-hidden />
              Importar ZIP
            </Button>
            <Button variant="primary" size="sm" onClick={() => create.mutate()} loading={create.isPending}>
              <Wand2 className="size-3.5" aria-hidden />
              Crear con ayuda
            </Button>
          </>
        }
      />

      <Segmented
        aria-label="Vista"
        value={tab}
        onChange={setTab}
        options={[
          { value: "library", label: `Mis skills${items.length ? ` · ${items.length}` : ""}` },
          { value: "drafts", label: `Borradores${draftItems.length ? ` · ${draftItems.length}` : ""}` },
        ]}
      />

      {tab === "library" ? (
        skills.isError ? (
          <ErrorState />
        ) : skills.isLoading ? (
          <SkeletonText lines={4} />
        ) : items.length ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {items.map((skill) => (
              <article key={skill.id} className="card flex flex-col p-4">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <Link href={`/ai/skills/${skill.id}`} className="min-w-0 hover:underline">
                    <h2 className="flex items-center gap-1.5 truncate font-mono text-[13px] font-medium">
                      <Sparkles className="size-3.5 shrink-0 text-accent" aria-hidden />
                      {skill.name}
                    </h2>
                  </Link>
                  <Badge variant="outline">v{skill.version}</Badge>
                </div>
                <p className="line-clamp-3 flex-1 text-[13px] leading-5 text-muted-foreground">{skill.description}</p>
                <div className="mt-3 border-t border-border pt-1">
                  <Switch
                    label="Disponible en el chat"
                    checked={skill.enabled_in_chat}
                    disabled={toggle.isPending}
                    onChange={(enabled) => toggle.mutate({ id: skill.id, enabled })}
                  />
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<Sparkles className="size-4" aria-hidden />}
            title="Aún no tienes skills"
            description="Describe una tarea que repites (un informe mensual, una revisión de suscripciones…) y el creador la convertirá en una skill."
            action={
              <Button variant="primary" size="sm" onClick={() => create.mutate()}>
                <Wand2 className="size-3.5" aria-hidden />
                Crear con ayuda
              </Button>
            }
          />
        )
      ) : drafts.isLoading ? (
        <SkeletonText lines={4} />
      ) : draftItems.length ? (
        <ul className="card divide-y divide-border">
          {draftItems.map((draft) => (
            <li key={draft.id} className="group flex items-center gap-3 px-4 py-3">
              <FilePen className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <Link href={`/ai/skills/drafts/${draft.id}`} className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium">{draft.name ?? "Nueva skill"}</p>
                <p className="text-[12px] text-muted-foreground">
                  Revisión {draft.revision} · {formatDateTime(draft.updated_at)}
                </p>
              </Link>
              <Badge variant={draft.valid ? "positive" : "neutral"}>{draft.valid ? "Válida" : "Incompleta"}</Badge>
              {draft.skill_id ? <Badge variant="accent">Publicada</Badge> : null}
              <button
                type="button"
                onClick={() => onDeleteDraft(draft.id, draft.name)}
                className={cn(
                  "rounded-md p-1 text-muted-foreground opacity-0 transition-opacity hover:text-negative focus:opacity-100 group-hover:opacity-100",
                  "[@media(hover:none)]:opacity-100",
                )}
                aria-label="Borrar borrador"
              >
                <Trash2 className="size-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState title="No hay borradores" description="Los borradores aparecen aquí mientras creas o editas una skill." />
      )}
    </div>
  );
}
