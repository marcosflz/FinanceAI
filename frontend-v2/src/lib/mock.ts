import { toNumber } from "@/lib/utils";
import type {
  Account,
  AnalyticsSummary,
  CashflowPoint,
  Category,
  CategoryBreakdown,
  ClassificationOrigin,
  ClassificationRule,
  DailyDensity,
  DataHealth,
  DedupCandidate,
  ImportDetail,
  ImportIncidence,
  ImportSummary,
  Movement,
  MovementKind,
  MovementState,
  MovementListResponse,
  PortfolioSummary,
  Position,
  RawRow,
  TagGroup,
  TransferSuggestion,
  User,
} from "@/lib/types";

export const mockUser: User = {
  id: 1,
  email: "marcos@example.com",
  name: "Marcos Florez",
  role: "admin",
  last_login_at: "2026-10-30T08:12:00Z",
};

export const mockAccounts: Account[] = [
  {
    id: 1,
    nombre: "Trade Republic",
    tipo: "broker_central",
    broker: "Trade Republic",
    iban: "ES64158300000019110001",
    alias_patrones: ["Trade Republic", "TR Bank"],
    es_propia: true,
    moneda: "EUR",
    color: "#4f46e5",
    activo: true,
    balance: 12450.32,
    last_reconciled_at: "2026-10-30T18:20:00Z",
    reconciliacion_diferencia: 0,
  },
  {
    id: 2,
    nombre: "Revolut",
    tipo: "efectivo_externa",
    broker: "Revolut",
    iban: "ES18158300000084910002",
    alias_patrones: ["Revolut**5844*", "Marcos Florez Fernandez"],
    es_propia: true,
    moneda: "EUR",
    color: "#0ea5e9",
    activo: true,
    balance: 3240.18,
    last_reconciled_at: "2026-10-20T09:40:00Z",
    reconciliacion_diferencia: -0.02,
  },
  {
    id: 3,
    nombre: "Bunq",
    tipo: "efectivo_externa",
    broker: "Bunq",
    iban: "NL00BUNQ0123456789",
    alias_patrones: ["Bunq test*", "Bunq"],
    es_propia: true,
    moneda: "EUR",
    color: "#14b8a6",
    activo: true,
    balance: 820.5,
    last_reconciled_at: null,
    reconciliacion_diferencia: null,
  },
  {
    id: 4,
    nombre: "Efectivo",
    tipo: "efectivo_externa",
    broker: null,
    iban: null,
    alias_patrones: ["Efectivo", "Cajero"],
    es_propia: true,
    moneda: "EUR",
    color: "#f59e0b",
    activo: true,
    balance: 160,
    last_reconciled_at: null,
    reconciliacion_diferencia: null,
  },
];

const mockCategoryRows: Array<{
  id: number;
  nombre: string;
  color: string;
  aplica_a: Category["aplica_a"];
  tratamiento: Category["tratamiento"];
  excluir_kpis: boolean;
}> = [
  { id: 1, nombre: "Alimentación", color: "#16a34a", aplica_a: "gasto", tratamiento: "normal", excluir_kpis: false },
  { id: 2, nombre: "Vivienda", color: "#0ea5e9", aplica_a: "gasto", tratamiento: "normal", excluir_kpis: false },
  { id: 3, nombre: "Transporte", color: "#f59e0b", aplica_a: "gasto", tratamiento: "normal", excluir_kpis: false },
  { id: 4, nombre: "Ocio", color: "#a855f7", aplica_a: "gasto", tratamiento: "normal", excluir_kpis: false },
  { id: 5, nombre: "Suscripciones", color: "#ec4899", aplica_a: "gasto", tratamiento: "normal", excluir_kpis: false },
  { id: 6, nombre: "Salud", color: "#ef4444", aplica_a: "gasto", tratamiento: "normal", excluir_kpis: false },
  { id: 7, nombre: "Compras", color: "#8b5cf6", aplica_a: "gasto", tratamiento: "normal", excluir_kpis: false },
  { id: 8, nombre: "Restaurantes", color: "#f97316", aplica_a: "gasto", tratamiento: "normal", excluir_kpis: false },
  { id: 9, nombre: "Viajes", color: "#14b8a6", aplica_a: "gasto", tratamiento: "normal", excluir_kpis: false },
  { id: 10, nombre: "Educación", color: "#6366f1", aplica_a: "gasto", tratamiento: "normal", excluir_kpis: false },
  { id: 11, nombre: "Inversión", color: "#0f766e", aplica_a: "ambos", tratamiento: "inversion", excluir_kpis: true },
  { id: 12, nombre: "Transferencias", color: "#64748b", aplica_a: "ambos", tratamiento: "transferencia", excluir_kpis: true },
  { id: 13, nombre: "Nómina", color: "#22c55e", aplica_a: "ingreso", tratamiento: "normal", excluir_kpis: false },
  { id: 14, nombre: "Otros", color: "#94a3b8", aplica_a: "ambos", tratamiento: "normal", excluir_kpis: false },
];

export const mockCategories: Category[] = mockCategoryRows.map((row) => ({
  ...row,
  parent_id: null,
  path: row.nombre,
  depth: 0,
  naturaleza:
    row.tratamiento === "transferencia"
      ? "transferencia"
      : row.tratamiento === "inversion"
        ? "inversion"
        : row.aplica_a === "ambos"
          ? "otro"
          : row.aplica_a,
  orden: row.id * 10,
  system_key: null,
  es_default: false,
  descripcion: null,
  activa: true,
  assignable: true,
  usage_count: 0,
  usage_total: 0,
  rule_count: 0,
  rule_total: 0,
  children_count: 0,
  creado_en: null,
  actualizado_en: null,
}));

