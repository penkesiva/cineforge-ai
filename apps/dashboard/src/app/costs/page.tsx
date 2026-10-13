import type { Metadata } from "next";
import { CostsPage } from "@/components/costs/CostsPage";

export const metadata: Metadata = { title: "Costs" };

export default function Page() {
  return <CostsPage />;
}
