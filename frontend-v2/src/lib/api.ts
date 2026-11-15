import type {
  AcceptInvitePayload,
  Account,
  AdminUser,
  AutomationResponse,
  DatabaseExportFormat,
  InviteResponse,
  RecoverPayload,
  AnalyticsSummary,
  ApiErrorBody,
  BulkMovementUpdate,
  CashflowPoint,
  CashflowGranularity,
  Category,
  CategoryBreakdown,
  CategoryInput,
  ClassificationBatchResponse,
  ClassificationRule,
  DailyDensity,
  DataHealth,
  DedupCandidate,
  ImportConfirmAccountPayload,
  ImportDetail,
  ImportSummary,
  ImportUploadResponse,
  LoginPayload,
  LoginResponse,
  Movement,
  MovementFilters,
  MovementListResponse,
  ModelSettings,
  MovementUpdate,
  Paginated,
  PortfolioSummary,
  ProfileUpdatePayload,
  Tag,
  TagGroup,
  TagGroupInput,
  TagGroupsResponse,
  TagInput,
  TransferSuggestion,
  User,
} from "@/lib/types";

export const AUTH_UNAUTHORIZED_EVENT = "ft:unauthorized";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/+$/, "");
export const API_BASE_URL = API_BASE;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;

  constructor(
    status: number,
    message: string,
    code = "unknown",
    details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : null;
}

function csrfToken(): string | null {
  return (
    readCookie("ft_csrf") ??
    readCookie("__Host-ft_csrf") ??
    readCookie("csrf_token")
  );
}

/** Cabecera CSRF para peticiones que no pasan por ``apiFetch`` (streams). */
export function csrfHeader(): Record<string, string> {
  const token = csrfToken();
  return token ? { "X-CSRF-Token": token } : {};
}

type QueryValue = string | number | boolean | null | undefined;

export function buildQuery(query?: Record<string, QueryValue>): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

export interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  json?: unknown;
  body?: BodyInit | null;
  query?: Record<string, QueryValue>;
  skipAuthRedirect?: boolean;
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { json, query, skipAuthRedirect, headers, ...rest } = options;
  const method = (rest.method ?? "GET").toUpperCase();
  const requestHeaders = new Headers(headers);
  requestHeaders.set("Accept", "application/json");

  let body = options.body;
  if (json !== undefined) {
    requestHeaders.set("Content-Type", "application/json");
    body = JSON.stringify(json);
  }

  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = csrfToken();
    if (token) requestHeaders.set("X-CSRF-Token", token);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}${buildQuery(query)}`, {
      ...rest,
      method,
      headers: requestHeaders,
      body,
      credentials: "include",
      cache: "no-store",
    });
  } catch (error) {
    throw new ApiError(
      0,
      "No se pudo conectar con el servidor. Comprueba tu conexión.",
      "network_error",
      error,
    );
  }

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("content-type") ?? "";
  const payload: unknown = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");

  if (!response.ok) {
    const body = (payload ?? {}) as ApiErrorBody;
    const message =
      body.message ??
      body.detail ??
      (typeof payload === "string" && payload ? payload : null) ??
      `Error ${response.status}`;

    if (response.status === 401 && !skipAuthRedirect) {
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent(AUTH_UNAUTHORIZED_EVENT, { detail: { path } }),
        );
      }
    }

    throw new ApiError(
      response.status,
      message,
      body.code ?? `http_${response.status}`,
      body.details,
    );
  }

  return payload as T;
}

export function isApiUnavailable(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.status === 0 || [404, 501, 502, 503, 504].includes(error.status);
  }
  return error instanceof TypeError;
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export const authApi = {
  login(payload: LoginPayload) {
    return apiFetch<LoginResponse>("/api/v3/auth/login", {
      method: "POST",
      json: payload,
      skipAuthRedirect: true,
    });
  },
  logout() {
    return apiFetch<void>("/api/v3/auth/logout", { method: "POST" });
  },
  logoutAll() {
    return apiFetch<void>("/api/v3/auth/logout-all", { method: "POST" });
  },
  me() {
    return apiFetch<User>("/api/v3/auth/me", { skipAuthRedirect: true });
  },
  updateProfile(payload: ProfileUpdatePayload) {
    return apiFetch<User>("/api/v3/auth/profile", {
      method: "PATCH",
      json: payload,
    });
  },
  changePassword(currentPassword: string, newPassword: string) {
    return apiFetch<void>("/api/v3/auth/change-password", {
      method: "POST",
      json: { current_password: currentPassword, new_password: newPassword },
    });
  },
  recover(payload: RecoverPayload) {
    return apiFetch<LoginResponse>("/api/v3/auth/recover", {
      method: "POST",
      json: payload,
      skipAuthRedirect: true,
    });
  },
  acceptInvite(payload: AcceptInvitePayload) {
    return apiFetch<LoginResponse>("/api/v3/auth/accept-invite", {
      method: "POST",
      json: payload,
      skipAuthRedirect: true,
    });
  },
  regenerateRecoveryKey(email: string, password: string) {
    return apiFetch<{ recovery_key: string }>("/api/v3/auth/recovery-key", {
      method: "POST",
      json: { email, password },
    });
  },
  setAutomation(enabled: boolean, password: string, days?: number) {
    return apiFetch<AutomationResponse>("/api/v3/auth/automation", {
      method: "PUT",
      json: { enabled, password, days },
    });
  },
};

export const accountDataApi = {
  /** Descarga el SQLite completo del usuario (descifrado o con passphrase). */
  async exportDatabase(
    password: string,
    format: DatabaseExportFormat,
    passphrase?: string,
  ): Promise<{ blob: Blob; filename: string }> {
    const headers = new Headers({ "Content-Type": "application/json" });
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", token);
    let response: Response;
    try {
      response = await fetch(`${API_BASE}/api/v3/export/database`, {
        method: "POST",
        headers,
        credentials: "include",
        cache: "no-store",
        body: JSON.stringify({ password, format, passphrase: passphrase || undefined }),
      });
    } catch (error) {
      throw new ApiError(0, "No se pudo conectar con el servidor.", "network_error", error);
    }
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
      throw new ApiError(
        response.status,
        body.message ?? body.detail ?? `Error ${response.status}`,
        body.code ?? `http_${response.status}`,
      );
    }
    const disposition = response.headers.get("content-disposition") ?? "";
    const match = /filename="?([^";]+)"?/i.exec(disposition);
    return { blob: await response.blob(), filename: match?.[1] ?? "finanzas.db" };
  },
};

export const adminApi = {
  listUsers() {
    return apiFetch<{ items: AdminUser[] }>("/api/v3/admin/users");
  },
  invite(email: string, name?: string, role: "user" | "admin" = "user") {
    return apiFetch<InviteResponse>("/api/v3/admin/users", {
      method: "POST",
      json: { email, name: name || undefined, role },
    });
  },
  setDisabled(userId: number, disabled: boolean) {
    return apiFetch<AdminUser>(`/api/v3/admin/users/${userId}`, {
      method: "PATCH",
      json: { disabled },
    });
  },
};

export const movementsApi = {
  list(filters: MovementFilters = {}) {
    return apiFetch<MovementListResponse>("/api/v3/movements", {
      query: {
        tab: filters.tab,
        q: filters.q,
        estado: filters.estado,
        kind: filters.kind,
        account_id: filters.account_id,
        categoria_id: filters.categoria_id,
        subcategoria_id: filters.subcategoria_id,
        origen: filters.origen,
        min_confidence: filters.min_confidence,
        desde: filters.from,
        hasta: filters.to,
        page: filters.page,
        page_size: filters.page_size,
        cursor: filters.cursor,
      },
    });
  },
  get(id: number) {
    return apiFetch<Movement>(`/api/v3/movements/${id}`);
  },
  update(id: number, payload: MovementUpdate) {
    return apiFetch<Movement>(`/api/v3/movements/${id}`, {
      method: "PATCH",
      json: payload,
    });
  },
  bulk(payload: BulkMovementUpdate) {
    return apiFetch<{ updated: number }>("/api/v3/movements/bulk", {
      method: "POST",
      json: payload,
    });
  },
};

export const importsApi = {
  list() {
    return apiFetch<Paginated<ImportSummary>>("/api/v3/imports");
  },
  get(id: number | string) {
    return apiFetch<ImportDetail>(`/api/v3/imports/${id}`);
  },
  upload(files: File[], accountId?: number | null) {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    if (accountId != null) form.append("account_id", String(accountId));
    return apiFetch<ImportUploadResponse>("/api/v3/imports", {
      method: "POST",
      body: form,
    });
  },
  reprocess(id: number) {
    return apiFetch<ImportSummary>(`/api/v3/imports/${id}/reprocess`, {
      method: "POST",
    });
  },
  changeAccount(id: number, accountId: number) {
    return apiFetch<ImportSummary>(`/api/v3/imports/${id}/account`, {
      method: "PATCH",
      json: { account_id: accountId },
    });
  },
  remove(id: number) {
    return apiFetch<{ deleted: boolean; id: number }>(`/api/v3/imports/${id}`, {
      method: "DELETE",
    });
  },
  confirmAccount(id: number, payload: ImportConfirmAccountPayload) {
    return apiFetch<ImportSummary>(`/api/v3/imports/${id}/confirm-account`, {
      method: "POST",
      json: payload,
    });
  },
};

export const modelsApi = {
  get() {
    return apiFetch<ModelSettings>("/api/v3/settings/models");
  },
  update(payload: Partial<ModelSettings>) {
    return apiFetch<ModelSettings>("/api/v3/settings/models", {
      method: "PATCH",
      json: payload,
    });
  },
};

export const classifyApi = {
  batch(payload: {
    limit?: number;
    import_id?: number | null;
    movement_ids?: number[];
  }) {
    return apiFetch<ClassificationBatchResponse>("/api/v3/classify/batch", {
      method: "POST",
      json: payload,
    });
  },
};

export const accountsApi = {
  list(includeInactive = false) {
    return apiFetch<{ items: Account[] }>("/api/v3/accounts", {
      query: { include_inactive: includeInactive },
    });
  },
  create(payload: Partial<Account>) {
    return apiFetch<Account>("/api/v3/accounts", {
      method: "POST",
      json: payload,
    });
  },
  update(id: number, payload: Partial<Account>) {
    return apiFetch<Account>(`/api/v3/accounts/${id}`, {
      method: "PATCH",
      json: payload,
    });
  },
  remove(id: number) {
    return apiFetch<{
      deleted: boolean;
      mode: "hard" | "archived";
      account_id: number;
      references: Record<string, number>;
      message: string;
    }>(`/api/v3/accounts/${id}`, { method: "DELETE" });
  },
  reapplyPatterns(id: number) {
    return apiFetch<{ matches: number; updated: number }>(
      `/api/v3/accounts/${id}/reapply-patterns`,
      { method: "POST" },
    );
  },
  transferSuggestions() {
    return apiFetch<{ items: TransferSuggestion[] }>(
      "/api/v3/transfers/suggestions",
    );
  },
  linkTransfer(payload: { outbound_id: number; inbound_id: number }) {
    return apiFetch<{ linked: boolean }>("/api/v3/transfers/link", {
      method: "POST",
      json: payload,
    });
  },
  dismissTransfer(payload: { outbound_id: number; inbound_id: number }) {
    return apiFetch<{ dismissed: boolean }>("/api/v3/transfers/dismiss", {
      method: "POST",
      json: payload,
    });
  },
};

export const portfolioApi = {
  summary() {
    return apiFetch<PortfolioSummary>("/api/v3/portfolio/summary");
  },
};

export const analyticsApi = {
  summary(query: { desde?: string; hasta?: string } = {}) {
    return apiFetch<AnalyticsSummary>("/api/v3/analytics/summary", {
      query: { desde: query.desde, hasta: query.hasta },
    });
  },
  cashflow(
    months = 12,
    query: {
      desde?: string;
      hasta?: string;
      granularity?: CashflowGranularity;
      all?: boolean;
    } = {},
  ) {
    return apiFetch<{ items: CashflowPoint[] }>("/api/v3/analytics/cashflow", {
      query: {
        months,
        desde: query.desde,
        hasta: query.hasta,
        granularity: query.granularity,
        all: query.all ? true : undefined,
      },
    });
  },
  byCategory(query: { desde?: string; hasta?: string } = {}) {
    return apiFetch<{ items: CategoryBreakdown[] }>(
      "/api/v3/analytics/by-category",
      { query: { desde: query.desde, hasta: query.hasta } },
    );
  },
  dataHealth() {
    return apiFetch<DataHealth>("/api/v3/analytics/data-health");
  },
  dailyDensity(query: { desde?: string; hasta?: string } = {}) {
    return apiFetch<{ items: DailyDensity[] }>(
      "/api/v3/analytics/daily-density",
      { query: { desde: query.desde, hasta: query.hasta } },
    );
  },
};

export const dedupApi = {
  list() {
    return apiFetch<{ items: DedupCandidate[] }>("/api/v3/dedup-candidates");
  },
  resolve(id: number, resolution: "mismo" | "distinto") {
    return apiFetch<{ resolved: boolean }>(
      `/api/v3/dedup-candidates/${id}/resolve`,
      { method: "POST", json: { resolution } },
    );
  },
};

export const categoriesApi = {
  list() {
    return apiFetch<{ items: Category[] }>("/api/v3/categories");
  },
  create(payload: CategoryInput) {
    return apiFetch<Category>("/api/v3/categories", {
      method: "POST",
      json: payload,
    });
  },
  update(id: number, payload: Partial<CategoryInput>) {
    return apiFetch<Category>(`/api/v3/categories/${id}`, {
      method: "PATCH",
      json: payload,
    });
  },
  remove(id: number) {
    return apiFetch<{ ok: boolean; deleted: number }>(`/api/v3/categories/${id}`, {
      method: "DELETE",
    });
  },
};

export const tagGroupsApi = {
  list() {
    return apiFetch<TagGroupsResponse>("/api/v3/tag-groups");
  },
  create(payload: TagGroupInput) {
    return apiFetch<TagGroup>("/api/v3/tag-groups", {
      method: "POST",
      json: payload,
    });
  },
  update(id: number, payload: Partial<TagGroupInput>) {
    return apiFetch<TagGroup>(`/api/v3/tag-groups/${id}`, {
      method: "PATCH",
      json: payload,
    });
  },
  remove(id: number) {
    return apiFetch<{ ok: boolean; deleted: number }>(`/api/v3/tag-groups/${id}`, {
      method: "DELETE",
    });
  },
};

export const tagsApi = {
  list(query: { group_id?: number; q?: string } = {}) {
    return apiFetch<{ items: Tag[]; total: number }>("/api/v3/tags", { query });
  },
  create(payload: TagInput) {
    return apiFetch<Tag>("/api/v3/tags", {
      method: "POST",
      json: payload,
    });
  },
  update(id: number, payload: Partial<TagInput>) {
    return apiFetch<Tag>(`/api/v3/tags/${id}`, {
      method: "PATCH",
      json: payload,
    });
  },
  remove(id: number) {
    return apiFetch<{ ok: boolean; deleted: number }>(`/api/v3/tags/${id}`, {
      method: "DELETE",
    });
  },
};

export const rulesApi = {
  list() {
    return apiFetch<{ items: ClassificationRule[] }>(
      "/api/v3/classification-rules",
    );
  },
};
