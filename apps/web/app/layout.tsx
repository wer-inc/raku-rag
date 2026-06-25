import "./globals.css";
import AppShell from "./components/AppShell";

export const metadata = {
  title: "Raku RAG",
  description: "Industry knowledge assistant",
};

// Explicit so mobile browsers render at device width and the responsive CSS engages.
export const viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
