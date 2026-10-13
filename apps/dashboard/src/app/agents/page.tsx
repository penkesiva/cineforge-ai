import type { Metadata } from "next";
import { AgentsRegistry } from "@/components/agents/AgentsRegistry";

export const metadata: Metadata = { title: "Agents" };

export default function Page() {
  return <AgentsRegistry />;
}
