import type { Metadata } from "next";
import { ThemeDetail } from "@/components/themes/ThemeDetail";

export const metadata: Metadata = { title: "Theme" };

export default async function ThemePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ThemeDetail id={decodeURIComponent(id)} />;
}
