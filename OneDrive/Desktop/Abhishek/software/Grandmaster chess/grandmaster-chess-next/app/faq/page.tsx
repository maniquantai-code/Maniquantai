import type { Metadata } from 'next';
import { FAQPage } from '@/components/pages/FAQPage';
import { jsonLdGraph, faqSchema, breadcrumbSchema } from '@/lib/json-ld';

export const metadata: Metadata = {
  title: 'FAQ — Online Chess, AI Engine & Multiplayer Questions Answered',
  description:
    'Answers to common questions about playing free online chess: AI difficulty, multiplayer invites, FIDE rule enforcement, PGN export, and mobile support.',
  alternates: { canonical: '/faq' },
};

const faqs = [
  {
    question: 'Is Grandmaster Chess completely free to play?',
    answer:
      'Yes, 100% free. You can play against AI bots across three difficulties, create multiplayer rooms to play with friends, analyze moves with PGN export, and study openings without paying or creating an account.',
  },
  {
    question: 'How do I invite a friend to play chess online?',
    answer:
      'Go to the Play Friend tab, select your preferred time control and color, and create a private game. You will get a shareable invite link and a 6-character room code that connects the game automatically.',
  },
  {
    question: 'How does the AI chess engine work?',
    answer:
      'The AI engine uses Minimax with Alpha-Beta pruning and Quiescence search. Basic AI plays intuitive beginner moves, Intermediate AI uses positional piece-square evaluations, and Advanced AI calculates deep multi-ply variations to avoid the horizon effect.',
  },
  {
    question: 'Are all standard FIDE chess rules enforced?',
    answer:
      'Yes. The platform validates en passant, castling, pawn promotion, threefold repetition, stalemate, the 50-move rule, and insufficient material draws.',
  },
  {
    question: 'Can I export my games to PGN format?',
    answer:
      'Yes. You can copy or download PGN notation from the move history panel and import it into Chess.com, Lichess, or ChessBase for analysis.',
  },
  {
    question: 'Does it work smoothly on mobile phones and tablets?',
    answer:
      'Yes, the board is fully responsive and touch-friendly across iOS, Android, and desktop browsers.',
  },
];

export default function Page() {
  const graph = jsonLdGraph(
    faqSchema(faqs),
    breadcrumbSchema([
      { name: 'Home', path: '/' },
      { name: 'FAQ', path: '/faq' },
    ])
  );
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(graph) }}
      />
      <FAQPage />
    </>
  );
}
