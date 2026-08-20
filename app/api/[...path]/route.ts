import { NextRequest, NextResponse } from "next/server";

// Prefer an explicit backend URL when provided. Otherwise use the FastAPI
// service mounted at /backend in the same Vercel deployment.
const BACKEND_URL =
  process.env.BACKEND_URL ||
  (process.env.VERCEL_URL
    ? `https://${process.env.VERCEL_URL}/backend`
    : "http://localhost:8000");

async function proxy(req: NextRequest, method: string) {
  const path = req.nextUrl.pathname;
  const search = req.nextUrl.search;
  const authHeader = req.headers.get("authorization");

  const init: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(authHeader ? { Authorization: authHeader } : {}),
    },
  };

  if (method !== "GET" && method !== "HEAD") {
    try {
      init.body = JSON.stringify(await req.json());
    } catch {
      // Empty body is valid for some requests.
    }
  }

  try {
    const backendPath = `${BACKEND_URL}${path}${search}`;
    const res = await fetch(backendPath, init, { cache: "no-store" });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(
      {
        error: "backend_unreachable",
        detail: "FastAPI backend could not be reached.",
      },
      { status: 502 }
    );
  }
}

export async function GET(req: NextRequest) {
  return proxy(req, "GET");
}
export async function POST(req: NextRequest) {
  return proxy(req, "POST");
}
export async function PUT(req: NextRequest) {
  return proxy(req, "PUT");
}
export async function DELETE(req: NextRequest) {
  return proxy(req, "DELETE");
}
