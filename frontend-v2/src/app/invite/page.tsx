import type { Metadata } from "next";
import { Suspense } from "react";
import { InviteForm } from "./invite-form";

export const metadata: Metadata = {
  title: "Invitación",
  description: "Crea tu cuenta y elige tu contraseña.",
};

export default function InvitePage() {
  return (
    <Suspense fallback={null}>
      <InviteForm />
    </Suspense>
  );
}
