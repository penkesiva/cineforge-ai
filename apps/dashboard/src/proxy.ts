import { NextResponse, type NextRequest } from "next/server";
import { apiInternalUrl } from "./lib/apiTarget";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  return NextResponse.rewrite(new URL(`${pathname}${search}`, `${apiInternalUrl()}/`));
}

export const config = {
  matcher: ["/api/v1/:path*", "/health", "/health/live"],
};
