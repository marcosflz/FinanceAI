import type { Metadata } from "next";
import { Suspense } from "react";
import { MovementsView } from "@/components/movements/movements-view";
import { PageSkeleton } from "@/components/ui/feedback";

export const metadata: Metadata = {
  title: "Movimientos",
};

export default function MovementsPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <MovementsView />
    </Suspense>
  );
}
