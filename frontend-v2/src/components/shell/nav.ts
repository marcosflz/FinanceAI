import {
  Bot,
  SlidersHorizontal,
  ChartNoAxesCombined,
  LayoutDashboard,
  ListFilter,
  Settings,
  Wand2,
  Sparkles,
  Target,
  UploadCloud,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  shortLabel: string;
  icon: LucideIcon;
  description: string;
  keywords: string[];
}

export const navItems: NavItem[] = [
  {
    href: "/",
    label: "Dashboard",
    shortLabel: "Inicio",
    icon: LayoutDashboard,
    description: "Flujo, patrimonio y salud de datos",
    keywords: ["inicio", "resumen", "dashboard", "kpi"],
  },
  {
    href: "/movements",
    label: "Movimientos",
    shortLabel: "Movim.",
    icon: ListFilter,
    description: "Bandeja de revisión y clasificación",
    keywords: ["bandeja", "revisar", "duplicados", "transferencias", "categorizar"],
  },
  {
    href: "/imports",
    label: "Importaciones",
    shortLabel: "Importar",
    icon: UploadCloud,
    description: "CSV, PDF, imágenes y extractos",
    keywords: ["importar", "csv", "pdf", "subir", "extracto"],
  },
  {
    href: "/accounts",
    label: "Cuentas",
    shortLabel: "Cuentas",
    icon: Wallet,
    description: "Saldos, IBAN y transferencias internas",
    keywords: ["cuenta", "iban", "revolut", "bunq", "saldo", "patrón"],
  },
  {
    href: "/portfolio",
    label: "Cartera",
    shortLabel: "Cartera",
    icon: ChartNoAxesCombined,
    description: "Posiciones, asignación y P&L",
    keywords: ["cartera", "inversión", "posiciones", "etf", "cripto", "p&l"],
  },
  {
    href: "/ai",
    label: "IA",
    shortLabel: "IA",
    icon: Sparkles,
    description: "Asistente, asesor, skills, automatizaciones y configuración de IA",
    keywords: ["ia", "inteligencia artificial", "chat", "asistente", "agente", "asesor", "skills", "bots", "memoria"],
  },
  {
    href: "/settings",
    label: "Ajustes",
    shortLabel: "Ajustes",
    icon: Settings,
    description: "Perfil, reglas, cuentas, seguridad y datos",
    keywords: ["ajustes", "configuración", "reglas", "modelos", "seguridad"],
  },
];

/** Subsecciones de IA: pestañas de /ai y entradas de la paleta de comandos. */
export const aiSections: NavItem[] = [
  {
    href: "/ai/assistant",
    label: "Asistente",
    shortLabel: "Chat",
    icon: Sparkles,
    description: "Chat con tus finanzas y aprobaciones",
    keywords: ["ia", "chat", "asistente", "agente", "preguntar"],
  },
  {
    href: "/ai/advisor",
    label: "Asesor",
    shortLabel: "Asesor",
    icon: Target,
    description: "Consejos diarios de mantener, comprar o vender",
    keywords: ["asesor", "recomendaciones", "comprar", "vender", "mantener", "noticias", "mercado"],
  },
  {
    href: "/ai/skills",
    label: "Skills",
    shortLabel: "Skills",
    icon: Wand2,
    description: "Procedimientos reutilizables creados con ayuda",
    keywords: ["skills", "habilidades", "procedimientos", "crear skill", "plantillas"],
  },
  {
    href: "/ai/automations",
    label: "Automatizaciones",
    shortLabel: "Bots",
    icon: Bot,
    description: "Resúmenes y revisiones programadas",
    keywords: ["bots", "programar", "cron", "alertas", "resumen semanal"],
  },
  {
    href: "/ai/settings",
    label: "Configuración",
    shortLabel: "Config.",
    icon: SlidersHorizontal,
    description: "Proveedores, memoria del asistente y modelos de importación",
    keywords: ["proveedores", "claves", "api key", "memoria", "modelos", "jev", "opencode", "typesafe"],
  },
];

export const mobileNavItems = navItems.filter((item) =>
  ["/", "/movements", "/accounts", "/portfolio", "/ai"].includes(item.href),
);

export function sectionLabel(pathname: string): string {
  if (pathname === "/") return "Dashboard";
  const item = [...aiSections, ...navItems]
    .sort((a, b) => b.href.length - a.href.length)
    .find((entry) => entry.href !== "/" && pathname.startsWith(entry.href));
  return item?.label ?? "Financial Tools";
}
