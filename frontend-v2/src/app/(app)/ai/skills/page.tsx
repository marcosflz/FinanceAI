import type { Metadata } from "next";
import { SkillsLibrary } from "@/components/skills/skills-library";

export const metadata: Metadata = { title: "Skills" };

export default function SkillsPage() {
  return <SkillsLibrary />;
}
