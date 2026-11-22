"use client";

import { PageHeader } from "@/components/ui/page-header";
import { AssistantSection } from "@/components/settings/assistant-section";
import { ModelsSection } from "@/components/settings/models-section";

/** Configuración de IA: proveedores y memoria del asistente, y modelos de importación. */
export function AiSettingsView() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="IA"
        title="Configuración"
        description="Proveedores y memoria del asistente, y los modelos que clasifican tus importaciones."
      />
      <section className="space-y-3" aria-labelledby="ai-assistant-settings">
        <h2 id="ai-assistant-settings" className="text-[13px] font-semibold">
          Asistente
        </h2>
        <AssistantSection />
      </section>
      <section className="space-y-3" aria-labelledby="ai-import-models">
        <div>
          <h2 id="ai-import-models" className="text-[13px] font-semibold">
            Modelos de importación
          </h2>
          <p className="text-[12px] text-muted-foreground">
            Clasifican los movimientos de los extractos que importas.
          </p>
        </div>
        <ModelsSection />
      </section>
    </div>
  );
}
