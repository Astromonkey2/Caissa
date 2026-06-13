import React, { useState, useCallback, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import ChessBoard from '../components/ChessBoard';
import { API } from '../lib/api';
import './Report.css';

const CHESS_FACTS = [
  "Magnus Carlsen became a grandmaster at age 13.",
  "The number of possible chess games exceeds atoms in the observable universe.",
  "Stockfish evaluates ~70 million positions per second.",
  "'Checkmate' comes from Persian: 'Shah Mat' — the king is dead.",
  "The first chess program was written in 1951 by Alan Turing.",
  "A knight can reach any square on the board in at most 6 moves.",
  "Chess has been played for over 1,500 years.",
  "Bobby Fischer learned chess from a booklet at age 6.",
];

const TACTIC_COLORS = {
  hanging_piece:      '#c85050',
  missed_fork:        '#c8a96e',
  pin_ignored:        '#5080c8',
  back_rank:          '#9bc700',
  missed_skewer:      '#c850c8',
  positional_blunder: '#888888',
};

const TACTIC_ICONS = {
  hanging_piece:      '⚠',
  missed_fork:        '⑂',
  pin_ignored:        '📌',
  back_rank:          '🏰',
  missed_skewer:      '⟋',
  positional_blunder: '?',
};

// maps our tactic types to Lichess puzzle trainer theme slugs
const LICHESS_THEMES = {
  hanging_piece:      'hangingPiece',
  missed_fork:        'fork',
  pin_ignored:        'pin',
  back_rank:          'backRankMate',
  missed_skewer:      'skewer',
  positional_blunder: 'middlegame',
};

// ── HELPERS ───────────────────────────────────────────────
function parseResources(text) {
  if (!text) return [];
  const resources = [];
  const sections  = text.split(/###\s+\d+\./).filter(Boolean);
  sections.forEach(section => {
    const titleMatch = section.match(/\*\*Title:\*\*\s*(.+)/);
    const urlMatch   = section.match(/\*\*URL:\*\*\s*(https?:\/\/[^\s*\n]+)/);
    const relMatch   = section.match(/\*\*Relevance:\*\*\s*([\s\S]+?)(?=\n\n|\n###|$)/);
    if (urlMatch) {
      const url       = urlMatch[1].trim().replace(/\.$/, '');
      const isYouTube = url.includes('youtube.com') || url.includes('youtu.be');
      const isLichess = url.includes('lichess.org');
      let videoId = null;
      if (isYouTube) {
        const m = url.match(/(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
        if (m) videoId = m[1];
      }
      resources.push({
        title:     titleMatch ? titleMatch[1].trim() : 'Resource',
        url,
        relevance: relMatch ? relMatch[1].trim().replace(/\n/g, ' ') : '',
        type:      isYouTube ? 'youtube' : isLichess ? 'lichess' : 'web',
        videoId,
      });
    }
  });
  return resources;
}

function parseCoaching(coachingStr, patterns) {
  if (!patterns || patterns.length === 0) return [];
  if (coachingStr) {
    try {
      const clean = coachingStr.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
      const data  = JSON.parse(clean);
      if (data.coaching && data.coaching.length > 0) return data.coaching;
    } catch { /* fall through */ }
  }
  return patterns.map(p => ({
    tactic_type: p.tactic_type,
    paragraph:   `This ${p.tactic_label} pattern occurred ${p.frequency} times in your recent games, averaging ${Math.round((p.avg_cp_loss || 0) / 100 * 10) / 10} pawns lost. ${p.tactic_detail}.`,
    checklist: [
      "Before every move, ask: does my move leave any piece undefended or newly attacked?",
      "After picking a candidate move, visualize your opponent's best reply before committing.",
    ],
  }));
}

function parseDiagnosis(report) {
  let stats = null;
  try { stats = JSON.parse(report.recommendations || '{}'); } catch { /* ignore */ }
  if (!report.resources) return { diagnosis: null, stats };
  const text    = report.resources;
  const cutIdx  = text.search(/###\s+1\./);
  const diagnosis = cutIdx > 0 ? text.slice(0, cutIdx).trim() : null;
  return { diagnosis, stats };
}

// ── PATTERN CARD ──────────────────────────────────────────
function PatternCard({ pattern, coaching }) {
  const accentColor  = TACTIC_COLORS[pattern.tactic_type] || '#888888';
  const icon         = TACTIC_ICONS[pattern.tactic_type]  || '?';
  const avgLoss      = Math.round((pattern.avg_cp_loss || 0) / 100 * 10) / 10;
  const severityPct  = Math.min(Math.round((pattern.avg_cp_loss || 0) / 10), 100);
  const severityColor = severityPct > 60 ? '#c85050' : severityPct > 30 ? '#c8a96e' : '#9bc700';

  return (
    <div className="pattern-card">

      <div className="pattern-header">
        <div className="pattern-icon" style={{ color: accentColor }}>{icon}</div>
        <div className="pattern-info">
          <div className="pattern-phase" style={{ color: accentColor }}>
            {pattern.phase} · {pattern.frequency}× in recent games
          </div>
          <h3 className="pattern-name">{pattern.tactic_label}</h3>
          <p className="pattern-detail">{pattern.tactic_detail}</p>
        </div>
        <div className="pattern-stat">
          <span className="pstat-num" style={{ color: accentColor }}>{avgLoss}</span>
          <span className="pstat-label">avg pawns lost</span>
        </div>
      </div>

      <div className="severity-row">
        <span className="severity-label">Severity</span>
        <div className="severity-track">
          <div className="severity-fill" style={{ width: `${severityPct}%`, background: severityColor }} />
        </div>
        <span className="severity-val" style={{ color: severityColor }}>{avgLoss} pawns avg</span>
      </div>

      {pattern.example?.fen && (
        <div className="pattern-board-row">
          <ChessBoard
            fen={pattern.example.fen}
            movePlayed={pattern.example.move_played}
            bestMove={pattern.example.best_move}
            orientation={pattern.example.user_color === 'black' ? 'black' : 'white'}
          />
          <div className="board-caption">
            <div className="bc-title">
              Worst example
              {pattern.example.move_number ? ` — move ${pattern.example.move_number}` : ''}
              {pattern.example.opening ? ` · ${pattern.example.opening}` : ''}
            </div>
            <div className="bc-line">
              <span className="bc-dot bc-red" />
              You played <strong>{pattern.example.move_played}</strong>
              {pattern.example.cp_loss ? ` (−${Math.round(pattern.example.cp_loss)} centipawns)` : ''}
            </div>
            {pattern.example.best_move && (
              <div className="bc-line">
                <span className="bc-dot bc-green" />
                Engine preferred <strong>{pattern.example.best_move}</strong>
              </div>
            )}
            {pattern.example.date && <div className="bc-date">{pattern.example.date}</div>}
          </div>
        </div>
      )}

      {pattern.all_openings?.length > 0 && (
        <div className="pattern-openings-row">
          <span className="po-label">Occurs in:</span>
          <div className="po-tags">
            {pattern.all_openings.map((o, i) => (
              <span key={i} className="po-tag">{o}</span>
            ))}
          </div>
        </div>
      )}

      {coaching && (
        <div className="coaching-block">
          <div className="coaching-label">♟ Coach says</div>
          <p className="coaching-text">{coaching.paragraph}</p>
          {coaching.checklist?.length > 0 && (
            <div className="checklist">
              {coaching.checklist.map((step, i) => (
                <div key={i} className="checklist-item">
                  <span className="check-num">{i + 1}</span>
                  <span>{step}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <a
        href={`https://lichess.org/training/${LICHESS_THEMES[pattern.tactic_type] || 'middlegame'}`}
        target="_blank"
        rel="noopener noreferrer"
        className="practice-link"
      >
        Practice {pattern.tactic_label} puzzles on Lichess →
      </a>
    </div>
  );
}

// ── OPENING REPERTOIRE ────────────────────────────────────
function OpeningRepertoire({ openings }) {
  if (!openings || openings.length === 0) return null;

  return (
    <div className="repertoire-table">
      <div className="rep-header-row">
        <span className="rep-col-name">Opening</span>
        <span className="rep-col-bar">W / D / L</span>
        <span className="rep-col-counts"></span>
        <span className="rep-col-tag">Action</span>
      </div>
      {openings.map((o, i) => {
        const wr  = Math.round((o.win_rate  || 0) * 100);
        const dr  = Math.round((o.draw_rate || 0) * 100);
        const lr  = Math.max(0, 100 - wr - dr);
        const wins   = o.wins   ?? Math.round((o.win_rate  || 0) * o.games);
        const draws  = o.draws  ?? Math.round((o.draw_rate || 0) * o.games);
        const losses = o.losses ?? (o.games - wins - draws);

        const tag      = wr > 55 ? 'keep' : wr < 35 ? 'drop' : 'study';
        const tagLabel = { keep: 'Study deeper', drop: 'Consider dropping', study: 'Needs work' }[tag];
        const tagColor = { keep: '#9bc700',      drop: '#c85050',           study: '#c8a96e'    }[tag];

        return (
          <div key={i} className="rep-row">
            <div className="rep-name">{o.name}</div>
            <div className="rep-bar-area">
              <div className="rep-wdl-track">
                <div className="rep-wdl-win"   style={{ width: `${wr}%` }} title={`${wr}% wins`} />
                <div className="rep-wdl-draw"  style={{ width: `${dr}%` }} title={`${dr}% draws`} />
                <div className="rep-wdl-loss"  style={{ width: `${lr}%` }} title={`${lr}% losses`} />
              </div>
              <span className="rep-wdl-label">
                <span className="wdl-w">{wins}W</span>
                <span className="wdl-sep"> / </span>
                <span className="wdl-d">{draws}D</span>
                <span className="wdl-sep"> / </span>
                <span className="wdl-l">{losses}L</span>
              </span>
            </div>
            <span className="rep-games">{o.games}g</span>
            <span className="rep-tag" style={{ color: tagColor, borderColor: tagColor }}>
              {tagLabel}
            </span>
          </div>
        );
      })}
      <p className="rep-legend">
        <span style={{ color: '#9bc700' }}>■</span> Keep (&gt;55% wins)&nbsp;&nbsp;
        <span style={{ color: '#c8a96e' }}>■</span> Needs work (35–55%)&nbsp;&nbsp;
        <span style={{ color: '#c85050' }}>■</span> Consider dropping (&lt;35%)
      </p>
    </div>
  );
}

// ── OPENING THEORY DEVIATIONS ─────────────────────────────
function OpeningDeviations({ username }) {
  const [state, setState] = useState('idle'); // idle | loading | done | error
  const [devs,  setDevs]  = useState([]);

  const run = async () => {
    setState('loading');
    try {
      const res = await axios.get(`${API}/api/openings/${username}`, { timeout: 300000 });
      setDevs(res.data.deviations || []);
      setState('done');
    } catch {
      setState('error');
    }
  };

  if (state === 'idle') {
    return (
      <div className="dev-idle">
        <p>
          Compare the first moves of your recent games against the Lichess
          database to find the exact move where you leave known theory.
        </p>
        <button className="analyze-btn" onClick={run}>
          ♘ Check my openings against theory
        </button>
      </div>
    );
  }

  if (state === 'loading') {
    return (
      <p className="dev-loading">
        ⟳ Querying the Lichess opening explorer for your last 10 games —
        this takes a minute or two. Leave this page open.
      </p>
    );
  }

  if (state === 'error') {
    return <p className="no-data">Could not reach the opening explorer. Try again in a moment.</p>;
  }

  if (devs.length === 0) {
    return <p className="no-data">No deviations found — your recent openings all follow known theory.</p>;
  }

  return (
    <div className="dev-list">
      {devs.map((d, i) => (
        <div key={i} className="dev-card">
          <div className="dev-head">
            <span className="dev-opening">{d.opening}{d.eco ? ` (${d.eco})` : ''}</span>
            <span className="dev-freq">{d.frequency}× · avg move {d.avg_move_num}</span>
          </div>
          <p className="dev-detail">
            {d.example.type === 'out_of_book' ? (
              <>On move {d.example.move_number} you played{' '}
                <strong>{d.example.user_move_san}</strong> — a position with no
                recorded games. You're improvising from there.</>
            ) : (
              <>On move {d.example.move_number} you played{' '}
                <strong>{d.example.user_move_san}</strong>; theory prefers{' '}
                <strong>{d.example.theory_san}</strong>
                {d.example.theory_games ? ` (${d.example.theory_games.toLocaleString()} games)` : ''}.</>
            )}
            {d.blunder_count > 0 && (
              <span className="dev-blunder">
                {' '}{d.blunder_count} of these games included a blunder soon after.
              </span>
            )}
          </p>
        </div>
      ))}
    </div>
  );
}

// ── STUDY PLAN ────────────────────────────────────────────
function StudyPlan({ patterns, stats, report }) {
  const phase       = report.weakness_phase || 'middlegame';
  const blunderPct  = Math.round((report.blunder_rate || 0) * 100);
  const topPattern  = patterns?.[0];
  const dailyMins   = blunderPct > 20 ? 30 : blunderPct > 12 ? 20 : 15;
  const targetPct   = Math.max(blunderPct - 6, 5);
  const worstOp     = stats?.worst_opening;
  const worstOpWr   = stats?.worst_opening_wr;
  const bestOp      = stats?.best_opening;

  const items = [
    {
      n:        '01',
      cadence:  'Daily',
      color:    '#c85050',
      action:   `${dailyMins} min of ${phase} tactics puzzles`,
      detail:   topPattern
        ? `Focus specifically on "${topPattern.tactic_label}" patterns — this is your most frequent mistake (${topPattern.frequency}× in recent games).`
        : `Use Lichess puzzles filtered to the ${phase} phase.`,
    },
    {
      n:        '02',
      cadence:  'Weekly',
      color:    '#c8a96e',
      action:   `Analyse 2 of your own games from the ${phase}`,
      detail:   `Pause at every position where you lost more than 1 pawn of eval. Ask: what was the hanging piece or tactic I missed? Write down the pattern.`,
    },
    {
      n:        '03',
      cadence:  'Goal',
      color:    '#9bc700',
      action:   `Reduce ${phase} blunder rate from ${blunderPct}% → ${targetPct}%`,
      detail:   `Reference players at your level who improved most over 3 months had a ${phase} blunder rate under 10%. You're at ${blunderPct}%.`,
    },
    ...(worstOp && (worstOpWr || 0) < 0.35 ? [{
      n:        '04',
      cadence:  'Opening',
      color:    '#888888',
      action:   `Replace or study the ${worstOp}`,
      detail:   `${Math.round((worstOpWr || 0) * 100)}% win rate — below the drop threshold. Either study the critical lines or swap to ${bestOp || 'an opening with a stronger record'}.`,
    }] : []),
    ...(topPattern ? [{
      n:        String(worstOp && (worstOpWr || 0) < 0.35 ? '05' : '04'),
      cadence:  'Mindset',
      color:    '#5080c8',
      action:   `Add a blunder-check habit before every move`,
      detail:   `"STOP — before I play this, is any of my pieces left hanging or newly attacked?" ${topPattern.frequency} of your recent blunders were ${topPattern.tactic_label.toLowerCase()} — a half-second check eliminates most of them.`,
    }] : []),
  ];

  return (
    <div className="study-plan">
      {items.map((item, i) => (
        <div key={i} className="study-item">
          <div className="study-num" style={{ background: item.color }}>{item.n}</div>
          <div className="study-body">
            <div className="study-cadence">{item.cadence}</div>
            <div className="study-action">{item.action}</div>
            <p className="study-detail">{item.detail}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── RESOURCE CARD ─────────────────────────────────────────
function ResourceCard({ resource }) {
  const typeColor = { youtube: '#ff4444', lichess: '#9bc700', web: '#c8a96e' }[resource.type];
  const typeLabel = { youtube: '▶ YouTube', lichess: '♟ Lichess', web: '⬡ Article' }[resource.type];
  return (
    <a href={resource.url} target="_blank" rel="noopener noreferrer" className="r-card">
      {resource.videoId ? (
        <div className="r-thumb">
          <img
            src={`https://img.youtube.com/vi/${resource.videoId}/mqdefault.jpg`}
            alt={resource.title}
            onError={e => { e.target.style.display = 'none'; }}
          />
          <div className="r-play">▶</div>
        </div>
      ) : (
        <div className="r-thumb r-thumb-icon">
          <span>{resource.type === 'lichess' ? '♟' : '⬡'}</span>
        </div>
      )}
      <div className="r-body">
        <div className="r-type" style={{ color: typeColor }}>{typeLabel}</div>
        <div className="r-title">{resource.title}</div>
        <div className="r-url">{resource.url.replace('https://', '').replace('http://', '')}</div>
        {resource.relevance && <div className="r-relevance">{resource.relevance}</div>}
      </div>
      <div className="r-arrow">→</div>
    </a>
  );
}

// ── LOADING ───────────────────────────────────────────────
function ReportLoading({ username, generating }) {
  const [factIdx,  setFactIdx]  = useState(0);
  const [progress, setProgress] = useState(5);
  useEffect(() => {
    const fi = setInterval(() => setFactIdx(i => (i + 1) % CHESS_FACTS.length), 4000);
    const pi = setInterval(() => setProgress(p => Math.min(p + 1.5, 90)), 3000);
    return () => { clearInterval(fi); clearInterval(pi); };
  }, []);
  return (
    <div className="report-loading chess-bg">
      <div className="rl-content">
        <div className="rl-king">♚</div>
        <h2 className="rl-username">{username}</h2>
        <p className="rl-status">
          {generating ? '3 AI agents are analyzing your games...' : 'Loading your report...'}
        </p>
        <div className="rl-progress"><div className="rl-fill" style={{ width: `${progress}%` }} /></div>
        <div className="fact-card">
          <span className="fact-label">did you know</span>
          <p className="fact-text">{CHESS_FACTS[factIdx]}</p>
        </div>
        {generating && (
          <div className="rl-steps">
            {['Agent 1: Diagnosing your weakness pattern...', 'Agent 2: Writing personalized coaching...', 'Agent 3: Searching YouTube & Lichess...'].map((s, i) => (
              <div key={i} className="rl-step"><span className="rl-dot">·</span>{s}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── MAIN REPORT ───────────────────────────────────────────
export default function Report() {
  const { username } = useParams();
  const navigate     = useNavigate();

  const [report,     setReport]     = useState(null);
  const [loading,    setLoading]    = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error,      setError]      = useState('');

  const loadData = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/report/${username}`, { timeout: 15000 });
      setReport(res.data);
      setLoading(false);
    } catch {
      setLoading(false);
      setError('No report found. Generate one from the dashboard.');
    }
  }, [username]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleRegenerate = async () => {
    setGenerating(true);
    setLoading(true);
    try {
      await axios.post(`${API}/api/generate-report/${username}`, null, { timeout: 15000 });
      const interval = setInterval(async () => {
        try {
          const status = await axios.get(`${API}/api/status/${username}`, { timeout: 15000 });
          if (status.data.status === 'ready') {
            clearInterval(interval);
            await loadData();
            setGenerating(false);
          }
        } catch { /* keep polling */ }
      }, 5000);
      setTimeout(() => { clearInterval(interval); setGenerating(false); setLoading(false); }, 600000);
    } catch {
      setGenerating(false);
      setLoading(false);
    }
  };

  const handleDownloadPDF = () => {
    window.print();
  };

  if (loading || generating) return <ReportLoading username={username} generating={generating} />;

  if (error || !report) {
    return (
      <div className="report-error chess-bg">
        <div className="re-content">
          <span className="re-king">♚</span>
          <p>{error || 'No report found.'}</p>
          <button className="analyze-btn" onClick={() => navigate(`/dashboard/${username}`)}>← Back to Dashboard</button>
        </div>
      </div>
    );
  }

  const patterns           = report.patterns_parsed || [];
  const resources          = parseResources(report.resources);
  const coaching           = parseCoaching(report.coaching, patterns);
  const coachMap           = {};
  coaching.forEach(c => { coachMap[c.tactic_type] = c; });
  const { diagnosis, stats } = parseDiagnosis(report);
  const openings           = stats?.top_openings || [];

  return (
    <div className="report-page chess-bg">

      <header className="rp-header">
        <button className="rp-back" onClick={() => navigate(`/dashboard/${username}`)}>← Dashboard</button>
        <div className="rp-logo"><span className="rp-king">♚</span><span className="rp-title">CAISSA</span></div>
        <div className="rp-actions">
          <span className="rp-user">{username}</span>
          <button className="regen-btn" onClick={handleRegenerate} disabled={generating}>↺ Regenerate</button>
          <button className="dl-btn" onClick={handleDownloadPDF}>↓ PDF</button>
        </div>
      </header>

      <main className="rp-main">

        {/* ── 01 DIAGNOSIS ── */}
        <section className="rp-section">
          <div className="section-label">01 — diagnosis</div>
          <h1 className="rp-headline">
            Your critical weakness is <span className="rp-weakness">{report.weakness_phase}</span>
          </h1>
          <div className="rp-stats-row">
            {[
              { val: `${Math.round(report.blunder_rate * 100)}%`, label: 'your blunder rate'  },
              { val: '~9%',                                        label: 'reference avg'      },
              { val: stats?.total_games     || '—',               label: 'games analyzed'     },
              { val: stats?.chesscom_rating || '—',               label: 'current rating'     },
              { val: stats?.trend           || '—',               label: 'trajectory'         },
            ].map((s, i) => (
              <div key={i} className="rp-stat">
                <span className="rp-stat-val">{s.val}</span>
                <span className="rp-stat-label">{s.label}</span>
              </div>
            ))}
          </div>
          {diagnosis && (
            <div className="rp-analysis-box">
              <p className="analysis-raw">{diagnosis}</p>
            </div>
          )}
        </section>

        <div className="rp-divider" />

        {/* ── 02 TACTICAL PATTERNS ── */}
        <section className="rp-section">
          <div className="section-label">02 — recurring mistakes</div>
          <h2 className="rp-section-title">What your games reveal</h2>
          <p className="rp-section-sub">
            Tactical patterns extracted by replaying your recent games with python-chess.
            Each card shows what kind of mistake you keep making, how severe it is, and exactly what to do about it.
          </p>
          {patterns.length > 0 ? (
            <div className="patterns-list">
              {patterns.map((p, i) => (
                <PatternCard key={i} pattern={p} coaching={coachMap[p.tactic_type]} />
              ))}
            </div>
          ) : (
            <div className="no-patterns">
              <p>No patterns extracted yet. Click Regenerate to run pattern analysis.</p>
            </div>
          )}
        </section>

        <div className="rp-divider" />

        {/* ── 03 OPENING REPERTOIRE ── */}
        <section className="rp-section">
          <div className="section-label">03 — opening repertoire</div>
          <h2 className="rp-section-title">What to keep, study, and drop</h2>
          <p className="rp-section-sub">
            Win rate by opening across your last {stats?.games_analyzed || 150} games.
            Threshold: keep anything above 55%, drop anything under 35%, study the rest.
          </p>
          {openings.length > 0 ? (
            <OpeningRepertoire openings={openings} />
          ) : (
            <div className="no-patterns"><p>Opening data not available — regenerate the report.</p></div>
          )}
        </section>

        <div className="rp-divider" />

        {/* ── 04 OPENING THEORY ── */}
        <section className="rp-section">
          <div className="section-label">04 — theory check</div>
          <h2 className="rp-section-title">Where you leave the book</h2>
          <p className="rp-section-sub">
            Your moves compared against millions of Lichess games — the exact move
            where each of your openings goes off known theory.
          </p>
          <OpeningDeviations username={username} />
        </section>

        <div className="rp-divider" />

        {/* ── 05 STUDY PLAN ── */}
        <section className="rp-section">
          <div className="section-label">05 — study plan</div>
          <h2 className="rp-section-title">What to do next, in order</h2>
          <p className="rp-section-sub">
            Prioritized based on your actual data — what will move the needle fastest at your rating.
          </p>
          <StudyPlan patterns={patterns} stats={stats} report={report} />
        </section>

        <div className="rp-divider" />

        {/* ── 06 STUDY RESOURCES ── */}
        <section className="rp-section">
          <div className="section-label">06 — study resources</div>
          <h2 className="rp-section-title">Specific resources to use</h2>
          <p className="rp-section-sub">
            Found by AI agents searching YouTube, Lichess, and chess articles — each matched to your specific weakness.
          </p>
          {resources.length > 0 ? (
            <div className="resources-list">
              {resources.map((r, i) => <ResourceCard key={i} resource={r} />)}
            </div>
          ) : (
            <p className="no-data">No resources yet — regenerate the report.</p>
          )}
        </section>

        <div className="rp-footer">
          <span>♚ CAISSA — Chess Improvement Intelligence</span>
          <span>Generated {new Date(report.created_at).toLocaleDateString()}</span>
          <button className="regen-btn" onClick={handleRegenerate}>↺ Regenerate</button>
        </div>

      </main>
    </div>
  );
}
