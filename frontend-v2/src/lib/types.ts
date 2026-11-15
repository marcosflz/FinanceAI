export type Money = number | string;

export type ISODate = string;

export type CashflowGranularity = "day" | "week" | "month" | "year";

export interface User {
  id: number;
  email: string;
  name?: string | null;
  role: "admin" | "user";
  last_login_at?: string | null;
  automation_until?: string | null;
  tenancy?: TenancyInfo;
}

export interface TenancyInfo {
  mode: "single" | "per_user";
  encryption: boolean;
}

export interface LoginPayload {
  email: string;
  password: string;
  remember?: boolean;
}

export interface LoginResponse {
  user: User;
  csrf_token?: string;
  /** Solo en el primer acceso (o al recuperar la cuenta): mostrar una vez. */
  recovery_key?: string;
}

export interface RecoverPayload {
  email: string;
  recovery_key: string;
  new_password: string;
}

export interface AcceptInvitePayload {
  token: string;
  password: string;
  name?: string | null;
}

export interface AutomationResponse {
  automation_until: string | null;
  workers: number;
}

export type DatabaseExportFormat = "sqlite" | "sqlcipher";

export interface AdminUser {
  id: number;
  email: string;
  name?: string | null;
  role: "admin" | "user";
  disabled: boolean;
  created_at?: string | null;
  last_login_at?: string | null;
  invite_pending: boolean;
  invite_expires_at?: string | null;
  encrypted: boolean;
}

export interface InviteResponse {
  user: AdminUser;
  invite_token: string;
  invite_path: string;
}

export interface ProfileUpdatePayload {
  name?: string | null;
  email?: string;
  current_password?: string;
}

export type AccountType = "broker_central" | "efectivo_externa";

export interface AccountCurrencyBalance {
  currency: string;
  balance: Money;
  balance_eur: Money;
  balance_inicial: Money;
  balance_inicial_eur: Money | null;
  balance_inicial_fecha: ISODate | null;
}

export interface Account {
  id: number;
  balances?: AccountCurrencyBalance[];
  balance_eur?: Money;
  nombre: string;
  tipo: AccountType;
  broker: string | null;
  iban: string | null;
  alias_patrones: string[];
  es_propia: boolean;
  moneda: string;
  color: string;
  activo: boolean;
  balance_inicial?: Money;
  balance_inicial_fecha?: ISODate | null;
  balance: Money;
  last_reconciled_at?: string | null;
  reconciliacion_diferencia?: Money | null;
}

export interface AccountBalanceSnapshot {
  cuenta_id: number;
  fecha: ISODate;
  saldo_declarado: Money;
  saldo_calculado: Money;
  diferencia: Money;
}

export type MovementKind =
  | "gasto"
  | "ingreso"
  | "transferencia_interna"
  | "cambio_divisa"
  | "inversion_compra"
  | "inversion_venta"
  | "dividendo"
  | "interes"
  | "cashback"
  | "fee"
  | "impuesto"
  | "aporte_activo"
  | "ajuste";

export type MovementState = "pendiente" | "aprobado" | "rechazado" | "duplicado";

export type ClassificationOrigin =
  | "broker"
  | "rule"
  | "memory"
  | "embedding"
  | "decider"
  | "llm"
  | "user";

export type CategoryAplicaA = "gasto" | "ingreso" | "ambos";
export type CategoryTratamiento = "normal" | "transferencia" | "inversion";

export interface Category {
  id: number;
  nombre: string;
  parent_id: number | null;
  root_id?: number;
  root_nombre?: string;
  is_subcategory?: boolean;
  path: string;
  depth: number;
  aplica_a: CategoryAplicaA;
  tratamiento: CategoryTratamiento;
  naturaleza?: "gasto" | "ingreso" | "transferencia" | "inversion" | "otro";
  color: string;
  excluir_kpis: boolean;
  orden: number;
  system_key: string | null;
  es_default: boolean;
  descripcion: string | null;
  activa: boolean;
  assignable: boolean;
  usage_count: number;
  usage_total: number;
  rule_count: number;
  rule_total: number;
  children_count: number;
  creado_en: string | null;
  actualizado_en: string | null;
}

