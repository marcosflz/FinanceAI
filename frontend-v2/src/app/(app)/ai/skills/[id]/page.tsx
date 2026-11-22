import type { Metadata } from "next";
import { SkillDetailView } from "@/components/skills/skill-detail";

export const metadata: Metadata = { title: "Skill" };

export default async function SkillPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SkillDetailView id={Number(id)} />;
}
