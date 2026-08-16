import type { Metadata } from 'next';
import { PlayFriendsPage } from '@/components/pages/PlayFriendsPage';

export const metadata: Metadata = {
  title: 'Play Chess with Friends Online — Free Multiplayer Rooms',
  description:
    'Create a free private chess room and invite a friend with a shareable code. Real-time multiplayer, synced chess clocks, chat, and no sign-up required.',
  alternates: { canonical: '/play/friends' },
};

export default function Page() {
  return <PlayFriendsPage />;
}