export const mockTagGroups: TagGroup[] = [
  {
    id: 1,
    nombre: "Recurrencia",
    color: "#6366f1",
    orden: 10,
    tags: [
      {
        id: 1,
        nombre: "Fijo",
        color: "#64748b",
        descripcion: "Gasto recurrente o periódico.",
        group_id: 1,
        group_nombre: "Recurrencia",
        orden: 10,
        activa: true,
        usage_count: 0,
        rule_count: 0,
        creado_en: null,
      },
      {
        id: 2,
        nombre: "Variable",
        color: "#94a3b8",
        descripcion: "Gasto no recurrente o puntual.",
        group_id: 1,
        group_nombre: "Recurrencia",
        orden: 20,
        activa: true,
        usage_count: 0,
        rule_count: 0,
        creado_en: null,
      },
    ],
  },
  {
    id: 2,
    nombre: "Viajes",
    color: "#14b8a6",
    orden: 20,
    tags: [
      {
        id: 3,
        nombre: "Korea 2026",
        color: "#14b8a6",
        descripcion: null,
        group_id: 2,
        group_nombre: "Viajes",
        orden: 10,
        activa: true,
        usage_count: 0,
        rule_count: 0,
        creado_en: null,
      },
    ],
  },
];

function categoryById(id: number | null | undefined): Category | null {
  if (!id) return null;
  return mockCategories.find((category) => category.id === id) ?? null;
}

interface MovementSeed {
  date: string;
  merchant: string;
  description?: string;
  amount: number;
  kind: MovementKind;
  categoryId?: number | null;
  subtype?: string | null;
  origin?: ClassificationOrigin;
  confidence?: number;
  estado?: MovementState;
  accountId?: number;
  accountDestinoId?: number;
  reasons?: string[];
  mcc?: string;
  source?: string;
  fee?: number;
  tax?: number;
  counterparty?: string;
  noClassification?: boolean;
  duplicateOf?: number;
  duplicateScore?: number;
  explanation?: string;
}

