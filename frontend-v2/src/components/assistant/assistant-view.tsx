"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, MessageSquarePlus, ShieldCheck, Trash2 } from "lucide-react";
import { agentApi } from "@/lib/agent-api";
import { formatDateTime, cn } from "@/lib/utils";
import { ChatPanel } from "@/components/assistant/chat-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/feedback";
import { PageHeader } from "@/components/ui/page-header";

export function AssistantView() {
  const router = useRouter();
  const params = useSearchParams();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const selected = Number(params.get("thread")) || null;
  const threads = useQuery({ queryKey: ["agent", "threads"], queryFn: () => agentApi.threads("all") });

  const create = useMutation({
    mutationFn: () => agentApi.createThread(),
    onSuccess: (thread) => {
      queryClient.invalidateQueries({ queryKey: ["agent", "threads"] });
      router.replace(`/assistant?thread=${thread.id}`);
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => agentApi.deleteThread(id),
    onSuccess: (_result, id) => {
      queryClient.invalidateQueries({ queryKey: ["agent", "threads"] });
      if (id === selected) router.replace("/assistant");
    },
  });

  async function onDelete(id: number, title: string) {
    const ok = await confirm({
      title: "¿Borrar la conversación?",
      description: `«${title}» y sus aprobaciones pendientes se eliminan. Los cambios ya aplicados se conservan.`,
      confirmLabel: "Borrar",
      tone: "danger",
    });
    if (ok) remove.mutate(id);
  }

  const items = threads.data?.items ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        eyebrow="IA"
        title="Asistente"
        description="Pregunta por tus cuentas, movimientos y cartera. Los cambios que proponga quedan pendientes hasta que los apruebes."
        actions={
          <div className="flex gap-2">
            <Link
              href="/automations"
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-3 text-[13px] font-medium hover:bg-muted"
            >
              <Bot className="size-3.5" aria-hidden />
              Automatizaciones
            </Link>
            <Button variant="primary" size="sm" onClick={() => create.mutate()} disabled={create.isPending}>
              <MessageSquarePlus className="size-3.5" aria-hidden />
              Nueva conversación
            </Button>
          </div>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
        <nav aria-label="Conversaciones" className="space-y-1 lg:max-h-[calc(100vh-220px)] lg:overflow-y-auto">
          {items.map((thread) => (
            <div
              key={thread.id}
              className={cn(
                "group flex items-center gap-1 rounded-lg px-2.5 py-2",
                thread.id === selected ? "bg-accent-soft text-accent-soft-foreground" : "hover:bg-muted",
              )}
            >
              <Link href={`/assistant?thread=${thread.id}`} className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  {thread.origin === "routine" ? <Bot className="size-3 shrink-0 text-accent" aria-hidden /> : null}
                  <span className="truncate text-[12px] font-medium">{thread.title}</span>
                </span>
                <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                  {formatDateTime(thread.updated_at)}
                  {thread.status === "awaiting_approval" ? <Badge variant="warning">Pendiente</Badge> : null}
                </span>
              </Link>
              <button
                type="button"
                onClick={() => onDelete(thread.id, thread.title)}
                className="rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-negative focus:opacity-100 group-hover:opacity-100"
                aria-label={`Borrar ${thread.title}`}
              >
                <Trash2 className="size-3.5" aria-hidden />
              </button>
            </div>
          ))}
          {threads.isSuccess && !items.length ? (
            <p className="px-2.5 py-2 text-[11px] text-muted-foreground">Aún no hay conversaciones.</p>
          ) : null}
        </nav>

        <section className="flex h-[calc(100vh-220px)] min-h-[420px] flex-col rounded-xl border border-border bg-subtle/40 p-3">
          {selected ? (
            <ChatPanel key={selected} threadId={selected} />
          ) : (
            <EmptyState
              icon={<ShieldCheck className="size-5" aria-hidden />}
              title="Empieza una conversación"
              description="El asistente trabaja sobre tu base de datos cifrada con el proveedor y la clave que configures en Ajustes."
              action={
                <Button variant="primary" size="sm" onClick={() => create.mutate()}>
                  <MessageSquarePlus className="size-3.5" aria-hidden />
                  Nueva conversación
                </Button>
              }
            />
          )}
        </section>
      </div>
    </div>
  );
}
