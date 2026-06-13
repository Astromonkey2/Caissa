import React from 'react';
import './ChessBoard.css';

const GLYPHS = {
  K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙',
  k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟',
};

function parseFen(fen) {
  const board = {};
  const placement = (fen || '').split(' ')[0];
  const ranks = placement.split('/');
  if (ranks.length !== 8) return board;
  ranks.forEach((rankStr, ri) => {
    const rank = 8 - ri;
    let file = 0;
    for (const ch of rankStr) {
      if (ch >= '1' && ch <= '8') {
        file += parseInt(ch, 10);
      } else {
        board[`${'abcdefgh'[file]}${rank}`] = ch;
        file += 1;
      }
    }
  });
  return board;
}

function uciSquares(uci) {
  if (!uci || uci.length < 4) return [];
  return [uci.slice(0, 2), uci.slice(2, 4)];
}

/**
 * Static chessboard rendered from a FEN string — no dependencies.
 * Red tint = squares of the move that was played, green = engine's move.
 */
export default function ChessBoard({ fen, movePlayed, bestMove, orientation = 'white' }) {
  const pieces = parseFen(fen);
  const played = new Set(uciSquares(movePlayed));
  const best   = new Set(uciSquares(bestMove));

  const files = orientation === 'black' ? [...'hgfedcba'] : [...'abcdefgh'];
  const ranks = orientation === 'black' ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1];

  return (
    <div className="cb-board">
      {ranks.map((rank, ri) =>
        files.map((file, fi) => {
          const sq    = `${file}${rank}`;
          const light = (fi + ri) % 2 === 0;
          const piece = pieces[sq];
          const cls = [
            'cb-sq',
            light ? 'cb-light' : 'cb-dark',
            played.has(sq) ? 'cb-played' : '',
            best.has(sq) ? 'cb-best' : '',
          ].filter(Boolean).join(' ');
          return (
            <div key={sq} className={cls}>
              {piece && (
                <span className={`cb-piece ${piece === piece.toUpperCase() ? 'cb-w' : 'cb-b'}`}>
                  {GLYPHS[piece]}
                </span>
              )}
              {fi === 0 && <span className="cb-rank">{rank}</span>}
              {ri === 7 && <span className="cb-file">{file}</span>}
            </div>
          );
        })
      )}
    </div>
  );
}
