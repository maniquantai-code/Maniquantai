import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

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
    }
  }

  try {
    const res = await fetch(`${BACKEND_URL}${path}${search}`, init);
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(
      { error: "backend_unreachable", detail: "Make sure the FastAPI server is running." },
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
