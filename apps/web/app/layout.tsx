import "./globals.css";
import Sidebar from "./components/Sidebar";

export const metadata = {
  title: "Raku RAG",
  description: "Industry knowledge assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <Sidebar />
          {children}
        </div>
      </body>
    </html>
  );
}
