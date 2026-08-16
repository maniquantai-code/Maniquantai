import React from 'react';
import { PieceType, PieceColor } from '@/types/chess';

interface PieceProps {
  type: PieceType;
  color: PieceColor;
  className?: string;
}

export const ChessPieceIcon: React.FC<PieceProps> = ({ type, color, className = 'w-full h-full' }) => {
  const isWhite = color === 'w';

  // SVG color palette
  const fill = isWhite ? '#ffffff' : '#1e293b';
  const stroke = isWhite ? '#27272a' : '#09090b';
  const highlight = isWhite ? '#f8fafc' : '#334155';
  const innerDetail = isWhite ? '#09090b' : '#f8fafc';

  switch (type.toLowerCase()) {
    case 'k': // King
      return (
        <svg viewBox="0 0 45 45" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
          <g fillRule="evenodd" clipRule="evenodd">
            {/* Base */}
            <path
              d="M22.5 11.63V6M20 8h5"
              stroke={stroke}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M22.5 25c0 0 4.5-7.5 3-10.5-1.5-3-6-3-6 0-1.5 3 3 10.5 3 10.5"
              fill={fill}
              stroke={stroke}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M11.5 37c5.5 3.5 15.5 3.5 21 0v-7s9-4.5 6-10.5c-4-6.5-13.5-3.5-16 4V23.5c-2.5-7.5-12-10.5-16-4-3 6 6 10.5 6 10.5v7z"
              fill={fill}
              stroke={stroke}
              strokeWidth="1.5"
            />
            <path
              d="M11.5 30c5.5-3 15.5-3 21 0m-21 3.5c5.5-3 15.5-3 21 0m-21 3.5c5.5-3 15.5-3 21 0"
              stroke={stroke}
              strokeWidth="1.5"
            />
            {/* Head cross details */}
            <circle cx="22.5" cy="14" r="1.5" fill={innerDetail} />
          </g>
        </svg>
      );

    case 'q': // Queen
      return (
        <svg viewBox="0 0 45 45" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
          <g fillRule="evenodd" clipRule="evenodd">
            <path
              d="M9 26c8.5-1.5 21-1.5 27 0l2-12-7 11V11l-5.5 13.5-3-15-3 15L14 11v14l-7-11 2 12z"
              fill={fill}
              stroke={stroke}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M9 26c0 2 1.5 2 2.5 4 2.5 4 1 5.5 1 5.5h20s-1.5-1.5 1-5.5c1-2 2.5-2 2.5-4 0-1.5-1.5-2.5-3-2-4.5 1-13 1-17.5 0-1.5-.5-3 .5-3 2z"
              fill={fill}
              stroke={stroke}
              strokeWidth="1.5"
            />
            <path
              d="M11.5 30c3.5-1 18.5-1 22 0m-21.5 3.5c3-1 18-1 21 0m-20.5 3.5c3-1 17-1 20 0"
              stroke={stroke}
              strokeWidth="1.5"
            />
            <circle cx="6" cy="12" r="2" fill={fill} stroke={stroke} strokeWidth="1.5" />
            <circle cx="14" cy="9" r="2" fill={fill} stroke={stroke} strokeWidth="1.5" />
            <circle cx="22.5" cy="8" r="2" fill={fill} stroke={stroke} strokeWidth="1.5" />
            <circle cx="31" cy="9" r="2" fill={fill} stroke={stroke} strokeWidth="1.5" />
            <circle cx="39" cy="12" r="2" fill={fill} stroke={stroke} strokeWidth="1.5" />
          </g>
        </svg>
      );

    case 'r': // Rook
      return (
        <svg viewBox="0 0 45 45" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
          <g fillRule="evenodd" clipRule="evenodd">
            <path
              d="M9 39h27v-3H9v3zm3-3v-4.5h21V36H12zm1.5-4.5l1.5-12.5h15l1.5 12.5H13.5zM11 19h23v-5h-4v2h-4v-2h-3v2h-4v-2h-4v2h-4v-2z"
              fill={fill}
              stroke={stroke}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M12 35.5h21m-20-4h19m-17-12.5h15"
              stroke={stroke}
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </g>
        </svg>
      );

    case 'b': // Bishop
      return (
        <svg viewBox="0 0 45 45" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
          <g fillRule="evenodd" clipRule="evenodd">
            <path
              d="M9 36c3.39-.97 10.11.43 13.5-2 3.39 2.43 10.11 1.03 13.5 2 0 0 1.65.54 3 2-.68.97-1.65.99-3 .5-3.39-.97-10.11.46-13.5-1-3.39 1.46-10.11.03-13.5 1-1.35.49-2.32.47-3-.5 1.35-1.46 3-2 3-2z"
              fill={fill}
              stroke={stroke}
              strokeWidth="1.5"
            />
            <path
              d="M15 32c2.5 2.5 12.5 2.5 15 0 .5-1.5 0-2 0-2 0-2.5-2.5-4-2.5-4 5.5-1.5 6-11.5-5-15.5-11 4-10.5 14-5 15.5 0 0-2.5 1.5-2.5 4 0 0-.5.5 0 2z"
              fill={fill}
              stroke={stroke}
              strokeWidth="1.5"
            />
            <path
              d="M25 8a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z"
              fill={fill}
              stroke={stroke}
              strokeWidth="1.5"
            />
            <path
              d="M17.5 26h10M15 30h15m-7.5-14v5m-3-2.5h6"
              stroke={stroke}
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </g>
        </svg>
      );

    case 'n': // Knight — traced from custom artwork
      return (
        <svg viewBox="0 0 45 45" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
          <g transform="translate(11.22,4) scale(0.041088)">
            <g transform="translate(-9.997777,860.745566) scale(0.1,-0.1)">
              <path
                d="M2715 8603 c-87 -20 -160 -73 -195 -143 -10 -19 -46 -155 -81 -302
-35 -148 -67 -268 -71 -268 -4 0 -90 69 -191 153 -185 155 -222 177 -299 177
-88 0 -188 -81 -226 -183 -21 -55 -22 -74 -22 -410 l0 -352 -61 -150 c-53
-132 -67 -155 -109 -195 -145 -137 -234 -299 -256 -470 -7 -52 -11 -59 -95
-145 -148 -152 -353 -411 -733 -929 -282 -383 -281 -382 -274 -541 7 -161 83
-272 240 -351 167 -84 333 -87 490 -9 l69 35 -8 -38 c-24 -113 12 -214 105
-289 72 -58 139 -77 257 -71 l91 5 -108 -151 c-296 -414 -412 -698 -448 -1092
-23 -252 40 -634 118 -717 l26 -27 -24 -113 c-34 -156 -34 -281 1 -357 28 -60
94 -132 146 -158 l33 -17 -35 -53 c-101 -149 -140 -263 -140 -407 0 -106 1
-112 34 -172 18 -34 42 -70 52 -79 19 -17 19 -18 0 -38 -10 -12 -48 -90 -85
-175 l-66 -153 0 -147 c0 -131 2 -150 18 -164 17 -16 195 -17 2355 -17 l2336
0 15 22 c13 18 16 52 16 163 l0 140 -56 155 c-32 85 -65 164 -76 176 -18 20
-18 21 2 39 11 10 35 48 53 84 73 149 33 365 -108 573 l-35 53 30 15 c51 26
128 109 157 169 47 97 41 193 -24 353 l-52 127 29 72 c39 93 39 91 -26 189
-143 216 -214 430 -214 646 0 52 38 450 85 886 47 436 90 872 96 968 59 962
-270 1827 -886 2323 -274 221 -638 402 -980 487 l-90 22 -50 101 c-99 201
-247 403 -426 583 -138 140 -223 186 -304 167z m-1191 -2079 c9 -8 16 -19 16
-24 0 -11 -29 -40 -40 -40 -11 0 -40 29 -40 40 0 11 29 40 40 40 5 0 16 -7 24
-16z m763 -786 c-7 -144 -18 -179 -36 -117 -7 24 -24 66 -38 94 l-26 49 48 43
c26 24 49 43 52 43 3 0 3 -51 0 -112z"
                fill={fill}
                stroke={stroke}
                strokeWidth="390"
              />
            </g>
          </g>
        </svg>
      );

    case 'p': // Pawn
    default:
      return (
        <svg viewBox="0 0 45 45" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
          <g fillRule="evenodd" clipRule="evenodd">
            <path
              d="M22.5 9c-2.21 0-4 1.79-4 4 0 .89.29 1.71.78 2.38C17.33 16.5 16 18.59 16 21c0 2.03.94 3.84 2.41 5.03-3 1.06-7.41 5.55-7.41 13.47h23c0-7.92-4.41-12.41-7.41-13.47 1.47-1.19 2.41-3 2.41-5.03 0-2.41-1.33-4.5-3.28-5.62.49-.67.78-1.49.78-2.38 0-2.21-1.79-4-4-4z"
              fill={fill}
              stroke={stroke}
              strokeWidth="1.5"
            />
            <path
              d="M14 36c5-2 12-2 17 0m-16 3h15"
              stroke={stroke}
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </g>
        </svg>
      );
  }
};
