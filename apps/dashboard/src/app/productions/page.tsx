import type { Metadata } from "next";
import { ProductionsPage } from "@/components/productions/ProductionsPage";

export const metadata: Metadata = { title: "Productions" };

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ topic?: string; video?: string; retrieved?: string }>;
}) {
  const params = await searchParams;
  const inspiration =
    params.topic && params.video && params.retrieved
      ? { topic: params.topic, videoId: params.video, retrievedAt: params.retrieved }
      : null;
  return <ProductionsPage inspiration={inspiration} />;
}
