import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND = (process.env.MANIQUANT_BACKEND_URL || process.env.BACKEND_API_URL || "").replace(/\/$/, "");

function localBackendUrl(req: NextRequest, path: string[]) {
  const url = new URL("/api", req.url);
  url.searchParams.set("__path", `/market-intelligence/${path.join("/")}`);
  return url.toString();
}

async function forward(req: NextRequest, path: string[]) {
  // Prefer a separately deployed FastAPI backend when configured. Otherwise use
  // the FastAPI function already deployed with this same Vercel project.
  const target = BACKEND
    ? `${BACKEND}/api/market-intelligence/${path.join("/")}${req.nextUrl.search}`
    : localBackendUrl(req, path);

  const headers = new Headers();
  const auth = req.headers.get("authorization");
  if (auth) headers.set("authorization", auth);
  headers.set("accept", "application/json");
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (req.method !== "GET" && req.method !== "HEAD") init.body = await req.text();

  try {
    const response = await fetch(target, init);
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") || "application/json" },
    });
  } catch (error) {
    return NextResponse.json(
      {
        detail: "Market intelligence backend unavailable",
        error: String(error),
        backend: BACKEND ? "external" : "same-vercel-project",
      },
      { status: 502 },
    );
  }
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path || []);
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path || []);
}

export async function OPTIONS() {
  return new NextResponse(null, { status: 204 });
}