const movementSeeds: MovementSeed[] = [
  {
    date: "2026-10-30",
    merchant: "Mercadona",
    amount: -84.32,
    kind: "gasto",
    categoryId: 1,
    subtype: "Supermercado",
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    mcc: "5411",
    source: "transactions_2026-07-01_2026-09-30.csv",
    explanation: "MCC 5411 → Alimentación",
  },
  {
    date: "2026-10-30",
    merchant: "Bunq test",
    description: "Transferencia a cuenta propia · Bunq",
    amount: -2,
    kind: "transferencia_interna",
    categoryId: 12,
    origin: "rule",
    confidence: 0.97,
    estado: "aprobado",
    accountDestinoId: 3,
    source: "transactions_2026-07-01_2026-09-30.csv",
    explanation: "Patrón de cuenta propia «Bunq test*»",
  },
  {
    date: "2026-10-30",
    merchant: "Bunq test",
    description: "Transferencia a cuenta propia · Bunq",
    amount: -2,
    kind: "transferencia_interna",
    categoryId: 12,
    origin: "rule",
    confidence: 0.97,
    estado: "aprobado",
    accountDestinoId: 3,
    source: "transactions_2026-07-01_2026-09-30.csv",
    explanation: "Repetición legítima · distinto transaction_id",
  },
  {
    date: "2026-10-29",
    merchant: "Nómina — Acme Studio",
    description: "Transferencia recibida · nómina octubre",
    amount: 3200,
    kind: "ingreso",
    categoryId: 13,
    origin: "broker",
    confidence: 1,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-29",
    merchant: "Transferencia a Revolut",
    description: "Envío a cuenta propia · Revolut",
    amount: -500,
    kind: "transferencia_interna",
    categoryId: 12,
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    accountDestinoId: 2,
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-28",
    merchant: "Ahorramas",
    amount: -38.06,
    kind: "gasto",
    categoryId: 1,
    subtype: "Supermercado",
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    mcc: "5411",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-28",
    merchant: "PayPal *AliExpress",
    amount: -27.94,
    kind: "gasto",
    categoryId: null,
    origin: "llm",
    confidence: 0.58,
    estado: "pendiente",
    reasons: ["Confianza baja (0.58)", "Merchant desconocido"],
    source: "transactions_2026-07-01_2026-09-30.csv",
    explanation: "El modelo no encuentra un precedente claro para este merchant.",
  },
  {
    date: "2026-10-27",
    merchant: "Repsol",
    amount: -52.1,
    kind: "gasto",
    categoryId: 3,
    subtype: "Combustible",
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    mcc: "5541",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-27",
    merchant: "Netflix",
    amount: -13.99,
    kind: "gasto",
    categoryId: 5,
    origin: "memory",
    confidence: 0.94,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
    explanation: "Precedente confirmado 8 veces · Suscripciones",
  },
  {
    date: "2026-10-26",
    merchant: "Compra IE00B4ND3602",
    description: "iShares MSCI World · 5,40 participaciones",
    amount: -500,
    kind: "inversion_compra",
    categoryId: 11,
    origin: "broker",
    confidence: 1,
    estado: "aprobado",
    fee: -1,
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-26",
    merchant: "Dividendo IE00B4ND3602",
    amount: 12.4,
    kind: "dividendo",
    categoryId: 11,
    origin: "broker",
    confidence: 1,
    estado: "aprobado",
    tax: -1.86,
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-25",
    merchant: "Transferencia de Marcos Florez",
    description: "Entrada desde Revolut",
    amount: 250,
    kind: "transferencia_interna",
    categoryId: 12,
    origin: "rule",
    confidence: 0.98,
    estado: "aprobado",
    accountId: 2,
    accountDestinoId: 1,
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-25",
    merchant: "Transferencia a Marcos Florez",
    description: "Salida hacia Revolut",
    amount: -250,
    kind: "transferencia_interna",
    categoryId: 12,
    origin: "memory",
    confidence: 0.86,
    estado: "pendiente",
    accountDestinoId: 2,
    reasons: ["Posible transferencia interna", "Contraparte coincide por nombre"],
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-24",
    merchant: "Rituals",
    amount: -24.5,
    kind: "gasto",
    categoryId: 7,
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-24",
    merchant: "Metro de Madrid",
    amount: -20,
    kind: "gasto",
    categoryId: 3,
    subtype: "Público",
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    mcc: "4111",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-23",
    merchant: "Amazon.es",
    amount: -34.9,
    kind: "gasto",
    categoryId: 7,
    origin: "memory",
    confidence: 0.92,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-23",
    merchant: "SUMUP *LA TAHONA",
    amount: -18.6,
    kind: "gasto",
    categoryId: null,
    origin: "llm",
    confidence: 0.61,
    estado: "pendiente",
    reasons: ["Confianza baja (0.61)", "Sin MCC"],
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-22",
    merchant: "Spotify",
    amount: -11.99,
    kind: "gasto",
    categoryId: 5,
    origin: "memory",
    confidence: 0.96,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-22",
    merchant: "Farmacia Fuencarral",
    amount: -12.4,
    kind: "gasto",
    categoryId: 6,
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    mcc: "5912",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-21",
    merchant: "IKEA",
    amount: -89,
    kind: "gasto",
    categoryId: 7,
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-21",
    merchant: "Renfe",
    amount: -46.8,
    kind: "gasto",
    categoryId: 9,
    origin: "rule",
    confidence: 0.95,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-20",
    merchant: "Cashback Saveback",
    amount: 4.79,
    kind: "cashback",
    categoryId: 11,
    origin: "broker",
    confidence: 1,
    estado: "aprobado",
    tax: -0.91,
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-20",
    merchant: "WAYLET",
    amount: -41.2,
    kind: "gasto",
    categoryId: null,
    origin: "rule",
    confidence: 0.77,
    estado: "pendiente",
    reasons: ["Regla genérica de combustible", "Confianza media"],
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-19",
    merchant: "Bar El Puerto",
    amount: -18.6,
    kind: "gasto",
    categoryId: 8,
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    mcc: "5812",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-19",
    merchant: "Movilidad MMD",
    amount: -35,
    kind: "gasto",
    categoryId: null,
    origin: "llm",
    confidence: 0.69,
    estado: "pendiente",
    reasons: ["Confianza baja (0.69)", "Merchant desconocido"],
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-18",
    merchant: "Compra SOL",
    description: "12,40 SOL",
    amount: -400,
    kind: "inversion_compra",
    categoryId: 11,
    origin: "broker",
    confidence: 1,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-18",
    merchant: "Venta MSFT",
    description: "1,00 MSFT",
    amount: 820,
    kind: "inversion_venta",
    categoryId: 11,
    origin: "broker",
    confidence: 1,
    estado: "aprobado",
    fee: -1,
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-17",
    merchant: "Mercadona",
    amount: -63.18,
    kind: "gasto",
    categoryId: 1,
    origin: "memory",
    confidence: 0.98,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-16",
    merchant: "Airbnb",
    amount: -210,
    kind: "gasto",
    categoryId: 9,
    origin: "memory",
    confidence: 0.93,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-16",
    merchant: "Transferencia a Bunq",
    amount: -120,
    kind: "transferencia_interna",
    categoryId: 12,
    origin: "rule",
    confidence: 0.98,
    estado: "aprobado",
    accountDestinoId: 3,
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-15",
    merchant: "Gimnasio Altafit",
    amount: -39.9,
    kind: "gasto",
    categoryId: 6,
    origin: "memory",
    confidence: 0.91,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-15",
    merchant: "OpenAI",
    amount: -22.6,
    kind: "gasto",
    categoryId: 5,
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-14",
    merchant: "Transferencia de Bunq",
    amount: 120,
    kind: "transferencia_interna",
    categoryId: 12,
    origin: "memory",
    confidence: 0.84,
    estado: "pendiente",
    accountId: 3,
    accountDestinoId: 1,
    reasons: ["Posible transferencia interna", "Importe casa con salida del 16/10"],
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-13",
    merchant: "El Corte Inglés",
    amount: -76.45,
    kind: "gasto",
    categoryId: 7,
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-12",
    merchant: "Domiciliación Vodafone",
    amount: -29.9,
    kind: "gasto",
    categoryId: 5,
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-12",
    merchant: "Domiciliación Iberdrola",
    amount: -64.2,
    kind: "gasto",
    categoryId: 2,
    subtype: "Suministros",
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-10",
    merchant: "Alquiler",
    amount: -850,
    kind: "gasto",
    categoryId: 2,
    subtype: "Alquiler",
    origin: "memory",
    confidence: 1,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-09",
    merchant: "Transferencia a Revolut",
    amount: -300,
    kind: "transferencia_interna",
    categoryId: 12,
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    accountDestinoId: 2,
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-09",
    merchant: "Transferencia de Revolut",
    amount: 300,
    kind: "transferencia_interna",
    categoryId: 12,
    origin: "rule",
    confidence: 0.99,
    estado: "aprobado",
    accountId: 2,
    accountDestinoId: 1,
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-08",
    merchant: "Compra ETH",
    description: "0,26 ETH",
    amount: -600,
    kind: "inversion_compra",
    categoryId: 11,
    origin: "broker",
    confidence: 1,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-07",
    merchant: "Amazon Prime",
    amount: -4.99,
    kind: "gasto",
    categoryId: 5,
    origin: "memory",
    confidence: 0.97,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-06",
    merchant: "Café Central",
    amount: -3.8,
    kind: "gasto",
    categoryId: 8,
    origin: "memory",
    confidence: 0.9,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-05",
    merchant: "Recibo no identificado",
    amount: -45,
    kind: "gasto",
    estado: "pendiente",
    noClassification: true,
    reasons: ["Sin clasificación", "Sin merchant legible"],
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-04",
    merchant: "Devolución Amazon",
    amount: 34.9,
    kind: "ingreso",
    categoryId: 7,
    origin: "memory",
    confidence: 0.88,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-03",
    merchant: "Intereses cuenta",
    amount: 2.14,
    kind: "interes",
    categoryId: 11,
    origin: "broker",
    confidence: 1,
    estado: "aprobado",
    tax: -0.45,
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-02",
    merchant: "Compra ETF Amundi",
    amount: -250,
    kind: "inversion_compra",
    categoryId: 11,
    origin: "broker",
    confidence: 1,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-10-01",
    merchant: "Comisión custodia",
    amount: -1,
    kind: "fee",
    categoryId: 11,
    origin: "broker",
    confidence: 1,
    estado: "aprobado",
    source: "transactions_2026-07-01_2026-09-30.csv",
  },
  {
    date: "2026-09-30",
    merchant: "Mercadona",
    amount: -72.44,
    kind: "gasto",
    categoryId: 1,
    origin: "memory",
    confidence: 0.98,
    estado: "aprobado",
    source: "extracto_trade_republic_ene_jun_2026.csv",
  },
  {
    date: "2026-09-29",
    merchant: "Nómina — Acme Studio",
    amount: 3200,
    kind: "ingreso",
    categoryId: 13,
    origin: "broker",
    confidence: 1,
    estado: "aprobado",
    source: "extracto_trade_republic_ene_jun_2026.csv",
  },
  {
    date: "2026-09-10",
    merchant: "Alquiler",
    amount: -850,
    kind: "gasto",
    categoryId: 2,
    origin: "memory",
    confidence: 1,
    estado: "aprobado",
    source: "extracto_trade_republic_ene_jun_2026.csv",
  },
];

