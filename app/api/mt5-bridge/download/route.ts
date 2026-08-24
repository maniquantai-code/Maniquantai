import { NextResponse } from "next/server";

const GITHUB_SOURCE =
  "https://api.github.com/repos/maniquantai-code/Maniquantai/contents/mt5-bridge/ea/ManiQuantAI_MT5_Bridge.mq5?ref=main";

export async function GET() {
  const response = await fetch(GITHUB_SOURCE, {
    headers: {
      Accept: "application/vnd.github+json",
      "User-Agent": "ManiQuantAI-MT5-Bridge-Downloader",
    },
    cache: "no-store",
  });

  if (!response.ok) {
    return NextResponse.json(
      { detail: "The ManiQuantAI MT5 Bridge source is temporarily unavailable." },
      { status: 502 },
    );
  }

  const payload = (await response.json()) as { content?: string; encoding?: string };
  if (!payload.content || payload.encoding !== "base64") {
    return NextResponse.json(
      { detail: "The ManiQuantAI MT5 Bridge source could not be read." },
      { status: 502 },
    );
  }

  const source = Buffer.from(payload.content.replace(/\n/g, ""), "base64");

  return new NextResponse(source, {
    status: 200,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Content-Disposition": 'attachment; filename="ManiQuantAI_MT5_Bridge.mq5"',
      "Cache-Control": "no-store",
    },
  });
}
