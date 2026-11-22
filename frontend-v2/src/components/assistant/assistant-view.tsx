"use client";

import { useCallback, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronRight, Loader2, PanelLeft, SquarePen, Trash2 } from "lucide-react";
import { agentApi } from "@/lib/agent-api";
import type { ChatThread } from "@/lib/agent-types";
import { cn } from "@/lib/utils";
import { ChatPanel, EmptyChat, type FirstMessage } from "@/components/assistant/chat-panel";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";

function ThreadStatus({ thread }: { thread: ChatThread }) {
  if (thread.status === "running") {
    return <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" aria-label="Generando" />;
  }
  if (thread.status === "awaiting_approval") {
    return <span className="size-2 shrink-0 rounded-full bg-warning" aria-label="Pendiente de aprobación" />;
  }
  return null;
}

function Section({
  label,
  children,
  defaultOpen = true,
}: {
  label: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mt-4 first:mt-1">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-1 px-2.5 pb-1 text-[13px] text-muted-foreground hover:text-foreground"
      >
        {label}
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} aria-hidden />
      </button>
      {open ? <div className="space-y-px">{children}</div> : null}
    </div>
  );
}

function ThreadRow({
  thread,
  active,
  onDelete,
  onNavigate,
}: {
  thread: ChatThread;
  active: boolean;
  onDelete: () => void;
  onNavigate: () => void;
}) {
  return (
    <div
      className={cn(
        "group flex h-9 items-center gap-1 rounded-lg pl-2.5 pr-1 text-[14px] transition-colors",
        active ? "bg-surface-3 text-foreground" : "text-foreground/85 hover:bg-surface-2",
      )}
    >
      <Link
        href={`/ai/assistant?thread=${thread.id}`}
        onClick={onNavigate}
        className="flex min-w-0 flex-1 items-center gap-2"
        title={thread.title}
      >
        {thread.origin === "routine" ? <Bot className="size-3.5 shrink-0 text-muted-foreground" aria-hidden /> : null}
        <span className="truncate">{thread.title}</span>
      </Link>
      <ThreadStatus thread={thread} />
      <button
        type="button"
        onClick={onDelete}
        className="rounded-md p-1 text-muted-foreground opacity-0 transition-opacity hover:text-negative focus:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
        aria-label={`Borrar ${thread.title}`}
      >
        <Trash2 className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}

export function AssistantView() {
  const router = useRouter();
  const params = useSearchParams();
  const confirm = useConfirm();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const selected = Number(params.get("thread")) || null;
  const presetSkill = params.get("skill");
  const [listOpen, setListOpen] = useState(false);
  const [first, setFirst] = useState<FirstMessage | null>(null);
  const threads = useQuery({
    queryKey: ["agent", "threads"],
    queryFn: () => agentApi.threads("all"),
    refetchInterval: (query) =>
      query.state.data?.items.some((thread) => thread.status === "running") ? 3000 : false,
  });

  const remove = useMutation({
    mutationFn: (id: number) => agentApi.deleteThread(id),
    onSuccess: (_result, id) => {
      queryClient.invalidateQueries({ queryKey: ["agent", "threads"] });
      if (id === selected) router.replace("/ai/assistant");
    },
    onError: () => toast({ title: "No se pudo borrar la conversación", variant: "error" }),
  });
  const start = useMutation({
    mutationFn: async ({ message, skills }: { message: string; skills: string[] }) => {
      const thread = await agentApi.createThread();
      return { thread, message, skills };
    },
    onSuccess: ({ thread, message, skills }) => {
      setFirst({ threadId: thread.id, message, skills });
      queryClient.invalidateQueries({ queryKey: ["agent", "threads"] });
      router.replace(`/ai/assistant?thread=${thread.id}`);
    },
    onError: () => toast({ title: "No se pudo crear la conversación", variant: "error" }),
  });
  const clearFirst = useCallback(() => setFirst(null), []);

  async function onDelete(thread: ChatThread) {
    const ok = await confirm({
      title: "¿Borrar la conversación?",
      description: `«${thread.title}» y sus aprobaciones pendientes se eliminan. Los cambios ya aplicados se conservan.`,
      confirmLabel: "Borrar",
      tone: "danger",
    });
    if (ok) remove.mutate(thread.id);
  }

  const items = threads.data?.items ?? [];
  const chats = items.filter((thread) => thread.origin === "chat");
  const routines = items.filter((thread) => thread.origin === "routine");
  const current = items.find((thread) => thread.id === selected);

  const header = (title: string) => (
    <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b border-border/60 bg-background/80 px-3 backdrop-blur-md sm:px-4">
      <button
        type="button"
        onClick={() => setListOpen(true)}
        className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface-2 hover:text-foreground lg:hidden"
        aria-label="Ver conversaciones"
      >
        <PanelLeft className="size-4" aria-hidden />
      </button>
      <h1 className="min-w-0 flex-1 truncate text-[14px] font-medium">{title || "Conversación"}</h1>
      {current ? (
        <button
          type="button"
          onClick={() => onDelete(current)}
          className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface-2 hover:text-negative"
          aria-label="Borrar conversación"
        >
          <Trash2 className="size-4" aria-hidden />
        </button>
      ) : null}
    </header>
  );

  const list = (
    <nav aria-label="Conversaciones" className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-col gap-px p-2">
        <Link
          href="/ai/assistant"
          onClick={() => setListOpen(false)}
          className={cn(
            "flex h-10 items-center gap-2.5 rounded-lg px-2.5 text-[15px] transition-colors hover:bg-surface-2",
            !selected && "bg-surface-3",
          )}
        >
          <SquarePen className="size-4" aria-hidden />
          Nueva conversación
        </Link>
      </div>
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        <Section label="Recientes">
          {chats.map((thread) => (
            <ThreadRow
              key={thread.id}
              thread={thread}
              active={thread.id === selected}
              onDelete={() => onDelete(thread)}
              onNavigate={() => setListOpen(false)}
            />
          ))}
          {threads.isSuccess && !chats.length ? (
            <p className="px-2.5 py-1.5 text-[13px] text-muted-foreground">Aún no hay conversaciones.</p>
          ) : null}
        </Section>
        {routines.length ? (
          <Section label="Automatizaciones" defaultOpen={false}>
            {routines.map((thread) => (
              <ThreadRow
                key={thread.id}
                thread={thread}
                active={thread.id === selected}
                onDelete={() => onDelete(thread)}
                onNavigate={() => setListOpen(false)}
              />
            ))}
          </Section>
        ) : null}
      </div>
    </nav>
  );

  return (
    // Ocupa el área bajo las pestañas de IA (anula el padding del shell).
    <div className="-mx-4 -mb-24 -mt-5 flex h-[calc(100svh-157px-env(safe-area-inset-bottom))] overflow-hidden sm:-mx-6 lg:-mx-8 lg:-mb-10 lg:h-[calc(100svh-101px)]">
      <aside className="hidden w-[260px] shrink-0 border-r border-border bg-sidebar lg:block">{list}</aside>

      {listOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Conversaciones">
          <button
            type="button"
            className="absolute inset-0 bg-overlay"
            aria-label="Cerrar"
            onClick={() => setListOpen(false)}
          />
          <aside className="animate-fade-in absolute inset-y-0 left-0 w-[288px] max-w-[85vw] border-r border-border bg-sidebar shadow-2">
            {list}
          </aside>
        </div>
      ) : null}

      <section className="flex min-w-0 flex-1 flex-col bg-background">
        {selected ? (
          <ChatPanel
            key={selected}
            threadId={selected}
            first={first}
            onFirstConsumed={clearFirst}
            header={header}
          />
        ) : (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex h-14 shrink-0 items-center px-3 lg:hidden">
              <button
                type="button"
                onClick={() => setListOpen(true)}
                className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface-2 hover:text-foreground"
                aria-label="Ver conversaciones"
              >
                <PanelLeft className="size-4" aria-hidden />
              </button>
            </div>
            <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
              <EmptyChat
                key={presetSkill ?? ""}
                busy={start.isPending}
                initialSkills={presetSkill ? [presetSkill] : undefined}
                onSend={(message, skills) => start.mutate({ message, skills })}
              />
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
