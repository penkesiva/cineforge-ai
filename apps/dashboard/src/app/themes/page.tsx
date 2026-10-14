import type { Metadata } from "next";
import { ThemesPage } from "@/components/themes/ThemesPage";

export const metadata: Metadata = { title: "Themes" };

export default function Page() {
  return <ThemesPage />;
}
