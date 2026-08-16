# Grandmaster Chess — Multiplayer WebSocket Server

Standalone real-time server for `/play/friends` rooms. Kept separate from the
Next.js app because Next.js (especially on serverless targets like Vercel)
doesn't support long-lived WebSocket connections.

## Run locally

```bash
npm install
npm run dev
```

Server starts on `PORT` (default `3001`) with a WebSocket endpoint at `/ws`
and a health check at `/api/health`.

## Deploy

Any Node host that supports persistent connections works: Railway, Render,
Fly.io, a small VPS, or a Docker container. Build with `npm run build`, run
with `npm start`.

Point the Next.js app at this server by setting `NEXT_PUBLIC_WS_URL` (e.g.
`wss://ws.yourdomain.com`) in its environment.
