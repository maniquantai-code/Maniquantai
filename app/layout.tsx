import "./globals.css";
import type { Metadata, Viewport } from "next";
import { StrategyProvider } from "@/context/StrategyContext";

export const metadata: Metadata = {
  title: "ManiQuantAI",
  description: "Vibe trading, done carefully.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <StrategyProvider>{children}</StrategyProvider>
      </body>
    </html>
  );
}
