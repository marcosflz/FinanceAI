import type { Metadata } from "next";
import { Suspense } from "react";
import { AssistantView } from "@/components/assistant/assistant-view";
import { PageSkeleton } from "@/components/ui/feedback";

export const metadata: Metadata = { title: "Asistente" };

export default function AssistantPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <AssistantView />
    </Suspense>
  );
}