export const mockMovements: Movement[] = movementSeeds.map((seed, index) => {
  const account = mockAccounts.find((item) => item.id === (seed.accountId ?? 1)) ?? null;
  const destination = mockAccounts.find((item) => item.id === seed.accountDestinoId) ?? null;
  const category = categoryById(seed.categoryId);
  const classification =
    seed.noClassification || (seed.categoryId === undefined && !seed.origin)
      ? null
      : {
          categoria_id: category?.id ?? null,
          categoria: category?.nombre ?? null,
          subtipo: seed.subtype ?? null,
          origen: seed.origin ?? "rule",
          confianza: seed.confidence ?? 0.99,
          explicacion:
            seed.explanation ??
            (category
              ? `Clasificado como ${category.nombre} por ${seed.origin ?? "rule"}.`
              : "Pendiente de categoría."),
          vigente: true,
        };

  return {
    id: 5000 + index,
    value_date: seed.date,
    occurred_at: `${seed.date}T10:24:00Z`,
    kind: seed.kind,
    direction: seed.amount >= 0 ? "in" : "out",
    amount: seed.amount,
    currency: "EUR",
    estado: seed.estado ?? "pendiente",
    merchant: seed.merchant,
    description: seed.description ?? null,
    account_id: account?.id ?? null,
    account: account ? { id: account.id, nombre: account.nombre, tipo: account.tipo } : null,
    account_destino_id: destination?.id ?? null,
    account_destino: destination
      ? { id: destination.id, nombre: destination.nombre, tipo: destination.tipo }
      : null,
    classification,
    mcc_code: seed.mcc ?? null,
    counterparty_name: seed.counterparty ?? null,
    counterparty_iban: null,
    fee: seed.fee ?? 0,
    tax: seed.tax ?? 0,
    source_label: seed.source ?? "transactions_2026-07-01_2026-09-30.csv",
    source_file_id: seed.source?.includes("ene_jun") ? 39 : 41,
    raw_row_id: 1000 + index,
    review_reasons: seed.reasons ?? [],
    created_at: `${seed.date}T10:25:00Z`,
    updated_at: `${seed.date}T10:25:00Z`,
  };
});

// The two "Bunq test" rows are a legitimate repetition, not a duplicate: they
// have different transaction ids and must remain as two movements. The
// duplicate queue uses a different synthetic pair to exercise the UI.
const lowConfidence = mockMovements.find(
  (movement) => movement.merchant === "PayPal *AliExpress",
);
const sumupMovement = mockMovements.find(
  (movement) => movement.merchant === "SUMUP *LA TAHONA",
);
if (lowConfidence && sumupMovement) {
  lowConfidence.duplicate_of = sumupMovement.id;
  lowConfidence.duplicate_score = 0.81;
  lowConfidence.review_reasons = [
    ...(lowConfidence.review_reasons ?? []),
    "Par candidato: importe y fecha próximos",
  ];
  sumupMovement.duplicate_of = lowConfidence.id;
  sumupMovement.duplicate_score = 0.81;
  sumupMovement.review_reasons = [
    ...(sumupMovement.review_reasons ?? []),
    "Par candidato: importe y fecha próximos",
  ];
}

export const mockMovementSummary = {
  pendientes: mockMovements.filter((movement) => movement.estado === "pendiente").length,
  sin_categoria: mockMovements.filter((movement) => !movement.classification?.categoria).length,
  duplicados: mockMovements.filter((movement) => Boolean(movement.duplicate_of)).length,
  transferencias: mockMovements.filter(
    (movement) => movement.kind === "transferencia_interna",
  ).length,
};

function matchesTab(movement: Movement, tab: string | undefined): boolean {
  switch (tab) {
    case "por-revisar":
      return (
        movement.estado === "pendiente" ||
        (movement.classification?.confianza ?? 1) < 0.8 ||
        Boolean(movement.review_reasons?.length)
      );
    case "duplicados":
      return Boolean(movement.duplicate_of);
    case "transferencias":
      return movement.kind === "transferencia_interna";
    case "sin-categorizar":
      return !movement.classification?.categoria;
    default:
      return true;
  }
}

export function getMockMovements(
  filters: {
    tab?: string;
    q?: string;
    estado?: string;
    kind?: string;
    account_id?: string;
    categoria_id?: string;
    origen?: string;
    min_confidence?: string;
    from?: string;
    to?: string;
    page?: number;
    page_size?: number;
  } = {},
): MovementListResponse {
  const pageSize = filters.page_size ?? 25;
  const page = filters.page ?? 1;
  const query = filters.q?.trim().toLowerCase();

  let items = mockMovements.filter((movement) => matchesTab(movement, filters.tab));

  if (query) {
    items = items.filter((movement) =>
      [movement.merchant, movement.description, movement.account?.nombre]
        .filter(Boolean)
        .some((value) => value?.toLowerCase().includes(query)),
    );
  }
  if (filters.estado) items = items.filter((item) => item.estado === filters.estado);
  if (filters.kind) items = items.filter((item) => item.kind === filters.kind);
  if (filters.account_id) {
    items = items.filter((item) => String(item.account_id) === filters.account_id);
  }
  if (filters.categoria_id) {
    items = items.filter(
      (item) => String(item.classification?.categoria_id ?? "") === filters.categoria_id,
    );
  }
  if (filters.origen) {
    items = items.filter((item) => item.classification?.origen === filters.origen);
  }
  if (filters.min_confidence) {
    const minimum = Number(filters.min_confidence);
    items = items.filter((item) => (item.classification?.confianza ?? 0) >= minimum);
  }
  if (filters.from) items = items.filter((item) => item.value_date >= filters.from!);
  if (filters.to) items = items.filter((item) => item.value_date <= filters.to!);

  const total = items.length;
  const start = (page - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    total,
    page,
    page_size: pageSize,
    next_cursor: start + pageSize < total ? String(page + 1) : null,
    summary: mockMovementSummary,
  };
}

