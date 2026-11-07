import {
  ChartNoAxesCombined,
  LayoutDashboard,
  ListFilter,
  Settings,
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
    href: "/settings",
    label: "Ajustes",
    shortLabel: "Ajustes",
    icon: Settings,
    description: "Reglas, modelos, privacidad y datos",
    keywords: ["ajustes", "configuración", "reglas", "modelos", "seguridad"],
  },
];

export const mobileNavItems = navItems.filter((item) =>
  ["/", "/movements", "/imports", "/accounts", "/portfolio"].includes(item.href),
);

export function sectionLabel(pathname: string): string {
  if (pathname === "/") return "Dashboard";
  const item = [...navItems]
    .sort((a, b) => b.href.length - a.href.length)
    .find((entry) => entry.href !== "/" && pathname.startsWith(entry.href));
  return item?.label ?? "Financial Tools";
}
