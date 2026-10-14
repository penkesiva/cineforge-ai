import type { Metadata } from "next";
import { ProductionsPage } from "@/components/productions/ProductionsPage";

export const metadata: Metadata = { title: "Productions" };

export default function Page() {
  return <ProductionsPage />;
}
