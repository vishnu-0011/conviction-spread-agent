import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'ConvictionSpread · Paper Decision Cockpit',
  description:
    'An explainable Alpaca paper-options agent showing thesis, spread selection, and deterministic risk gates.',
  openGraph: {
    title: 'ConvictionSpread · Paper Decision Cockpit',
    description:
      'An explainable Alpaca paper-options agent showing thesis, spread selection, and deterministic risk gates.',
    images: ['/conviction-spread-social.png'],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'ConvictionSpread · Paper Decision Cockpit',
    description:
      'An explainable Alpaca paper-options agent showing thesis, spread selection, and deterministic risk gates.',
    images: ['/conviction-spread-social.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
