import type { Metadata } from 'next';
import { HomePage } from '@/components/pages/HomePage';
import { SITE_NAME } from '@/lib/site-config';

export const metadata: Metadata = {
  title: `${SITE_NAME} | Play Free Chess with Friends & AI`,
  description:
    'Play free online chess with friends or challenge AI opponents across basic, intermediate and advanced difficulty levels. Real-time multiplayer rooms, chess clocks, move history, and strategy guides.',
  alternates: { canonical: '/' },
};

export default function Page() {
  return <HomePage />;
}