export const mockImports: ImportSummary[] = [
  {
    id: 41,
    source: "trade_republic_csv",
    filename: "transactions_2026-07-01_2026-09-30.csv",
    mime_type: "text/csv",
    file_hash: "9f2c1a77b4e0d5c8a1f3",
    period_start: "2026-07-01",
    period_end: "2026-09-30",
    row_count: 312,
    movement_new_count: 298,
    movement_seen_count: 14,
    duplicate_count: 0,
    uncategorized_count: 18,
    status: "parsed",
    account_id: 1,
    account: { id: 1, nombre: "Trade Republic" },
    parser_version: "tr-csv-2.1",
    error: null,
    created_at: "2026-10-28T19:04:00Z",
    parsed_at: "2026-10-28T19:04:12Z",
  },
  {
    id: 40,
    source: "revolut_pdf",
    filename: "extracto_revolut_sep2026.pdf",
    mime_type: "application/pdf",
    file_hash: "3a8e2f90cc71b3f5d192",
    period_start: "2026-09-01",
    period_end: "2026-09-30",
    row_count: 96,
    movement_new_count: 94,
    movement_seen_count: 2,
    duplicate_count: 2,
    uncategorized_count: 6,
    status: "needs_review",
    account_id: 2,
    account: { id: 2, nombre: "Revolut" },
    parser_version: "revolut-pdf-0.9",
    error: null,
    created_at: "2026-10-20T08:16:00Z",
    parsed_at: "2026-10-20T08:16:41Z",
  },
  {
    id: 39,
    source: "trade_republic_csv",
    filename: "extracto_trade_republic_ene_jun_2026.csv",
    mime_type: "text/csv",
    file_hash: "bf01d87d3eaa5d61e0a0",
    period_start: "2026-01-01",
    period_end: "2026-06-30",
    row_count: 585,
    movement_new_count: 585,
    movement_seen_count: 0,
    duplicate_count: 8,
    uncategorized_count: 27,
    status: "parsed",
    account_id: 1,
    account: { id: 1, nombre: "Trade Republic" },
    parser_version: "tr-csv-2.0",
    error: null,
    created_at: "2026-07-26T17:02:00Z",
    parsed_at: "2026-07-26T17:02:18Z",
  },
  {
    id: 38,
    source: "image_receipt",
    filename: "recibo_ikea.jpg",
    mime_type: "image/jpeg",
    file_hash: "77aa45e39d01ff8a0d21",
    period_start: null,
    period_end: null,
    row_count: 0,
    movement_new_count: 0,
    movement_seen_count: 0,
    duplicate_count: 0,
    uncategorized_count: 0,
    status: "failed",
    account_id: null,
    account: null,
    parser_version: "receipt-vision-0.1",
    error: "No se pudo leer el total del recibo. Revisa la imagen o añade el gasto a mano.",
    created_at: "2026-10-18T12:44:00Z",
    parsed_at: null,
  },
];

const mockIncidences: ImportIncidence[] = [
  {
    id: 1,
    severity: "warning",
    code: "possible_duplicate",
    message: "2 filas con mismo importe, fecha y merchant. Revisar antes de aprobar.",
    row_index: 142,
  },
  {
    id: 2,
    severity: "info",
    code: "opening_positions",
    message: "15 posiciones de apertura detectadas en el PDF de valores.",
    row_index: null,
  },
  {
    id: 3,
    severity: "error",
    code: "balance_mismatch",
    message: "El balance final no coincide con la suma de movimientos (diferencia 0,02 €).",
    row_index: null,
  },
];

const mockRawRows: RawRow[] = [
  {
    id: 1,
    row_index: 1,
    row_hash: "a1b2c3",
    payload: {
      datetime: "2026-10-30T10:24:00Z",
      date: "2026-10-30",
      category: "CASH",
      type: "CARD_TRANSACTION",
      name: "Mercadona",
      amount: "-84.32",
      currency: "EUR",
      mcc_code: "5411",
      transaction_id: "c1a5…9f20",
    },
  },
  {
    id: 2,
    row_index: 2,
    row_hash: "d4e5f6",
    payload: {
      datetime: "2026-10-30T10:31:00Z",
      date: "2026-10-30",
      category: "CASH",
      type: "TRANSFER_INSTANT_OUTBOUND",
      name: "Bunq test",
      amount: "-2.00",
      currency: "EUR",
      counterparty_name: "Marcos Florez",
      transaction_id: "ff02…11ac",
    },
  },
  {
    id: 3,
    row_index: 3,
    row_hash: "a7b8c9",
    payload: {
      datetime: "2026-10-29T06:00:00Z",
      date: "2026-10-29",
      category: "CASH",
      type: "TRANSFER_INSTANT_INBOUND",
      name: "Acme Studio",
      amount: "3200.00",
      currency: "EUR",
      transaction_id: "1020…bb41",
    },
  },
];

export function getMockImport(id: number): ImportDetail {
  const summary = mockImports.find((item) => item.id === id) ?? mockImports[0];
  const transactions = mockMovements
    .filter((movement) => movement.source_label === summary.filename)
    .slice(0, 12);
  return {
    ...summary,
    transactions: transactions.length > 0 ? transactions : mockMovements.slice(0, 8),
    incidences: summary.status === "failed" ? mockIncidences.slice(2) : mockIncidences,
    raw_rows: mockRawRows,
    reconciliation_report:
      summary.status === "failed"
        ? null
        : {
            rows_ok: true,
            balance_difference: 0.02,
            total_amount: 18420.44,
          },
  };
}

