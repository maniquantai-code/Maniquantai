# Grandmaster Chess Online — Next.js Edition

Migrated from a Vite + React SPA to Next.js 15 (App Router) for real
server-rendered pages, per-route SEO metadata, structured data, and a new
blog/content system. All game logic, the board, the AI engine, sounds, and
storage are the original code, ported as-is.

## What changed and why

The old app was a client-only SPA: `<div id="root">` and everything rendered
after JavaScript loaded. That's fine for the interactive game itself, but it
meant Google saw empty HTML on `/play`, `/learn/*`, `/faq`, etc. — no title,
no meta description, no content to index.

This version:

- Uses **Next.js App Router** with real file-based routes matching the old
  paths (`/play/ai`, `/learn/chess-rules`, `/faq`, ...).
- **Server-renders every page** on first load — view-source on any page now
  shows real HTML content and JSON-LD, not an empty div.
- Content pages (home, learn guides, FAQ, blog) are prerendered at build
  time (SSG) for maximum speed and crawlability.
- Interactive pages (`/play/ai`, `/play/friends`, `/play/local`,
  `/dashboard`) still render the exact same React game components you had —
  they're marked as Client Components but are still server-rendered on
  first paint, so they benefit from real HTML too.
- Adds a full **blog** at `/blog` (SSG, Markdown-based) with 6 starter
  articles targeting real chess search queries, internally linked to your
  play/learn pages.
- Adds `sitemap.xml`, `robots.txt`, `llms.txt`, Open Graph/Twitter tags,
  and JSON-LD (WebApplication, WebSite, Organization, Article, FAQPage,
  BreadcrumbList) sitewide.
- 301 redirects from the old short URLs (`/learn/rules`, `/play`, etc.) to
  the new canonical ones, so nothing breaks and no link equity is lost.

## Project structure

```
app/                    Next.js routes (pages, layouts, metadata)
  blog/                 Blog index, [slug] posts, category pages
  learn/, play/, faq/, dashboard/
  sitemap.ts, robots.ts
components/             All ported UI components (board, navbar, modals, etc.)
  pages/                Ported page-level components (former src/pages)
  blog/                 Blog-specific UI (post cards)
lib/                    Chess engine, audio, storage, blog content loader, SEO helpers
services/               Multiplayer WebSocket client
content/blog/           Markdown blog posts (frontmatter + body)
types/                  Shared TypeScript types
ws-server/              STANDALONE multiplayer WebSocket server (see below)
```

## Why the WebSocket server is separate

Next.js (particularly on Vercel or other serverless targets) doesn't support
long-lived WebSocket connections. `/play/friends` real-time multiplayer now
runs against a small standalone Node service in `ws-server/` — same game
logic as before (room codes, chess.js validation, clocks), just decoupled
from the page-serving app. See `ws-server/README.md`.

Set `NEXT_PUBLIC_WS_URL` in the Next.js app's environment to point at wherever
you deploy it.

## Running locally

```bash
# Main site (pages, blog, SEO)
npm install
cp .env.example .env.local   # set NEXT_PUBLIC_SITE_URL, NEXT_PUBLIC_WS_URL
npm run dev                  # http://localhost:3000

# Multiplayer server (separate terminal)
cd ws-server
npm install
npm run dev                  # ws://localhost:3001/ws
```

## Deploying

- **Next.js app**: Vercel is the path of least resistance (zero config for
  App Router SSG/SSR, image optimization, redirects). Netlify, Railway, or a
  Docker/Node server also work — this is a standard Next.js app, nothing
  Vercel-specific in the code.
- **ws-server**: needs a host that keeps a process alive — Railway, Render,
  Fly.io, or a small VPS. Not deployable to Vercel serverless functions.

## Adding a new blog post

Drop a new Markdown file in `content/blog/` with frontmatter:

```md
---
title: "Your Post Title"
description: "One or two sentences for meta description and card preview."
date: "2026-08-15"
author: "Grandmaster Chess Editorial Team"
category: "Strategy"
tags: ["chess", "tactics"]
readingMinutes: 6
---

Your content in Markdown...
```

It's picked up automatically — no code changes needed. The slug is the
filename with any leading `NN-` ordering prefix and `.md` stripped.

## SEO/AEO checklist covered

- [x] Per-page title/description/canonical
- [x] Open Graph + Twitter Cards
- [x] `sitemap.xml` (dynamic, includes all blog posts/categories)
- [x] `robots.txt` (blocks `/dashboard`, ephemeral `/play/friends/[code]`)
- [x] `llms.txt` for AI answer engines
- [x] JSON-LD: WebApplication, WebSite, Organization, Article, FAQPage,
      BreadcrumbList
- [x] Semantic headings, internal linking between blog ↔ play/learn pages
- [x] 301 redirects from legacy URLs
- [x] Real server-rendered HTML on every route (verified via build output)
