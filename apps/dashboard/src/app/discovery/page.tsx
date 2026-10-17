import type { Metadata } from "next";
import { DiscoveryPage } from "@/components/discovery/DiscoveryPage";

export const metadata: Metadata = { title: "Discovery" };

export default function Page() {
  return <DiscoveryPage />;
}