export interface Tag {
  id: number;
  nombre: string;
  color: string;
  descripcion: string | null;
  group_id: number | null;
  group_nombre: string | null;
  orden: number;
  activa: boolean;
  usage_count: number;
  rule_count: number;
  creado_en: string | null;
}

export interface TagGroup {
  id: number;
  nombre: string;
  color: string;
  orden: number;
  tags: Tag[];
}

export interface TagGroupsResponse {
  items: TagGroup[];
  ungrouped: Tag[];
  total: number;
}

export interface CategoryInput {
  nombre: string;
  parent_id?: number | null;
  aplica_a: CategoryAplicaA;
  tratamiento: CategoryTratamiento;
  color: string;
  excluir_kpis: boolean;
  orden: number;
  system_key?: string | null;
  descripcion?: string | null;
  activa: boolean;
}

export interface TagGroupInput {
  nombre: string;
  color: string;
  orden: number;
}

export interface TagInput {
  nombre: string;
  color: string;
  descripcion?: string | null;
  group_id?: number | null;
  orden: number;
  activa: boolean;
}

export interface Classification {
  categoria_id: number | null;
  categoria: string | null;
  categoria_raiz_id?: number | null;
  categoria_raiz_nombre?: string | null;
  subcategoria_id?: number | null;
  subcategoria_nombre?: string | null;
  subtipo: string | null;
  origen: ClassificationOrigin;
  confianza: number | null;
  explicacion: string | null;
  modelo?: string | null;
  prompt_version?: string | null;
  vigente: boolean;
  creado_en?: string;
}

export interface Movement {
  id: number;
  value_date: ISODate;
  occurred_at?: string | null;
  kind: MovementKind;
  direction: "in" | "out";
  amount: Money | null;
  currency: string;
  amount_eur?: Money | null;
  fx_rate_to_eur?: number | null;
  fx_source?: string | null;
  fx_date?: ISODate | null;
  estado: MovementState;
  merchant: string | null;
  description: string | null;
  account_id: number | null;
  account: Pick<Account, "id" | "nombre" | "tipo"> | null;
  account_destino_id?: number | null;
  account_destino?: Pick<Account, "id" | "nombre" | "tipo"> | null;
  classification: Classification | null;
  mcc_code?: string | null;
  counterparty_name?: string | null;
  counterparty_iban?: string | null;
  fee?: Money | null;
  tax?: Money | null;
  source_file_id?: number | null;
  source_label?: string | null;
  raw_row_id?: number | null;
  duplicate_of?: number | null;
  duplicate_score?: number | null;
  review_reasons?: string[];
  created_at?: string;
  updated_at?: string;
}

export interface MovementListResponse {
  items: Movement[];
  total: number;
  page: number;
  page_size: number;
  next_cursor: string | null;
  summary?: {
    pendientes: number;
    sin_categoria: number;
    duplicados: number;
    transferencias: number;
  };
}

export interface MovementFilters {
  tab?: string;
  q?: string;
  estado?: string;
  kind?: string;
  account_id?: string;
  categoria_id?: string;
  subcategoria_id?: string;
  origen?: string;
  min_confidence?: string;
  from?: string;
  to?: string;
  page?: number;
  page_size?: number;
  cursor?: string;
}

export interface MovementUpdate {
  estado?: MovementState;
  categoria_id?: number | null;
  subtipo?: string | null;
  nota?: string | null;
}

export interface BulkMovementUpdate {
  ids: number[];
  action: "aprobar" | "rechazar" | "reabrir" | "categorizar";
  categoria_id?: number | null;
  subtipo?: string | null;
}

export interface ModelSettings {
  jev_model: string;
  jev_reference_max: number;
  classification_batch_size: number;
  jev_max_calls_per_run: number;
  opencode_model: string;
  opencode_fallback_models: string[];
  ocr_lang: string;
  ocr_dpi: number;
  auto_approve_threshold: number;
  typesafe_configured: boolean;
  opencode_configured: boolean;
  limits: {
    jev_reference_max: [number, number];
    classification_batch_size: [number, number];
    jev_max_calls_per_run: [number, number];
    ocr_dpi: [number, number];
  };
}

