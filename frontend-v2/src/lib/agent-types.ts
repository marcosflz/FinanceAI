/** Tipos del asistente de IA y automatizaciones (contrato /api/v3/ai y /api/v3/agent). */

export interface AiCatalogProvider {
  id: string;
  label: string;
  models: string[];
  notes: string;
  requires_key: boolean;
  kind: "api" | "subscription";
  link: "key" | "claude" | "chatgpt";
}

export interface AiProviderConfig {
  provider: string;
  label: string;
  model: string | null;
  enabled: boolean;
  is_default: boolean;
  has_key: boolean;
  key_hint: string | null;
  kind?: "api" | "subscription";
  link?: "key" | "claude" | "chatgpt";
  updated_at?: string | null;
}

export interface ChatThread {
  id: number;
  title: string;
  origin: "chat" | "routine";
  bot_id: number | null;
  provider: string | null;
  model: string | null;
  status: "idle" | "running" | "awaiting_approval";
  created_at: string;
  updated_at: string;
}

export interface RecategorizeRow {
  id: number;
  date?: string | null;
  amount?: number | null;
  currency?: string | null;
  merchant?: string | null;
  category?: string | null;
  new_category: string | null;
  valid: boolean;
}

export interface ApprovalPreview {
  kind: "simple" | "recategorize";
  rows?: RecategorizeRow[];
}

export interface AgentApproval {
  id: number;
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
  preview: ApprovalPreview | null;
  /** ``resolved``: ya decidida en un turno anterior (el mensaje guarda la foto). */
  status: "pending" | "approved" | "denied" | "resolved";
  created_at?: string;
}

export interface ChartSeries {
  name: string;
  values: number[];
}

export type MessagePart =
  | { type: "text"; text: string }
  | {
      type: "tool";
      call_id: string;
      name: string;
      args: Record<string, unknown>;
      result: unknown;
    }
  | { type: "approvals"; items: AgentApproval[] };

export interface ChatMessage {
  id: number | string;
  role: "user" | "assistant";
  content: string | null;
  parts: MessagePart[];
  run_id?: number | null;
  created_at?: string;
}

export interface ThreadDetail {
  thread: ChatThread;
  messages: ChatMessage[];
  pending_approvals: AgentApproval[];
  active_run_id: number | null;
}

interface EventBase {
  seq: number;
  run_id: number;
  thread_id: number;
}

export type AgentEvent = EventBase &
  (
    | { type: "RUN_STARTED"; initiator: string }
    | { type: "TEXT_DELTA"; delta: string }
    | { type: "TOOL_CALL_START"; call_id: string; name: string; args: Record<string, unknown> }
    | {
        type: "TOOL_CALL_RESULT";
        call_id: string;
        name: string;
        args: Record<string, unknown>;
        result: unknown;
      }
    | { type: "APPROVAL_REQUIRED"; approvals: AgentApproval[] }
    | { type: "RUN_FINISHED"; status: "completed" | "interrupted" }
    | { type: "RUN_ERROR"; status: string; message: string }
  );

export interface ApprovalDecision {
  call_id: string;
  approved: boolean;
  selected_ids?: number[];
  reason?: string;
}

export interface BotTemplate {
  id: string;
  name: string;
  cron: string;
  prompt: string;
}

export interface Bot {
  id: number;
  name: string;
  template: string | null;
  prompt: string;
  cron: string;
  timezone: string;
  enabled: boolean;
  provider: string | null;
  model: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_thread_id: number | null;
  last_error: string | null;
}

export interface BotInput {
  name: string;
  prompt: string;
  cron: string;
  timezone?: string;
  template?: string | null;
  enabled?: boolean;
  provider?: string | null;
  model?: string | null;
}

export interface AgentNotification {
  id: number;
  kind: "bot_completed" | "bot_failed" | "needs_approval" | string;
  title: string;
  body: string | null;
  thread_id: number | null;
  bot_id: number | null;
  read: boolean;
  created_at: string;
}
