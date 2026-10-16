import type { Metadata } from "next";
import { DebugPage } from "@/components/debug/DebugPage";

export const metadata: Metadata = { title: "Debug · CineForge AI" };

export default function Page() {
  return <DebugPage />;
}
