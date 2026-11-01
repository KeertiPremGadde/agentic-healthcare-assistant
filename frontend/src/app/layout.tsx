import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AppHeader } from "@/components/app-header";
import { DisclaimerBanner } from "@/components/disclaimer-banner";
import { THEME_INIT_SCRIPT } from "@/components/theme-toggle";
import { UserScope } from "@/components/user-scope";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "MedAgent",
  description:
    "An agentic healthcare assistant demo: medical Q&A with sources, doctor search and booking.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "light dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="flex min-h-dvh flex-col">
        <a
          href="#main"
          className="focus:bg-card sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:px-3 focus:py-2 focus:shadow"
        >
          Skip to content
        </a>
        <AuthProvider>
          <AppHeader />
          <DisclaimerBanner />
          <main id="main" className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 py-4">
            <UserScope>{children}</UserScope>
          </main>
        </AuthProvider>
      </body>
    </html>
  );
}
