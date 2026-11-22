import type { Metadata } from "next";
import { SkillDraftEditor } from "@/components/skills/draft-editor";

export const metadata: Metadata = { title: "Creador de skills" };

export default async function SkillDraftPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SkillDraftEditor id={Number(id)} />;
}
