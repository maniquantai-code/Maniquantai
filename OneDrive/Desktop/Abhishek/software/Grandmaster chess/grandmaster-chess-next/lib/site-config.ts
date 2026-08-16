export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://www.grandmasterchess.online';

export const SITE_NAME = 'Grandmaster Chess Online';

export const SITE_TAGLINE = 'Play Free Chess with Friends & AI';

export const SITE_DESCRIPTION =
  'Play free online chess with friends or challenge AI opponents across basic, intermediate and advanced difficulty levels. Real-time multiplayer rooms, chess clocks, move history, and strategy guides.';

export const TWITTER_HANDLE = '@grandmasterchess';

export function absoluteUrl(path: string): string {
  if (path.startsWith('http')) return path;
  return `${SITE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}
