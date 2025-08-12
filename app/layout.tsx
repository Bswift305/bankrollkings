import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "BankrollKings",
  description: "Next.js + Supabase starter",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body style={{ margin: 0 }}>{children}</body>
    </html>
  );
}
