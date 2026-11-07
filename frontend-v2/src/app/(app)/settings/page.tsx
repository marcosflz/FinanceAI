import type { Metadata } from "next";
import { Suspense } from "react";
import { SettingsView } from "@/components/settings/settings-view";
import { PageSkeleton } from "@/components/ui/feedback";

export const metadata: Metadata = {
  title: "Ajustes",
};

export default function SettingsPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <SettingsView />
    </Suspense>
  );
}
