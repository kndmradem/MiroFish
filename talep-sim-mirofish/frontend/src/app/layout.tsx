import type { Metadata } from "next";
import "./globals.css";
import { ModeTabs } from "@/components/mode-tabs";

export const metadata: Metadata = {
  title: "Talep Simülasyonu",
  description: "Ürün talep, fiyat ve üretim dağıtımı simülasyonu",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="tr">
      <body className="antialiased">
        <ModeTabs />
        {children}
      </body>
    </html>
  );
}
