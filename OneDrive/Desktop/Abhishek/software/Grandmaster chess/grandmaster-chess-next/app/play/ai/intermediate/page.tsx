import type { Metadata } from 'next';
import { PlayAIPage } from '@/components/pages/PlayAIPage';

export const metadata: Metadata = {
  title: 'Play Chess vs Intermediate AI (Casual Level) — Free Online',
  description:
    'Play free online chess against an intermediate AI opponent — a solid, casual-strength challenge for players comfortable with the basics.',
  alternates: { canonical: '/play/ai/intermediate' },
};

export default function Page() {
  return <PlayAIPage initialDifficulty="intermediate" />;
}
