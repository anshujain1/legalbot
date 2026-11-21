import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JustAi — Your Legal AI assistant",
  description: "Let's make Legal AI simpler for all!",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
