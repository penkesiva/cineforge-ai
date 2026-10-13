"use client";

import { ErrorState } from "@/components/ui";

export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <ErrorState title="This page hit an unexpected error" error={error} onRetry={reset} />;
}
