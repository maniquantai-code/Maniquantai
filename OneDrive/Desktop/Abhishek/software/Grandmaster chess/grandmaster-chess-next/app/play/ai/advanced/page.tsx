import type { Metadata } from 'next';
import { PlayAIPage } from '@/components/pages/PlayAIPage';

export const metadata: Metadata = {
  title: 'Play Chess vs Advanced AI (Master Level) — Free Online',
  description:
    'Play free online chess against an advanced, master-strength AI opponent. A serious tactical and strategic challenge for experienced players.',
  alternates: { canonical: '/play/ai/advanced' },
};

export default function Page() {
  return <PlayAIPage initialDifficulty="advanced" />;
}
