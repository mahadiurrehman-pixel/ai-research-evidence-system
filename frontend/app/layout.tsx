import type { Metadata } from "next";
import "./globals.css";
import { TopNav } from "@/components/layout/TopNav";

export const metadata: Metadata = {
  title: "Reality Checker — AI Evidence Intelligence",
  description:
    "Investigate claims, compare evidence, and verify statements with AI-powered research analysis.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen">
        <TopNav />
        <main className="pt-14">{children}</main>
      </body>
    </html>
  );
}