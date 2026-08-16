import type { Metadata } from 'next';
import { PlayAIPage } from '@/components/pages/PlayAIPage';

export const metadata: Metadata = {
  title: 'Play Chess vs Basic AI (Beginner Level) — Free Online',
  description:
    'Play free online chess against a beginner-friendly AI opponent. Perfect for learning openings, basic tactics, and getting comfortable with the rules.',
  alternates: { canonical: '/play/ai/basic' },
};

export default function Page() {
  return <PlayAIPage initialDifficulty="basic" />;
}
