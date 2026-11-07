import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Acceso",
  description: "Accede a tu panel financiero personal.",
};

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-background">
          <div className="skeleton h-8 w-40" />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
