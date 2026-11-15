"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Loader2, Settings2 } from "lucide-react";
import { agentApi, aiApi } from "@/lib/agent-api";
import type {
  AgentEvent,
  AgentApproval,
  ApprovalDecision,
  ChatMessage,
  MessagePart,
} from "@/lib/agent-types";
import { ApiError } from "@/lib/api";
import { MessageView } from "@/components/assistant/message-view";
import { ModelPicker, useModelChoice } from "@/components/assistant/model-picker";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonText } from "@/components/ui/feedback";
import { Textarea } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";

const SUGGESTIONS = [
  "¿Cuánto he gastado este mes y en qué?",
  "Revisa mis movimientos pendientes y propón categorías",
  "Compara mis gastos de los últimos 3 meses en un gráfico",
  "¿Cómo va mi cartera?",
];

interface LiveState {
  message: ChatMessage;
  running: Set<string>;
  lastSeq: number;
}

function emptyLive(): LiveState {
  return {
    message: { id: "live", role: "assistant", content: null, parts: [] },
    running: new Set(),
    lastSeq: 0,
  };
}

function applyEvent(state: LiveState, event: AgentEvent): LiveState {
  const parts: MessagePart[] = [...state.message.parts];
  const running = new Set(state.running);
  switch (event.type) {
    case "TEXT_DELTA": {
      const last = parts[parts.length - 1];
      if (last && last.type === "text") parts[parts.length - 1] = { ...last, text: last.text + event.delta };
      else parts.push({ type: "text", text: event.delta });
      break;
    }
    case "TOOL_CALL_START":
      running.add(event.call_id);
      parts.push({ type: "tool", call_id: event.call_id, name: event.name, args: event.args, result: undefined });
      break;
    case "TOOL_CALL_RESULT": {
      running.delete(event.call_id);
      const index = parts.findIndex((part) => part.type === "tool" && part.call_id === event.call_id);
      const part = { type: "tool" as const, call_id: event.call_id, name: event.name, args: event.args, result: event.result };
      if (index >= 0) parts[index] = part;
      else parts.push(part);
      break;
    }
    case "APPROVAL_REQUIRED":
      parts.push({ type: "approvals", items: event.approvals });
      break;
    default:
      break;
  }
  return { message: { ...state.message, parts }, running, lastSeq: Math.max(state.lastSeq, event.seq) };
}

export function ChatPanel({ threadId }: { threadId: number }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["agent", "thread", threadId],
    queryFn: () => agentApi.thread(threadId),
  });
  const providers = useQuery({ queryKey: ["ai", "providers"], queryFn: () => aiApi.providers() });
  const catalog = useQuery({ queryKey: ["ai", "catalog"], queryFn: () => aiApi.catalog() });
  const [choice, setChoice] = useModelChoice();

  const [draft, setDraft] = useState("");
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [live, setLive] = useState<LiveState | null>(null);
  const [decisions, setDecisions] = useState<Record<string, ApprovalDecision>>({});
  const abortRef = useRef<AbortController | null>(null);
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
      try {
        await start((event) => {
          setLive((current) => applyEvent(current ?? emptyLive(), event));
          if (event.type === "RUN_ERROR") {
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
    [refresh, toast],
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

  const messages = useMemo(() => {
    const items = (detail.data?.messages ?? []).map((message) => ({
      ...message,
      parts: message.parts.map((part) =>
        part.type === "approvals"
          ? {
              ...part,
              items: part.items.map((approval: AgentApproval) => {
                const local = decisions[approval.call_id];
                if (local) return { ...approval, status: local.approved ? "approved" : "denied" } as AgentApproval;
                return pendingIds.has(approval.call_id) ? approval : ({ ...approval, status: "resolved" } as AgentApproval);
              }),
            }
          : part,
      ),
    }));
    return items;
  }, [detail.data?.messages, pendingIds, decisions]);

  function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setDraft("");
    setPendingUser(message);
    void runStream((onEvent, signal) =>
      agentApi.send(
        threadId,
        { message, provider: choice?.provider, model: choice?.model },
        onEvent,
        signal,
      ),
    );
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

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    send(draft);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send(draft);
    }
  }

  const noProvider =
    providers.isSuccess && !catalog.data?.fake && providers.data.items.filter((p) => p.enabled).length === 0;
  const awaiting = detail.data?.thread.status === "awaiting_approval";

  if (detail.isError) return <ErrorState title="No se pudo cargar la conversación" />;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="scrollbar-thin min-h-0 flex-1 space-y-4 overflow-y-auto px-1 pb-4">
        {detail.isLoading ? <SkeletonText lines={4} /> : null}
        {detail.isSuccess && !messages.length && !pendingUser ? (
          <EmptyState
            title="¿En qué te ayudo con tus finanzas?"
            description="Consulto tus cuentas, movimientos y cartera. Cualquier cambio queda pendiente de que lo apruebes."
            action={
              <div className="flex flex-wrap justify-center gap-1.5">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    disabled={busy || noProvider}
                    onClick={() => send(suggestion)}
                    className="rounded-full border border-border bg-card px-3 py-1 text-[12px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            }
          />
        ) : null}
        {messages.map((message) => (
          <MessageView key={message.id} message={message} busy={busy} onDecide={onDecide} />
        ))}
        {pendingUser ? (
          <MessageView
            message={{ id: "pending-user", role: "user", content: pendingUser, parts: [] }}
            onDecide={onDecide}
          />
        ) : null}
        {live ? (
          <MessageView
            message={live.message}
            streaming
            runningCalls={live.running}
            busy
            onDecide={onDecide}
          />
        ) : null}
        <div ref={bottomRef} />
      </div>

      {noProvider ? (
        <div className="mb-2 flex items-center justify-between gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[12px]">
          <span>Configura un proveedor de IA con tu API key para usar el asistente.</span>
          <Link
            href="/settings?section=asistente"
            className="inline-flex items-center gap-1 font-medium text-foreground underline underline-offset-2"
          >
            <Settings2 className="size-3.5" aria-hidden />
            Configurar
          </Link>
        </div>
      ) : null}

      <form onSubmit={onSubmit} className="rounded-xl border border-border bg-card p-2 shadow-sm">
        <Textarea
          aria-label="Mensaje para el asistente"
          rows={2}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          disabled={noProvider}
          placeholder={
            awaiting ? "Resuelve las aprobaciones pendientes para continuar…" : "Pregunta por tus finanzas…"
          }
          className="min-h-[52px] resize-none border-0 bg-transparent px-1.5 shadow-none focus-visible:ring-0"
        />
        <div className="flex items-center justify-between gap-2 pt-1">
          <ModelPicker
            providers={providers.data?.items ?? []}
            catalog={catalog.data?.items ?? []}
            value={choice}
            onChange={setChoice}
          />
          <Button
            type="submit"
            size="sm"
            variant="primary"
            disabled={busy || !draft.trim() || awaiting || noProvider}
            aria-label="Enviar"
          >
            {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <ArrowUp className="size-3.5" aria-hidden />}
            {busy ? "Generando…" : "Enviar"}
          </Button>
        </div>
      </form>
    </div>
  );
}
