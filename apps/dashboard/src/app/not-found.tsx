import Link from "next/link";
import { EmptyState } from "@/components/ui";

export default function NotFound() {
  return (
    <EmptyState title="Page not found">
      <Link href="/" className="text-sky-300 hover:underline">
        Back to overview
      </Link>
    </EmptyState>
  );
}
