import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "JJFlipBook - PDF 플립북 뷰어",
  description: "PDF 문서를 웹에서 편안한 3D 플립 넘김 책자로 감상할 수 있는  스마트 뷰어 서비스입니다.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
};

import AuthGuard from "../components/AuthGuard";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <body>
        {/* Android 감지: is-android 클래스를 html에 추가하여 Android 전용 GPU 핫픽스를 iOS와 격리 */}
        <script dangerouslySetInnerHTML={{__html: `if(/Android/i.test(navigator.userAgent))document.documentElement.classList.add('is-android')`}} />
        <AuthGuard>
          {children}
        </AuthGuard>
      </body>
    </html>
  );
}