export type ImportStatus =
  | "uploaded"
  | "queued"
  | "processing"
  | "parsing"
  | "parsed"
  | "parsed_with_overlap"
  | "needs_review"
  | "failed";

export interface AccountMatch {
  status: "match" | "match_weak" | "unknown" | "warning" | "mismatch" | "new_account" | "unsupported_product" | string;
  selected_account_id: number | null;
  detected_account_id: number | null;
  reason: string;
  resolution_source?: string | null;
  requires_confirmation?: boolean;
  candidates?: number[];
  detected?: {
    bank?: string | null;
    account_name?: string | null;
    account_iban?: string | null;
    product?: string | null;
  } | null;
}

export interface ImportSummary {
  id: number;
  source: string;
  filename: string;
  mime_type: string;
  file_hash: string;
  period_start: ISODate | null;
  period_end: ISODate | null;
  row_count: number;
  movement_new_count: number;
  movement_seen_count: number;
  duplicate_count: number;
  uncategorized_count: number;
  status: ImportStatus;
  account_id: number | null;
  account?: Pick<Account, "id" | "nombre"> | null;
  parser_version: string;
  error: string | null;
  reconciliation?: Reconciliation | null;
  detected_account?: AccountMatch["detected"];
  account_match?: AccountMatch | null;
  account_balance?: {
    status: string;
    message: string;
    opening?: string | null;
    opening_date?: string | null;
  } | null;
  incidences?: ImportIncidence[];
  balance_start?: number | null;
  balance_end?: number | null;
  balance_start_date?: ISODate | null;
  internal_transfer_links?: {
    linked?: number;
    already_linked?: number;
    candidates?: number;
    scanned?: number;
  } | null;
  created_at: string;
  queued_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  attempts?: number;
  parsed_at: string | null;
  /** Tamaño del fichero original en bytes, si sigue en disco. */
  size_bytes?: number | null;
  /** Posición en la cola del worker (1 = el siguiente). Solo en el listado. */
  queue_position?: number | null;
  /** Acción que el agente ha dejado pendiente de aprobación. */
  pending_action?: ImportPendingAction | null;
}

export interface ImportProposedAccount {
  nombre: string;
  iban: string | null;
  tipo: AccountType;
  broker: string | null;
  moneda: string;
  balance_inicial: number | null;
  balance_inicial_fecha: ISODate | null;
}

export type ImportPendingAction =
  | {
      type: "create_account" | "confirm_account";
      reason: string | null;
      proposed_account: ImportProposedAccount;
      suggested_account_id: number | null;
      candidates: Array<{ id: number; nombre: string; iban: string | null }>;
    }
  | { type: "unsupported_product"; reason: string | null }
  | { type: "review_movements"; reason: string | null };

export interface Reconciliation {
  opening?: string;
  closing?: string;
  expected_delta?: string;
  actual_delta?: string;
  difference?: string;
  ok?: boolean;
}

export interface RawRow {
  id: number;
  row_index: number;
  payload: Record<string, string | number | null>;
  row_hash: string;
}

export interface ImportIncidence {
  id: number;
  severity: "info" | "warning" | "error";
  code: string;
  message: string;
  row_index: number | null;
}

export interface ImportDetail extends ImportSummary {
  transactions: Movement[];
  incidences: ImportIncidence[];
  raw_rows: RawRow[];
  reconciliation_report?: {
    rows_ok: boolean;
    balance_difference: Money | null;
    total_amount: Money;
  } | null;
}

export interface ImportUploadResponse {
  import: ImportSummary;
  imports?: ImportSummary[];
  duplicate: boolean;
  message?: string;
}

export type ImportConfirmAccountPayload =
  | {
      action: "create";
      account: {
        nombre: string;
        iban: string | null;
        tipo: AccountType;
        broker: string | null;
        es_propia: true;
        moneda: string;
        color: string;
        activo: true;
        alias_patrones: string[];
        balance_inicial: Money;
        balance_inicial_fecha: ISODate | null;
      };
    }
  | {
      action: "assign";
      account_id: number;
    };

