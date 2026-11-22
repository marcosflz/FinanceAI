import type { ReactNode } from "react";
import { AiTabs } from "@/components/ai/ai-tabs";

export default function AiLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <AiTabs />
      {children}
    </>
  );
}
