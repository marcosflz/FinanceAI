"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Settings2, Sparkles } from "lucide-react";
import { agentApi, aiApi, skillsApi } from "@/lib/agent-api";
import type { AgentApproval, AgentEvent, ApprovalDecision } from "@/lib/agent-types";
import { ApiError } from "@/lib/api";
import { applyEvent, emptyLive, type LiveState } from "@/components/assistant/chat-stream";
import { Composer } from "@/components/assistant/composer";
import { MessageView } from "@/components/assistant/message-view";
import { ModelPicker, useModelChoice } from "@/components/assistant/model-picker";
import { SkillsPicker } from "@/components/assistant/skills-picker";
import { ErrorState, SkeletonText } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";

const SUGGESTIONS = [
  "¿Cuánto he gastado este mes y en qué?",
  "Revisa mis movimientos pendientes y propón categorías",
  "Compara mis gastos de los últimos 3 meses en un gráfico",
  "¿Cómo va mi cartera?",
];

export interface FirstMessage {
  threadId: number;
  message: string;
  skills: string[];
}

/** Herramientas comunes del composer: skills + modelo (estado compartido por el chat). */
function useComposerTools(initialSkills?: string[]) {
  const providers = useQuery({ queryKey: ["ai", "providers"], queryFn: () => aiApi.providers() });
  const catalog = useQuery({ queryKey: ["ai", "catalog"], queryFn: () => aiApi.catalog() });
  const skills = useQuery({ queryKey: ["agent", "skills"], queryFn: () => skillsApi.list() });
  const [choice, setChoice] = useModelChoice();
  const [selected, setSelected] = useState<string[]>(initialSkills ?? []);
  const noProvider =
    providers.isSuccess && !catalog.data?.fake && providers.data.items.filter((p) => p.enabled).length === 0;

  const left = (
    <SkillsPicker skills={skills.data?.items ?? []} selected={selected} onChange={setSelected} disabled={noProvider} />
  );
  const right = (
    <ModelPicker
      providers={providers.data?.items ?? []}
      catalog={catalog.data?.items ?? []}
      value={choice}
      onChange={setChoice}
    />
  );
  const chips = selected.map((name) => ({
    label: `/${name}`,
    onRemove: () => setSelected((current) => current.filter((item) => item !== name)),
  }));
  return { choice, selected, setSelected, noProvider, left, right, chips };
}

function NoProviderBanner() {
  return (
    <div className="mb-2 flex items-center justify-between gap-2 rounded-xl border border-warning/30 bg-warning-soft px-3 py-2 text-[12px]">
      <span>Configura un proveedor de IA para usar el asistente.</span>
      <Link
        href="/ai/settings"
        className="inline-flex items-center gap-1 font-medium text-foreground underline underline-offset-2"
      >
        <Settings2 className="size-3.5" aria-hidden />
        Configurar
      </Link>
    </div>
  );
}

/**
 * Estado vacío centrado (como Nexus): logo, pregunta, composer y sugerencias.
 * Se usa sin conversación seleccionada; al enviar se crea el hilo.
 */
