import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: "Loan Data Verification Copilot",
  description: "Turn messy loan records into validated, traceable, verified data.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="bg-[#09111b]">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
