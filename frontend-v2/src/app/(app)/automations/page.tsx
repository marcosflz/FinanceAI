import type { Metadata } from "next";
import { AutomationsView } from "@/components/assistant/automations-view";

export const metadata: Metadata = { title: "Automatizaciones" };

export default function AutomationsPage() {
  return <AutomationsView />;
}
