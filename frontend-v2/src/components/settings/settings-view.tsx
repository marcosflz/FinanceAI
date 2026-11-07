"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  BrainCircuit,
  Database,
  FlaskConical,
  Info,
  Landmark,
  Settings2,
  ShieldCheck,
  Tags,
  type LucideIcon,
} from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { GeneralSection } from "@/components/settings/general-section";
import { CategoriesSection } from "@/components/settings/categories-section";
import { RulesSection } from "@/components/settings/rules-section";
import { AccountsSettingsSection } from "@/components/settings/accounts-section";
import { ModelsSection } from "@/components/settings/models-section";
import { PrivacySection } from "@/components/settings/privacy-section";
import { DataSection } from "@/components/settings/data-section";
import { cn } from "@/lib/utils";

const sections: Array<{
  value: string;
  label: string;
  description: string;
  icon: LucideIcon;
}> = [
  { value: "general", label: "General", description: "Perfil y apariencia", icon: Settings2 },
  { value: "categorias", label: "Categorías", description: "Taxonomía", icon: Tags },
  { value: "reglas", label: "Reglas", description: "Clasificación determinista", icon: FlaskConical },
  { value: "cuentas", label: "Cuentas", description: "IBAN y patrones", icon: Landmark },
  { value: "modelos", label: "Modelos", description: "Jev y OpenCode Go", icon: BrainCircuit },
  { value: "privacidad", label: "Privacidad", description: "Redacción y sesiones", icon: ShieldCheck },
  { value: "datos", label: "Datos", description: "Exportar y backup", icon: Database },
];

const sectionComponents: Record<string, React.ComponentType> = {
  general: GeneralSection,
  categorias: CategoriesSection,
  reglas: RulesSection,
  cuentas: AccountsSettingsSection,
  modelos: ModelsSection,
  privacidad: PrivacySection,
  datos: DataSection,
};

export function SettingsView() {
  const searchParams = useSearchParams();
  const raw = searchParams.get("section") ?? "general";
  const active = sections.some((section) => section.value === raw) ? raw : "general";
  const Section = sectionComponents[active] ?? GeneralSection;
  const activeMeta = sections.find((section) => section.value === active) ?? sections[0];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Configuración"
        title="Ajustes"
        description="Perfil, taxonomía, reglas, cuentas, modelos y datos. Las secciones están separadas para que cada cambio tenga un contrato y una auditoría claros."
        actions={
          <Badge variant="outline">
            <span className="num text-[10px]">Configuración real</span>
          </Badge>
        }
      />

      <div className="flex items-start gap-2 rounded-lg border border-border bg-card px-3 py-2.5 text-[11px] leading-5 text-muted-foreground">
        <Info className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
        <p>
          Perfil, seguridad, cuentas, modelos, categorías y etiquetas ya persisten en
          el backend. Los formularios de reglas/datos siguen siendo visuales y de
          contrato. La gestión de cuentas también está en{" "}
          <Link href="/accounts" className="font-medium text-foreground underline underline-offset-2">/accounts</Link>.
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-[196px_minmax(0,1fr)]">
        <nav
          className="scrollbar-thin -mx-1 flex flex-wrap gap-1 px-1 pb-1 lg:sticky lg:top-[76px] lg:mx-0 lg:h-fit lg:flex-col lg:flex-nowrap lg:overflow-visible lg:px-0"
          aria-label="Secciones de ajustes"
        >
          {sections.map((section) => {
            const Icon = section.icon;
            const isActive = section.value === active;
            return (
              <Link
                key={section.value}
                href={`/settings?section=${section.value}`}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors lg:w-full",
                  isActive
                    ? "bg-accent-soft text-accent-soft-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon
                  className={cn("size-3.5 shrink-0", isActive ? "text-accent" : "")}
                  aria-hidden
                />
                <span className="min-w-0">
                  <span className="block text-[12px] font-medium">{section.label}</span>
                  <span className="hidden truncate text-[9px] opacity-65 lg:block">
                    {section.description}
                  </span>
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="min-w-0">
          <div className="mb-3 flex items-center justify-between gap-2 lg:hidden">
            <p className="text-[11px] text-muted-foreground">{activeMeta.description}</p>
          </div>
          <Section />
        </div>
      </div>
    </div>
  );
}