export interface ClassificationBatchItem {
  movement_id: number;
  value_date: string | null;
  merchant: string | null;
  amount: string | null;
  kind: string;
  method: string;
  categoria: string | null;
  categoria_id: number | null;
  subtipo: string | null;
  confianza: number | null;
  needs_review: boolean;
  auto_approved?: boolean;
  explicacion: string | null;
  reference_count: number;
}

export interface ClassificationBatchResponse {
  items: ClassificationBatchItem[];
  processed: number;
  remaining: number;
  reference_count: number;
  reference_cap: number;
  stats: Record<string, number>;
}

export type DedupStatus = "pendiente" | "mismo" | "distinto";

export interface DedupCandidate {
  id: number;
  movement_a: Movement;
  movement_b: Movement;
  score: number;
  motivo: string;
  estado: DedupStatus;
  created_at: string;
}

export interface TransferSuggestion {
  id: number;
  outbound: Movement;
  inbound: Movement;
  score: number;
  amount: Money;
  date: ISODate;
  status: "pendiente" | "confirmada" | "descartada";
}

export type AssetClass = "stock" | "etf" | "fondo" | "cripto" | "otro";

export interface Position {
  asset_id: number;
  symbol: string;
  isin: string | null;
  nombre: string;
  asset_class: AssetClass;
  cantidad: Money;
  precio_medio: Money;
  precio_actual: Money | null;
  valor_actual: Money;
  coste_total: Money;
  pnl_no_realizado: Money;
  pnl_no_realizado_pct: number;
  pnl_realizado: Money;
  peso: number;
  moneda: string;
  yf_ticker?: string | null;
  datos_incompletos: boolean;
  cantidad_declarada?: Money | null;
  diferencia_cantidad?: Money | null;
  precio_fecha?: ISODate | null;
  cobertura_coste?: number;
  coste_completo?: boolean;
  pnl_realizado_completo?: boolean;
}

export interface PortfolioSummary {
  posiciones: Position[];
  valor_total: Money;
  coste_total: Money;
  pnl_no_realizado: Money;
  pnl_realizado: Money;
  dividendos: Money;
  comisiones: Money;
  moneda: string;
  asignacion: Array<{ label: string; value: Money; peso: number }>;
  avisos: string[];
  posiciones_negativas: Array<{ asset_id: number; symbol: string; cantidad: Money }>;
  calculado_en: string;
  snapshot_date?: ISODate | null;
  cash_difference?: Money | null;
}

export interface AnalyticsSummary {
  period: { from: ISODate; to: ISODate; label: string };
  ingresos: Money;
  gastos: Money;
  flujo_neto: Money;
  tasa_ahorro: number;
  ingresos_prev: Money;
  gastos_prev: Money;
  flujo_neto_prev: Money;
  patrimonio_neto: Money;
  patrimonio_neto_prev: Money;
  pendientes: number;
  sin_categoria: number;
  duplicados: number;
  transferencias_sugeridas: number;
  transferencias_netas?: Money;
  aportes_netos?: Money;
}

export interface CashflowPoint {
  month: string;
  ingresos: Money;
  gastos: Money;
  neto: Money;
}

export interface CategoryBreakdown {
  categoria_id: number;
  categoria: string;
  color: string;
  total: Money;
  prev_total: Money;
  delta_pct: number;
  movimientos: number;
}

export interface DataHealth {
  last_import_at: string | null;
  last_import_filename: string | null;
  auto_classified_pct: number;
  corrections_last_week: number;
  pending_count: number;
  uncategorized_count: number;
  duplicate_count: number;
  internal_transfers_pending: number;
  accounts_total: number;
  accounts_unreconciled: number;
  negative_positions: number;
  missing_opening_positions: boolean;
  stale_movements_without_classification: number;
}

export interface DailyDensity {
  date: ISODate;
  count: number;
}

export interface ClassificationRule {
  id: number;
  nombre: string | null;
  descripcion: string | null;
  prioridad: number;
  campo: string;
  operador: string;
  valor: string;
  set_categoria: string | null;
  set_subtipo: string | null;
  activa: boolean;
  auto_aprobar: boolean;
  hit_count: number;
  last_hit_at: string | null;
  creado_en: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  next_cursor: string | null;
}

export interface ApiErrorBody {
  code?: string;
  message?: string;
  detail?: string;
  details?: unknown;
}
