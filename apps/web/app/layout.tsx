import "./globals.css";

export const metadata = {
  title: "Raku RAG",
  description: "Industry knowledge assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
