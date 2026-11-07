import type { Metadata } from "next";
import { ImportsView } from "@/components/imports/imports-view";

export const metadata: Metadata = {
  title: "Importaciones",
};

export default function ImportsPage() {
  return <ImportsView />;
}
