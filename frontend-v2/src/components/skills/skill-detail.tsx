"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, MessageSquare, PencilLine, Sparkles, Trash2 } from "lucide-react";
import { skillsApi } from "@/lib/agent-api";
import { formatDateTime } from "@/lib/utils";
import { SkillPreview } from "@/components/skills/draft-editor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { ErrorState, SkeletonText } from "@/components/ui/feedback";
import { Switch } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";

export function SkillDetailView({ id }: { id: number }) {
  const router = useRouter();
  const confirm = useConfirm();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const skill = useQuery({ queryKey: ["agent", "skill", id], queryFn: () => skillsApi.get(id) });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["agent", "skill", id] });
    queryClient.invalidateQueries({ queryKey: ["agent", "skills"] });
  };
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => skillsApi.update(id, { enabled_in_chat: enabled }),
    onSuccess: invalidate,
  });
  const edit = useMutation({
    mutationFn: () => skillsApi.createDraft(id),
    onSuccess: ({ id: draftId }) => router.push(`/ai/skills/drafts/${draftId}`),
    onError: () => toast({ title: "No se pudo abrir el editor", variant: "error" }),
  });
  const remove = useMutation({
    mutationFn: () => skillsApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent", "skills"] });
      router.push("/ai/skills");
    },
  });

  if (skill.isError) return <ErrorState title="No se pudo cargar la skill" />;
  if (!skill.data) return <SkeletonText lines={6} />;
  const data = skill.data;

  async function onDelete() {
    const ok = await confirm({
      title: `¿Borrar «${data.name}»?`,
      description: "Deja de estar disponible en el chat y en las automatizaciones que la usaban.",
      confirmLabel: "Borrar",
      tone: "danger",
    });
    if (ok) remove.mutate();
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <Link
            href="/ai/skills"
            className="inline-flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-3.5" aria-hidden />
            Skills
          </Link>
          <h1 className="mt-1 flex items-center gap-2 font-mono text-[20px] font-semibold">
            <Sparkles className="size-5 text-accent" aria-hidden />
            {data.name}
            <Badge variant="outline">v{data.version}</Badge>
          </h1>
          <p className="mt-1 max-w-2xl text-[13px] text-muted-foreground">{data.description}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/ai/assistant?skill=${encodeURIComponent(data.name)}`}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-[13px] font-medium hover:bg-muted"
          >
            <MessageSquare className="size-3.5" aria-hidden />
            Probar en el chat
          </Link>
          <a
            href={skillsApi.exportUrl(id)}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-[13px] font-medium hover:bg-muted"
          >
            <Download className="size-3.5" aria-hidden />
            Exportar
          </a>
          <Button variant="primary" size="sm" onClick={() => edit.mutate()} loading={edit.isPending}>
            <PencilLine className="size-3.5" aria-hidden />
            Editar con ayuda
          </Button>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
        <section className="card p-5">
          <SkillPreview files={data.files} />
        </section>
        <aside className="space-y-4">
          <div className="card px-4 py-1">
            <Switch
              label="Disponible en el chat"
              description="El asistente la activa cuando encaja con tu petición."
              checked={data.enabled_in_chat}
              disabled={toggle.isPending}
              onChange={(enabled) => toggle.mutate(enabled)}
            />
          </div>
          <div className="card p-4">
            <p className="mb-2 text-[12px] font-medium text-muted-foreground">Versiones</p>
            <ul className="space-y-1.5 text-[13px]">
              {data.versions.map((version) => (
                <li key={version.id} className="flex items-center justify-between">
                  <span>v{version.version}</span>
                  <span className="text-[12px] text-muted-foreground">{formatDateTime(version.created_at)}</span>
                </li>
              ))}
            </ul>
          </div>
          <Button variant="ghost" size="sm" className="text-negative" onClick={() => void onDelete()}>
            <Trash2 className="size-3.5" aria-hidden />
            Borrar skill
          </Button>
        </aside>
      </div>
    </div>
  );
}
