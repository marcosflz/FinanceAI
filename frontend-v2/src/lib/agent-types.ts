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
  origin: "chat" | "routine" | "skill_creator";
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
  | { type: "approvals"; items: AgentApproval[] }
  | { type: "skill"; name: string };

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
    | { type: "SKILL_ACTIVATED"; name: string; id: string }
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
  skill_ids: number[];
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
  skill_ids?: number[];
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

// ── Skills ───────────────────────────────────────────────────────────────────

export interface SkillVersionRef {
  id: number;
  version: number;
  created_at: string;
}

export interface Skill {
  id: number;
  name: string;
  description: string;
  enabled_in_chat: boolean;
  source: string;
  version: number | null;
  versions: SkillVersionRef[];
  created_at: string;
  updated_at: string | null;
}

/** Contenido de texto por ruta; ``null`` si el archivo es binario. */
export type SkillFiles = Record<string, string | null>;

export interface SkillDetail extends Skill {
  files: SkillFiles;
}

export interface SkillValidation {
  ok: boolean;
  error?: string;
  name?: string;
  description?: string;
  files?: string[];
}

export interface SkillDraftSummary {
  id: number;
  skill_id: number | null;
  thread_id: number;
  base_version_id: number | null;
  revision: number;
  name: string | null;
  valid: boolean;
  status: ChatThread["status"];
  created_at: string;
  updated_at: string;
}

export interface SkillDraftDetail extends SkillDraftSummary {
  files: SkillFiles;
  base_files: SkillFiles | null;
  validation: SkillValidation | null;
  messages: ChatMessage[];
  active_run_id: number | null;
}

// ── Memoria y asesor ─────────────────────────────────────────────────────────

export interface AgentMemory {
  id: number;
  key: string;
  value: string;
  category: "profile" | "preference" | "goal" | "asset" | "fact";
  source: "assistant" | "user";
  source_thread_id: number | null;
  created_at: string;
  updated_at: string;
}

export type Horizon = "corto" | "medio" | "largo";
export type AdviceAction = "mantener" | "comprar" | "vender";

export interface Recommendation {
  id?: number;
  symbol: string;
  name?: string | null;
  asset_id?: number | null;
  horizon: Horizon;
  action: AdviceAction;
  confidence: "baja" | "media" | "alta";
  rationale: string;
  sources: string[];
  price?: number | null;
  currency?: string | null;
  thread_id?: number | null;
  created_at?: string;
}

export interface AdvisorAsset {
  symbol: string;
  name: string | null;
  asset_id: number | null;
  horizons: Partial<Record<Horizon, Recommendation>>;
  updated_at: string | null;
}

export interface AdvisorStatus {
  skill_installed: boolean;
  bot: Bot | null;
  last_report_at: string | null;
  recommendations: number;
}

export interface AdvisorEvaluation {
  items: (Recommendation & { current_price: number; change_pct: number; hit: boolean })[];
  by_horizon: Partial<Record<Horizon, { hits: number; total: number }>>;
  hit_rate: number | null;
  evaluated: number;
}

export interface NewsFeed {
  name: string;
  url: string;
}

export interface NewsItem {
  title: string;
  summary: string;
  url: string;
  source: string;
  published_at: string | null;
}