export function EmptyChat({
  onSend,
  busy,
  initialSkills,
}: {
  onSend: (message: string, skills: string[]) => void;
  busy?: boolean;
  initialSkills?: string[];
}) {
  const tools = useComposerTools(initialSkills);
  function send(text: string) {
    onSend(text, tools.selected);
    tools.setSelected([]);
  }
  return (
    <div className="flex min-h-full flex-col items-center justify-center px-4 pb-[14vh] pt-10">
      <div className="w-full max-w-[700px]">
        <div className="mb-7 flex flex-col items-center text-center">
          <span className="animate-dialog-in mb-5 flex size-10 items-center justify-center rounded-xl bg-accent text-accent-foreground">
            <Sparkles className="size-5" aria-hidden />
          </span>
          <h1 className="text-[26px] font-normal tracking-tight sm:text-[30px]">
            ¿En qué te ayudo con tus finanzas?
          </h1>
        </div>
        {tools.noProvider ? <NoProviderBanner /> : null}
        <Composer
          onSend={send}
          busy={busy}
          disabled={tools.noProvider}
          autoFocus
          placeholder="Pregunta por tus cuentas, movimientos o cartera…"
          left={tools.left}
          right={tools.right}
          chips={tools.chips}
        />
        <ul className="mt-6 divide-y divide-border">
          {SUGGESTIONS.map((suggestion) => (
            <li key={suggestion}>
              <button
                type="button"
                disabled={busy || tools.noProvider}
                onClick={() => send(suggestion)}
                className="flex w-full items-center gap-3 px-1 py-2.5 text-left text-[14px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
              >
                <Search className="size-4 shrink-0" aria-hidden />
                {suggestion}
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-8 text-center text-[12px] text-muted-foreground">
          Cualquier cambio que proponga el asistente queda pendiente de tu aprobación.
        </p>
      </div>
    </div>
  );
}

export function ChatPanel({
  threadId,
  first,
  onFirstConsumed,
  header,
}: {
  threadId: number;
  first?: FirstMessage | null;
  onFirstConsumed?: () => void;
  header?: (title: string) => ReactNode;
}) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["agent", "thread", threadId],
    queryFn: () => agentApi.thread(threadId),
  });
  const tools = useComposerTools();

  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [live, setLive] = useState<LiveState | null>(null);
  const [decisions, setDecisions] = useState<Record<string, ApprovalDecision>>({});
  const abortRef = useRef<AbortController | null>(null);
  const firstSent = useRef(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const busy = live !== null;

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["agent", "thread", threadId] });
    queryClient.invalidateQueries({ queryKey: ["agent", "threads"] });
  }, [queryClient, threadId]);

  const runStream = useCallback(
    async (start: (onEvent: (event: AgentEvent) => void, signal: AbortSignal) => Promise<void>) => {
      const controller = new AbortController();
      abortRef.current = controller;
      setLive(emptyLive());
      queryClient.invalidateQueries({ queryKey: ["agent", "threads"] });
      try {
        await start((event) => {
          setLive((current) => applyEvent(current ?? emptyLive(), event));
          if (event.type === "RUN_ERROR" && event.status !== "cancelled") {
            toast({ title: "El asistente ha fallado", description: event.message, variant: "error" });
          }
        }, controller.signal);
      } catch (error) {
        toast({
          title: "No se pudo enviar",
          description: error instanceof ApiError ? error.message : "Error de conexión",
          variant: "error",
        });
      } finally {
        abortRef.current = null;
        await refresh();
        setLive(null);
        setPendingUser(null);
        setDecisions({});
      }
    },
    [queryClient, refresh, toast],
  );

  // Reengancha un run en curso (p. ej. tras recargar la página).
  const activeRun = detail.data?.active_run_id ?? null;
  useEffect(() => {
    if (!activeRun || abortRef.current) return;
    void runStream((onEvent, signal) => agentApi.follow(activeRun, 0, onEvent, signal));
  }, [activeRun, runStream]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [detail.data?.messages.length, live?.message.parts, pendingUser]);

  const pendingIds = useMemo(
    () => new Set((detail.data?.pending_approvals ?? []).map((approval) => approval.call_id)),
    [detail.data?.pending_approvals],
  );

  const messages = useMemo(
    () =>
      (detail.data?.messages ?? []).map((message) => ({
        ...message,
        parts: message.parts.map((part) =>
          part.type === "approvals"
            ? {
                ...part,
                items: part.items.map((approval: AgentApproval) => {
                  const local = decisions[approval.call_id];
                  if (local) return { ...approval, status: local.approved ? "approved" : "denied" } as AgentApproval;
                  return pendingIds.has(approval.call_id)
                    ? approval
                    : ({ ...approval, status: "resolved" } as AgentApproval);
                }),
              }
            : part,
        ),
      })),
    [detail.data?.messages, pendingIds, decisions],
  );

  const send = useCallback(
    (text: string, skills: string[]) => {
      const message = text.trim();
      if (!message || abortRef.current) return;
      setPendingUser(message);
      void runStream((onEvent, signal) =>
        agentApi.send(
          threadId,
          {
            message,
            provider: tools.choice?.provider,
            model: tools.choice?.model,
            skills: skills.length ? skills : undefined,
          },
          onEvent,
          signal,
        ),
      );
    },
    [runStream, threadId, tools.choice?.provider, tools.choice?.model],
  );

  // Primer mensaje escrito en el estado vacío, antes de que existiera el hilo.
  useEffect(() => {
    if (!first || first.threadId !== threadId || firstSent.current) return;
    firstSent.current = true;
    send(first.message, first.skills);
    onFirstConsumed?.();
  }, [first, threadId, send, onFirstConsumed]);

  function onStop() {
    const runId = live?.runId ?? activeRun;
    if (!runId) return;
    agentApi.cancel(runId).catch(() => {
      // Ya había terminado: el stream se cerrará solo.
    });
  }

  function onDecide(decision: ApprovalDecision) {
    const next = { ...decisions, [decision.call_id]: decision };
    setDecisions(next);
    const pending = detail.data?.pending_approvals ?? [];
    // nas-adk reanuda todas las llamadas pendientes a la vez.
    if (pending.every((approval) => next[approval.call_id])) {
      void runStream((onEvent, signal) =>
        agentApi.resume(threadId, pending.map((approval) => next[approval.call_id]), onEvent, signal),
      );
    }
  }

  const awaiting = detail.data?.thread.status === "awaiting_approval";
  const lastIndex = messages.length - 1;

  if (detail.isError) return <ErrorState title="No se pudo cargar la conversación" />;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {header ? header(detail.data?.thread.title ?? "") : null}
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[760px] px-4 pb-6 pt-6 sm:px-6">
          {detail.isLoading ? <SkeletonText lines={4} /> : null}
          {messages.map((message, index) => (
            <MessageView
              key={message.id}
              message={message}
              busy={busy}
              last={index === lastIndex && !live && !pendingUser}
              onDecide={onDecide}
            />
          ))}
          {pendingUser ? (
            <MessageView message={{ id: "pending-user", role: "user", content: pendingUser, parts: [] }} />
          ) : null}
          {live ? (
            <MessageView message={live.message} streaming runningCalls={live.running} busy onDecide={onDecide} />
          ) : null}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="sticky bottom-0 bg-gradient-to-t from-background from-60% to-transparent pb-[max(env(safe-area-inset-bottom),1rem)] pt-4">
        <div className="mx-auto w-full max-w-[760px] px-4 sm:px-6">
          {tools.noProvider ? <NoProviderBanner /> : null}
          <Composer
            onSend={(text) => {
              send(text, tools.selected);
              tools.setSelected([]);
            }}
            busy={busy}
            onStop={onStop}
            disabled={tools.noProvider || awaiting}
            placeholder={
              awaiting ? "Resuelve las aprobaciones pendientes para continuar…" : "Pregunta lo que quieras…"
            }
            left={tools.left}
            right={tools.right}
            chips={tools.chips}
          />
        </div>
      </div>
    </div>
  );
}
