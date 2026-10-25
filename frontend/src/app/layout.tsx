import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Interview room — Candidate interview",
  description:
    "Review the role, share your resume, and join a voice interview about your experience and qualifications.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