const duplicatePair = [lowConfidence, sumupMovement].filter(
  (movement): movement is Movement => Boolean(movement),
);

export const mockDedupCandidates: DedupCandidate[] = [
  {
    id: 1,
    movement_a: duplicatePair[0] ?? mockMovements[0],
    movement_b: duplicatePair[1] ?? mockMovements[1],
    score: 0.81,
    motivo: "Importe similar, misma semana y merchant con prefijo de cobro.",
    estado: "pendiente",
    created_at: "2026-10-30T19:00:00Z",
  },
];

export const mockTransferSuggestions: TransferSuggestion[] = [
  {
    id: 1,
    outbound:
      mockMovements.find(
        (movement) => movement.merchant === "Transferencia a Marcos Florez",
      ) ?? mockMovements[0],
    inbound:
      mockMovements.find(
        (movement) => movement.merchant === "Transferencia de Marcos Florez",
      ) ?? mockMovements[1],
    score: 0.94,
    amount: 250,
    date: "2026-10-25",
    status: "pendiente",
  },
  {
    id: 2,
    outbound:
      mockMovements.find(
        (movement) => movement.merchant === "Transferencia a Bunq",
      ) ?? mockMovements[0],
    inbound:
      mockMovements.find(
        (movement) => movement.merchant === "Transferencia de Bunq",
      ) ?? mockMovements[1],
    score: 0.88,
    amount: 120,
    date: "2026-10-16",
    status: "pendiente",
  },
];

const positivePositions: Position[] = [
  {
    asset_id: 1,
    symbol: "IE00B4ND3602",
    isin: "IE00B4ND3602",
    nombre: "iShares MSCI World",
    asset_class: "etf",
    cantidad: 42.5,
    precio_medio: 85.1,
    precio_actual: 92.4,
    valor_actual: 3927,
    coste_total: 3616.75,
    pnl_no_realizado: 310.25,
    pnl_no_realizado_pct: 8.58,
    pnl_realizado: 0,
    peso: 0,
    moneda: "EUR",
    yf_ticker: "IWDA.AS",
    datos_incompletos: false,
  },
  {
    asset_id: 2,
    symbol: "SOL",
    isin: null,
    nombre: "Solana",
    asset_class: "cripto",
    cantidad: 12.4,
    precio_medio: 132,
    precio_actual: 148.2,
    valor_actual: 1837.68,
    coste_total: 1636.8,
    pnl_no_realizado: 200.88,
    pnl_no_realizado_pct: 12.27,
    pnl_realizado: 42.1,
    peso: 0,
    moneda: "EUR",
    yf_ticker: "SOL-EUR",
    datos_incompletos: false,
  },
  {
    asset_id: 3,
    symbol: "ETH",
    isin: null,
    nombre: "Ethereum",
    asset_class: "cripto",
    cantidad: 1.85,
    precio_medio: 2310,
    precio_actual: 2480,
    valor_actual: 4588,
    coste_total: 4273.5,
    pnl_no_realizado: 314.5,
    pnl_no_realizado_pct: 7.36,
    pnl_realizado: 0,
    peso: 0,
    moneda: "EUR",
    yf_ticker: "ETH-EUR",
    datos_incompletos: false,
  },
  {
    asset_id: 4,
    symbol: "IE00BK5BQT80",
    isin: "IE00BK5BQT80",
    nombre: "Vanguard FTSE All-World",
    asset_class: "etf",
    cantidad: 18.2,
    precio_medio: 109.4,
    precio_actual: 118.6,
    valor_actual: 2158.52,
    coste_total: 1991.08,
    pnl_no_realizado: 167.44,
    pnl_no_realizado_pct: 8.41,
    pnl_realizado: 0,
    peso: 0,
    moneda: "EUR",
    yf_ticker: "VWCE.DE",
    datos_incompletos: false,
  },
  {
    asset_id: 5,
    symbol: "AAPL",
    isin: "US0378331005",
    nombre: "Apple",
    asset_class: "stock",
    cantidad: 5,
    precio_medio: 198.4,
    precio_actual: 226.1,
    valor_actual: 1130.5,
    coste_total: 992,
    pnl_no_realizado: 138.5,
    pnl_no_realizado_pct: 13.96,
    pnl_realizado: 0,
    peso: 0,
    moneda: "EUR",
    yf_ticker: "AAPL",
    datos_incompletos: false,
  },
  {
    asset_id: 6,
    symbol: "MSFT",
    isin: "US5949181045",
    nombre: "Microsoft",
    asset_class: "stock",
    cantidad: 3,
    precio_medio: 388,
    precio_actual: 415.2,
    valor_actual: 1245.6,
    coste_total: 1164,
    pnl_no_realizado: 81.6,
    pnl_no_realizado_pct: 7.01,
    pnl_realizado: 0,
    peso: 0,
    moneda: "EUR",
    yf_ticker: "MSFT",
    datos_incompletos: false,
  },
  {
    asset_id: 7,
    symbol: "BTC",
    isin: null,
    nombre: "Bitcoin",
    asset_class: "cripto",
    cantidad: 0.062,
    precio_medio: 54000,
    precio_actual: 61200,
    valor_actual: 3794.4,
    coste_total: 3348,
    pnl_no_realizado: 446.4,
    pnl_no_realizado_pct: 13.33,
    pnl_realizado: 0,
    peso: 0,
    moneda: "EUR",
    yf_ticker: "BTC-EUR",
    datos_incompletos: false,
  },
  {
    asset_id: 8,
    symbol: "IE00B4L5Y983",
    isin: "IE00B4L5Y983",
    nombre: "iShares Core MSCI Emerging Markets",
    asset_class: "etf",
    cantidad: 30,
    precio_medio: 55.2,
    precio_actual: 58.4,
    valor_actual: 1752,
    coste_total: 1656,
    pnl_no_realizado: 96,
    pnl_no_realizado_pct: 5.8,
    pnl_realizado: 0,
    peso: 0,
    moneda: "EUR",
    yf_ticker: "EMIM.AS",
    datos_incompletos: false,
  },
  {
    asset_id: 9,
    symbol: "NVO",
    isin: "DK0062498333",
    nombre: "Novo Nordisk",
    asset_class: "stock",
    cantidad: 10,
    precio_medio: 118.9,
    precio_actual: 102.3,
    valor_actual: 1023,
    coste_total: 1189,
    pnl_no_realizado: -166,
    pnl_no_realizado_pct: -13.96,
    pnl_realizado: 0,
    peso: 0,
    moneda: "EUR",
    yf_ticker: "NOVO-B.CO",
    datos_incompletos: false,
  },
  {
    asset_id: 10,
    symbol: "ASML",
    isin: "NL0010273215",
    nombre: "ASML",
    asset_class: "stock",
    cantidad: 1,
    precio_medio: 690,
    precio_actual: 742.5,
    valor_actual: 742.5,
    coste_total: 690,
    pnl_no_realizado: 52.5,
    pnl_no_realizado_pct: 7.61,
    pnl_realizado: 0,
    peso: 0,
    moneda: "EUR",
    yf_ticker: "ASML.AS",
    datos_incompletos: false,
  },
  {
    asset_id: 11,
    symbol: "IE00B4K48X80",
    isin: "IE00B4K48X80",
    nombre: "iShares MSCI Europe",
    asset_class: "etf",
    cantidad: 14,
    precio_medio: 74.2,
    precio_actual: 79.5,
    valor_actual: 1113,
    coste_total: 1038.8,
    pnl_no_realizado: 74.2,
    pnl_no_realizado_pct: 7.14,
    pnl_realizado: 0,
    peso: 0,
    moneda: "EUR",
    yf_ticker: "IMEU.AS",
    datos_incompletos: false,
  },
  {
    asset_id: 12,
    symbol: "XYZ",
    isin: null,
    nombre: "Activo sin precio actualizado",
    asset_class: "otro",
    cantidad: 4,
    precio_medio: 50,
    precio_actual: null,
    valor_actual: 0,
    coste_total: 200,
    pnl_no_realizado: -200,
    pnl_no_realizado_pct: -100,
    pnl_realizado: 0,
    peso: 0,
    moneda: "EUR",
    yf_ticker: null,
    datos_incompletos: true,
  },
];

