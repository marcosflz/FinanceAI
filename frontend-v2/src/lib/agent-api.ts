import { API_BASE_URL, ApiError, apiFetch, csrfHeader } from "@/lib/api";
import type {
  AgentEvent,
  AgentNotification,
  AiCatalogProvider,
  AiProviderConfig,
  ApprovalDecision,
  Bot,
  BotInput,
  BotTemplate,
  ChatThread,
  ThreadDetail,
} from "@/lib/agent-types";
import type { ApiErrorBody } from "@/lib/types";

export const aiApi = {
  catalog() {
    return apiFetch<{ items: AiCatalogProvider[]; fake: boolean }>("/api/v3/ai/catalog");
  },
  providers() {
    return apiFetch<{ items: AiProviderConfig[] }>("/api/v3/ai/providers");
  },
  save(
    provider: string,
    payload: { api_key?: string; model?: string; enabled?: boolean; is_default?: boolean },
  ) {
    return apiFetch<AiProviderConfig>(`/api/v3/ai/providers/${provider}`, {
      method: "PUT",
      json: payload,
    });
  },
  remove(provider: string) {
    return apiFetch<void>(`/api/v3/ai/providers/${provider}`, { method: "DELETE" });
  },
  linkStart(provider: string) {
    return apiFetch<{ link_id: string; url: string }>(
      `/api/v3/ai/providers/${provider}/link/start`,
      { method: "POST" },
    );
  },
  linkFinish(
    provider: string,
    payload: { link_id: string; code?: string; redirect_url?: string; model?: string },
  ) {
    return apiFetch<AiProviderConfig & { models: string[] }>(
      `/api/v3/ai/providers/${provider}/link/finish`,
      { method: "POST", json: payload },
    );
  },
  linkCancel(provider: string, linkId: string) {
    return apiFetch<void>(`/api/v3/ai/providers/${provider}/link/cancel`, {
      method: "POST",
      json: { link_id: linkId },
    });
  },
  chatgptModels() {
    return apiFetch<{ items: string[] }>("/api/v3/ai/providers/chatgpt/models");
  },
};

/**
 * Lee un ``text/event-stream`` de una respuesta ``fetch`` (POST + CSRF, que
 * ``EventSource`` no permite) y llama a ``onEvent`` por cada evento.
 */
async function readEvents(
  path: string,
  init: RequestInit,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (signal?.aborted) return;
    throw new ApiError(0, "No se pudo conectar con el servidor.", "network_error", error);
  }
  if (!response.ok || !response.body) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    throw new ApiError(
      response.status,
      body.message ?? body.detail ?? `Error ${response.status}`,
      body.code ?? `http_${response.status}`,
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = block
          .split("\n")
          .filter((line) => line.startsWith("data: "))
          .map((line) => line.slice(6))
          .join("\n");
        if (data) onEvent(JSON.parse(data) as AgentEvent);
        boundary = buffer.indexOf("\n\n");
      }
    }
  } catch (error) {
    if (!signal?.aborted) throw error;
  }
}

function jsonInit(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...csrfHeader() },
    body: JSON.stringify(body),
  };
}

export const agentApi = {
  threads(origin: "chat" | "routine" | "all" = "all") {
    return apiFetch<{ items: ChatThread[] }>("/api/v3/agent/threads", { query: { origin } });
  },
  createThread(title?: string) {
    return apiFetch<ChatThread>("/api/v3/agent/threads", { method: "POST", json: { title } });
  },
  thread(id: number) {
    return apiFetch<ThreadDetail>(`/api/v3/agent/threads/${id}`);
  },
  deleteThread(id: number) {
    return apiFetch<void>(`/api/v3/agent/threads/${id}`, { method: "DELETE" });
  },
  send(
    threadId: number,
    payload: { message: string; provider?: string; model?: string },
    onEvent: (event: AgentEvent) => void,
    signal?: AbortSignal,
  ) {
    return readEvents(`/api/v3/agent/threads/${threadId}/messages`, jsonInit(payload), onEvent, signal);
  },
  resume(
    threadId: number,
    decisions: ApprovalDecision[],
    onEvent: (event: AgentEvent) => void,
    signal?: AbortSignal,
  ) {
    return readEvents(
      `/api/v3/agent/threads/${threadId}/resume`,
      jsonInit({ decisions }),
      onEvent,
      signal,
    );
  },
  follow(runId: number, after: number, onEvent: (event: AgentEvent) => void, signal?: AbortSignal) {
    return readEvents(
      `/api/v3/agent/runs/${runId}/events?after=${after}`,
      { method: "GET", headers: { Accept: "text/event-stream" } },
      onEvent,
      signal,
    );
  },
};

export const botsApi = {
  templates() {
    return apiFetch<{ items: BotTemplate[] }>("/api/v3/agent/bots/templates");
  },
  list() {
    return apiFetch<{ items: Bot[] }>("/api/v3/agent/bots");
  },
  create(payload: BotInput) {
    return apiFetch<Bot>("/api/v3/agent/bots", { method: "POST", json: payload });
  },
  update(id: number, payload: Partial<BotInput>) {
    return apiFetch<Bot>(`/api/v3/agent/bots/${id}`, { method: "PATCH", json: payload });
  },
  remove(id: number) {
    return apiFetch<void>(`/api/v3/agent/bots/${id}`, { method: "DELETE" });
  },
  runNow(id: number) {
    return apiFetch<{ thread_id: number; status: string; error?: string | null }>(
      `/api/v3/agent/bots/${id}/run`,
      { method: "POST" },
    );
  },
};

export const notificationsApi = {
  list(unread = false) {
    return apiFetch<{ items: AgentNotification[]; unread: number }>(
      "/api/v3/agent/notifications",
      { query: { unread } },
    );
  },
  markRead(ids?: number[]) {
    return apiFetch<{ updated: number }>("/api/v3/agent/notifications/read", {
      method: "POST",
      json: ids ?? null,
    });
  },
};
