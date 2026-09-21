import type { Metadata, Viewport } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'Mega Cérebro', description: 'Seu conhecimento conectado à execução.', manifest: '/manifest.webmanifest', appleWebApp: { capable: true, title: 'Mega Cérebro', statusBarStyle: 'black-translucent' } };
export const viewport: Viewport = { width: 'device-width', initialScale: 1, themeColor: '#080e1b' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="pt-BR"><body>{children}</body></html>; }
