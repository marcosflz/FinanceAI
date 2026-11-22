import type { Metadata } from "next";
import { AiSettingsView } from "@/components/ai/ai-settings-view";

export const metadata: Metadata = { title: "Configuración de IA" };

export default function AiSettingsPage() {
  return <AiSettingsView />;
}
