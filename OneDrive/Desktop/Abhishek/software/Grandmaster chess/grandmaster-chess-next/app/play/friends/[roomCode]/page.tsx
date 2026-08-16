import type { Metadata } from 'next';
import { PlayFriendsPage } from '@/components/pages/PlayFriendsPage';

export const metadata: Metadata = {
  title: 'Join a Chess Room — Multiplayer Chess Online',
  description:
    'Join a private multiplayer chess room using your invite code and start playing in real time instantly.',
  robots: { index: false, follow: true },
};

export default async function Page({
  params,
}: {
  params: Promise<{ roomCode: string }>;
}) {
  const { roomCode } = await params;
  return <PlayFriendsPage roomCodeFromUrl={roomCode} />;
}
