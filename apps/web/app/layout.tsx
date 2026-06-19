export const metadata = {
  title: "raku-rag (local)",
  description: "Phase 0 web skeleton",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
