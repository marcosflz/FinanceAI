import type { Metadata } from "next";
import { RecoverForm } from "./recover-form";

export const metadata: Metadata = {
  title: "Recuperar cuenta",
  description: "Restablece tu contraseña con tu clave de recuperación.",
};

export default function RecoverPage() {
  return <RecoverForm />;
}
