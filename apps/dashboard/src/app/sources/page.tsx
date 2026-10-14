import type { Metadata } from "next";
import { SourcesPage } from "@/components/sources/SourcesPage";

export const metadata: Metadata = { title: "Sources" };

export default function Page() {
  return <SourcesPage />;
}
