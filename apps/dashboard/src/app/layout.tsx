import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "CineForge AI", template: "%s · CineForge AI" },
  description: "Operator dashboard for the CineForge AI multi-agent cinematic video engine.",
};

export const viewport: Viewport = {
  themeColor: "#06060a",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen font-sans text-zinc-200 antialiased">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