export function getMockPortfolio(): PortfolioSummary {
  const valorTotal = positivePositions.reduce(
    (sum, item) => sum + toNumber(item.valor_actual),
    0,
  );
  const costeTotal = positivePositions.reduce(
    (sum, item) => sum + toNumber(item.coste_total),
    0,
  );
  const posiciones = positivePositions.map((position) => ({
    ...position,
    peso: valorTotal > 0 ? (toNumber(position.valor_actual) / valorTotal) * 100 : 0,
  }));

  const classTotals = new Map<string, number>();
  for (const position of posiciones) {
    classTotals.set(
      position.asset_class,
      (classTotals.get(position.asset_class) ?? 0) + toNumber(position.valor_actual),
    );
  }

  const classLabels: Record<string, string> = {
    etf: "ETFs",
    cripto: "Cripto",
    stock: "Acciones",
    fondo: "Fondos",
    otro: "Otros",
  };

  return {
    posiciones,
    valor_total: valorTotal,
    coste_total: costeTotal,
    pnl_no_realizado: valorTotal - costeTotal,
    pnl_realizado: 42.1,
    dividendos: 96.2,
    comisiones: 18.4,
    moneda: "EUR",
    asignacion: Array.from(classTotals.entries())
      .map(([key, value]) => ({
        label: classLabels[key] ?? key,
        value,
        peso: valorTotal > 0 ? (value / valorTotal) * 100 : 0,
      }))
      .sort((a, b) => b.value - a.value),
    avisos: [
      "Faltan posiciones de apertura de dos activos: el P&L histórico puede ser incompleto.",
      "1 posición con cantidad negativa oculta hasta conciliar el extracto de valores.",
      "Un activo no tiene precio actualizado (XYZ).",
    ],
    posiciones_negativas: [
      { asset_id: 13, symbol: "IWDA", cantidad: -3.08 },
    ],
    calculado_en: "2026-10-31T09:00:00Z",
  };
}

export const mockAnalytics: AnalyticsSummary = {
  period: { from: "2026-10-01", to: "2026-10-31", label: "Octubre 2026" },
  ingresos: 3420,
  gastos: 2184.62,
  flujo_neto: 1235.38,
  tasa_ahorro: 0.361,
  ingresos_prev: 3180,
  gastos_prev: 2410.44,
  flujo_neto_prev: 769.56,
  patrimonio_neto: 39983.2,
  patrimonio_neto_prev: 38742,
  pendientes: mockMovementSummary.pendientes,
  sin_categoria: mockMovementSummary.sin_categoria,
  duplicados: mockMovementSummary.duplicados,
  transferencias_sugeridas: mockTransferSuggestions.length,
};

export const mockCashflow: CashflowPoint[] = [
  { month: "2025-11", ingresos: 3200, gastos: 2280.44, neto: 919.56 },
  { month: "2025-12", ingresos: 3480, gastos: 3120.18, neto: 359.82 },
  { month: "2026-01", ingresos: 3200, gastos: 2450.7, neto: 749.3 },
  { month: "2026-02", ingresos: 3200, gastos: 2218.32, neto: 981.68 },
  { month: "2026-03", ingresos: 3260, gastos: 2388.94, neto: 871.06 },
  { month: "2026-04", ingresos: 3200, gastos: 2604.12, neto: 595.88 },
  { month: "2026-05", ingresos: 3320, gastos: 2312.4, neto: 1007.6 },
  { month: "2026-06", ingresos: 3200, gastos: 2780.26, neto: 419.74 },
  { month: "2026-07", ingresos: 3200, gastos: 2240.1, neto: 959.9 },
  { month: "2026-08", ingresos: 3260, gastos: 2960.72, neto: 299.28 },
  { month: "2026-09", ingresos: 3200, gastos: 2410.44, neto: 789.56 },
  { month: "2026-10", ingresos: 3420, gastos: 2184.62, neto: 1235.38 },
];

