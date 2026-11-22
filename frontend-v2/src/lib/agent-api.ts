import { API_BASE_URL, ApiError, apiFetch, csrfHeader } from "@/lib/api";
import type {
  AdvisorAsset,
  AdvisorEvaluation,
  AdvisorStatus,
  AgentEvent,
  AgentMemory,
  AgentNotification,
  AiCatalogProvider,
  AiProviderConfig,
  ApprovalDecision,
  Bot,
  BotInput,
  BotTemplate,
  ChatThread,
  NewsFeed,
  NewsItem,
  Recommendation,
  Skill,
  SkillDetail,
  SkillDraftDetail,
  SkillDraftSummary,
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
    payload: { message: string; provider?: string; model?: string; skills?: string[] },
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
  cancel(runId: number) {
    return apiFetch<{ cancelled: boolean }>(`/api/v3/agent/runs/${runId}/cancel`, { method: "POST" });
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

export const skillsApi = {
  list() {
    return apiFetch<{ items: Skill[] }>("/api/v3/agent/skills");
  },
  get(id: number) {
    return apiFetch<SkillDetail>(`/api/v3/agent/skills/${id}`);
  },
  update(id: number, payload: { enabled_in_chat?: boolean }) {
    return apiFetch<Skill>(`/api/v3/agent/skills/${id}`, { method: "PATCH", json: payload });
  },
  remove(id: number) {
    return apiFetch<void>(`/api/v3/agent/skills/${id}`, { method: "DELETE" });
  },
  exportUrl(id: number) {
    return `${API_BASE_URL}/api/v3/agent/skills/${id}/export`;
  },
  async importZip(file: File) {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(`${API_BASE_URL}/api/v3/agent/skills/import`, {
      method: "POST",
      body,
      credentials: "include",
      headers: { ...csrfHeader() },
    });
    const data = (await response.json().catch(() => ({}))) as ApiErrorBody & {
      items?: { draft_id: number; name: string }[];
    };
    if (!response.ok) {
      throw new ApiError(
        response.status,
        data.message ?? data.detail ?? `Error ${response.status}`,
        data.code ?? `http_${response.status}`,
      );
    }
    return { items: data.items ?? [] };
  },
  drafts() {
    return apiFetch<{ items: SkillDraftSummary[] }>("/api/v3/agent/skill-drafts");
  },
  createDraft(skillId?: number) {
    return apiFetch<{ id: number }>("/api/v3/agent/skill-drafts", {
      method: "POST",
      json: { skill_id: skillId ?? null },
    });
  },
  draft(id: number) {
    return apiFetch<SkillDraftDetail>(`/api/v3/agent/skill-drafts/${id}`);
  },
  saveDraft(id: number, revision: number, files: Record<string, string | null>) {
    return apiFetch<{ revision: number }>(`/api/v3/agent/skill-drafts/${id}`, {
      method: "PATCH",
      json: { revision, files },
    });
  },
  deleteDraft(id: number) {
    return apiFetch<void>(`/api/v3/agent/skill-drafts/${id}`, { method: "DELETE" });
  },
  publish(id: number) {
    return apiFetch<{ skill_id: number; version: number; name: string }>(
      `/api/v3/agent/skill-drafts/${id}/publish`,
      { method: "POST" },
    );
  },
  send(
    draftId: number,
    payload: { message: string; provider?: string; model?: string },
    onEvent: (event: AgentEvent) => void,
    signal?: AbortSignal,
  ) {
    return readEvents(
      `/api/v3/agent/skill-drafts/${draftId}/messages`,
      jsonInit(payload),
      onEvent,
      signal,
    );
  },
};

export const memoryApi = {
  list(q?: string) {
    return apiFetch<{ items: AgentMemory[] }>("/api/v3/agent/memories", { query: q ? { q } : undefined });
  },
  create(key: string, value: string) {
    return apiFetch<AgentMemory>("/api/v3/agent/memories", { method: "POST", json: { key, value } });
  },
  update(id: number, value: string) {
    return apiFetch<AgentMemory>(`/api/v3/agent/memories/${id}`, { method: "PATCH", json: { value } });
  },
  remove(id: number) {
    return apiFetch<void>(`/api/v3/agent/memories/${id}`, { method: "DELETE" });
  },
  clear() {
    return apiFetch<void>("/api/v3/agent/memories", { method: "DELETE" });
  },
};

export const advisorApi = {
  status() {
    return apiFetch<AdvisorStatus>("/api/v3/advisor/status");
  },
  setup() {
    return apiFetch<Bot>("/api/v3/advisor/setup", { method: "POST" });
  },
  latest() {
    return apiFetch<{ items: AdvisorAsset[] }>("/api/v3/advisor/latest");
  },
  history(symbol?: string) {
    return apiFetch<{ items: Recommendation[] }>("/api/v3/advisor/history", {
      query: symbol ? { symbol } : undefined,
    });
  },
  evaluation() {
    return apiFetch<AdvisorEvaluation>("/api/v3/advisor/evaluation");
  },
  feeds() {
    return apiFetch<{ items: NewsFeed[]; defaults: NewsFeed[] }>("/api/v3/advisor/feeds");
  },
  saveFeeds(items: NewsFeed[]) {
    return apiFetch<{ items: NewsFeed[] }>("/api/v3/advisor/feeds", { method: "PUT", json: { items } });
  },
  news(q?: string) {
    return apiFetch<{ items: NewsItem[]; feeds: string[]; failed: string[] }>("/api/v3/advisor/news", {
      query: q ? { q } : undefined,
    });
  },
};
