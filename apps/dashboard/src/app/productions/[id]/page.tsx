import type { Metadata } from "next";
import { ProductionDetailContainer } from "@/components/production/ProductionDetailContainer";

export const metadata: Metadata = { title: "Production" };

export default async function ProductionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ProductionDetailContainer id={decodeURIComponent(id)} />;
}