export const mockCategoryBreakdown: CategoryBreakdown[] = [
  {
    categoria_id: 2,
    categoria: "Vivienda",
    color: "#0ea5e9",
    total: 914.2,
    prev_total: 914.2,
    delta_pct: 0,
    movimientos: 3,
  },
  {
    categoria_id: 1,
    categoria: "Alimentación",
    color: "#16a34a",
    total: 428.6,
    prev_total: 392.18,
    delta_pct: 9.3,
    movimientos: 12,
  },
  {
    categoria_id: 7,
    categoria: "Compras",
    color: "#8b5cf6",
    total: 214.8,
    prev_total: 181.4,
    delta_pct: 18.4,
    movimientos: 6,
  },
  {
    categoria_id: 9,
    categoria: "Viajes",
    color: "#14b8a6",
    total: 210,
    prev_total: 0,
    delta_pct: 100,
    movimientos: 1,
  },
  {
    categoria_id: 3,
    categoria: "Transporte",
    color: "#f59e0b",
    total: 172.4,
    prev_total: 204.9,
    delta_pct: -15.9,
    movimientos: 9,
  },
  {
    categoria_id: 5,
    categoria: "Suscripciones",
    color: "#ec4899",
    total: 45.97,
    prev_total: 45.97,
    delta_pct: 0,
    movimientos: 4,
  },
  {
    categoria_id: 8,
    categoria: "Restaurantes",
    color: "#f97316",
    total: 41.4,
    prev_total: 73.8,
    delta_pct: -43.9,
    movimientos: 4,
  },
  {
    categoria_id: 6,
    categoria: "Salud",
    color: "#ef4444",
    total: 52.3,
    prev_total: 38.2,
    delta_pct: 36.9,
    movimientos: 2,
  },
];

export const mockDataHealth: DataHealth = {
  last_import_at: "2026-10-28T19:04:00Z",
  last_import_filename: "transactions_2026-07-01_2026-09-30.csv",
  auto_classified_pct: 91.4,
  corrections_last_week: 3,
  pending_count: mockMovementSummary.pendientes,
  uncategorized_count: mockMovementSummary.sin_categoria,
  duplicate_count: mockMovementSummary.duplicados,
  internal_transfers_pending: 2,
  accounts_total: mockAccounts.length,
  accounts_unreconciled: 3,
  negative_positions: 1,
  missing_opening_positions: true,
  stale_movements_without_classification: 7,
};

export const mockDailyDensity: DailyDensity[] = Array.from({ length: 31 }, (_, index) => {
  const day = index + 1;
  const counts = [0, 1, 2, 0, 3, 1, 0, 2, 4, 5, 1, 0, 2, 3, 1, 0, 4, 2, 1, 3, 0, 2, 5, 1, 0, 3, 2, 1, 0, 2, 1];
  return { date: `2026-10-${String(day).padStart(2, "0")}`, count: counts[index] };
});

export const mockRules: ClassificationRule[] = [
  {
    id: 1,
    nombre: "MCC supermercados",
    descripcion: "Supermercados y alimentación",
    prioridad: 120,
    campo: "mcc_code",
    operador: "mcc_in",
    valor: "5411,5412",
    set_categoria: "Alimentación",
    set_subtipo: "Supermercado",
    activa: true,
    auto_aprobar: true,
    hit_count: 128,
    last_hit_at: "2026-10-30T10:24:00Z",
    creado_en: "2026-07-26T17:00:00Z",
  },
  {
    id: 2,
    nombre: "Revolut propia",
    descripcion: "Cualquier movimiento que mencione Revolut",
    prioridad: 110,
    campo: "description_clean",
    operador: "contains",
    valor: "REVOLUT",
    set_categoria: "Transferencias",
    set_subtipo: null,
    activa: true,
    auto_aprobar: true,
    hit_count: 64,
    last_hit_at: "2026-10-29T09:12:00Z",
    creado_en: "2026-07-26T17:00:00Z",
  },
  {
    id: 3,
    nombre: "Suscripciones conocidas",
    descripcion: "Netflix, Spotify, Amazon Prime",
    prioridad: 105,
    campo: "merchant",
    operador: "regex",
    valor: "^(NETFLIX|SPOTIFY|AMAZON PRIME)",
    set_categoria: "Suscripciones",
    set_subtipo: null,
    activa: true,
    auto_aprobar: true,
    hit_count: 31,
    last_hit_at: "2026-10-27T04:10:00Z",
    creado_en: "2026-08-02T10:00:00Z",
  },
  {
    id: 4,
    nombre: "Combustible",
    descripcion: "Estaciones de servicio",
    prioridad: 100,
    campo: "mcc_code",
    operador: "mcc_in",
    valor: "5541,5542",
    set_categoria: "Transporte",
    set_subtipo: "Combustible",
    activa: true,
    auto_aprobar: false,
    hit_count: 22,
    last_hit_at: "2026-10-27T18:20:00Z",
    creado_en: "2026-08-12T09:30:00Z",
  },
  {
    id: 5,
    nombre: "Autoaprendizaje: Mercadona",
    descripcion: "Generada desde 14 decisiones manuales",
    prioridad: 160,
    campo: "merchant",
    operador: "contains",
    valor: "MERCADONA",
    set_categoria: "Alimentación",
    set_subtipo: "Supermercado",
    activa: true,
    auto_aprobar: true,
    hit_count: 14,
    last_hit_at: "2026-10-30T10:24:00Z",
    creado_en: "2026-10-29T11:00:00Z",
  },
  {
    id: 6,
    nombre: "Cargos desconocidos",
    descripcion: "Regla pausada durante la revisión de taxonomía",
    prioridad: 40,
    campo: "descripcion",
    operador: "contains",
    valor: "RECIBO",
    set_categoria: "Otros",
    set_subtipo: null,
    activa: false,
    auto_aprobar: false,
    hit_count: 3,
    last_hit_at: "2026-09-14T08:00:00Z",
    creado_en: "2026-09-01T08:00:00Z",
  },
];
