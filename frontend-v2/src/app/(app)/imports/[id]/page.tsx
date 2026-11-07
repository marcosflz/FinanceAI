import type { Metadata } from "next";
import { Suspense } from "react";
import { ImportDetailView } from "@/components/imports/import-detail-view";
import { PageSkeleton } from "@/components/ui/feedback";

export const metadata: Metadata = {
  title: "Detalle de importación",
};

export default function ImportDetailPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ImportDetailView />
    </Suspense>
  );
}
