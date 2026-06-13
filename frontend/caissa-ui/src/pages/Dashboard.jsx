import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts';
import { API } from '../lib/api';
import './Dashboard.css';

const STATUS_MESSAGES = {
  pending:     'Initializing...',
  fetching:    'Fetching your games...',
  analyzing:   'Running analysis on your moves...',
  researching: 'AI agents searching for study resources...',
  ready:       'Analysis complete',
  error:       'Something went wrong. Try refreshing.',
};

const STATUS_PCT = {
  pending: 5, fetching: 20, analyzing: 60, researching: 85, ready: 100, error: 0
};

// ── RESOURCE PARSER ───────────────────────────────────────
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

// ── RESOURCE CARD ─────────────────────────────────────────
function ResourceCard({ resource }) {
  const typeColor = { youtube: '#ff4444', lichess: '#9bc700', web: '#c8a96e' }[resource.type];
  const typeLabel = { youtube: '▶ YouTube', lichess: '♟ Lichess', web: '⬡ Article' }[resource.type];

  return (
    <a href={resource.url} target="_blank" rel="noopener noreferrer" className="resource-card">
      {resource.videoId ? (
        <div className="resource-thumb">
          <img
            src={`https://img.youtube.com/vi/${resource.videoId}/mqdefault.jpg`}
            alt={resource.title}
            onError={e => { e.target.style.display = 'none'; }}
          />
          <div className="play-btn">▶</div>
        </div>
      ) : (
        <div className="resource-thumb resource-thumb-icon">
          <span>{resource.type === 'lichess' ? '♟' : '⬡'}</span>
        </div>
      )}
      <div className="resource-body">
        <div className="resource-type" style={{ color: typeColor }}>{typeLabel}</div>
        <div className="resource-title">{resource.title}</div>
        <div className="resource-url">
          {resource.url.replace('https://', '').replace('http://', '')}
        </div>
        {resource.relevance && (
          <div className="resource-relevance">{resource.relevance}</div>
        )}
      </div>
      <div className="resource-arrow">→</div>
    </a>
  );
}

// ── DASHBOARD ─────────────────────────────────────────────
export default function Dashboard() {
  const { username } = useParams();
  const navigate     = useNavigate();

  const [status,     setStatus]     = useState('pending');
  const [profile,    setProfile]    = useState(null);
  const [report,     setReport]     = useState(null);
  const [error,      setError]      = useState('');
  const [generating, setGenerating] = useState(false);

  // resilient polling — tolerates intermittent failures
  useEffect(() => {
    let interval;
    let failCount = 0;

    const poll = async () => {
      try {
        const res = await axios.get(`${API}/api/status/${username}`, { timeout: 15000 });
        failCount = 0;
        const s   = res.data.status;
        setStatus(s);

        if (s === 'ready') {
          clearInterval(interval);
          fetchProfile();
        } else if (s === 'error') {
          clearInterval(interval);
          setError('Analysis failed. Please try again.');
        }
      } catch {
        failCount++;
        if (failCount >= 10) {
          clearInterval(interval);
          setError('Lost connection to server. Please refresh.');
        }
        // otherwise silently retry
      }
    };

    poll();
    interval = setInterval(poll, 4000);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [username]);

  const fetchProfile = async () => {
    try {
      const profRes = await axios.get(`${API}/api/profile/${username}`, { timeout: 15000 });
      setProfile(profRes.data);
      try {
        const repRes = await axios.get(`${API}/api/report/${username}`, { timeout: 15000 });
        setReport(repRes.data);
      } catch {
        setReport(null);
      }
    } catch {
      setError('Could not load profile data.');
    }
  };

  const handleGenerateReport = async () => {
    setGenerating(true);
    try {
      await axios.post(`${API}/api/generate-report/${username}`, null, { timeout: 15000 });
      const interval = setInterval(async () => {
        try {
          const statusRes = await axios.get(`${API}/api/status/${username}`, { timeout: 15000 });
          if (statusRes.data.status === 'ready') {
            const repRes = await axios.get(`${API}/api/report/${username}`, { timeout: 15000 });
            setReport(repRes.data);
            setGenerating(false);
            clearInterval(interval);
          }
        } catch { /* keep polling */ }
      }, 5000);
      setTimeout(() => { clearInterval(interval); setGenerating(false); }, 600000);
    } catch {
      setGenerating(false);
    }
  };

  const pct = STATUS_PCT[status] || 0;

  // ── LOADING ───────────────────────────────────────────
  if (status !== 'ready') {
    return (
      <div className="dash-loading chess-bg">
        <div className="loading-content">
          <div className="king-spin">♚</div>
          <h2 className="loading-username">{username}</h2>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <p className="loading-msg">{STATUS_MESSAGES[status]}</p>
          {error && <p className="error-msg">{error}</p>}
          <p className="loading-note">
            This can take several minutes for Chess.com users.<br />
            Lichess users are much faster. You can close and come back.
          </p>
          {status === 'analyzing' && profile?.platform === 'lichess' && (
  <div className="lichess-tip">
    <p>
      ⚡ Games with pre-computed evals are instant.<br/>
      Games without analysis need Stockfish — this takes longer.<br/>
      <a 
        href={`https://lichess.org/@/${username}/all`}
        target="_blank" 
        rel="noopener noreferrer"
        style={{color:'var(--accent)'}}
      >
        Analyze your games on Lichess →
      </a>
      {' '}to speed this up next time.
    </p>
  </div>
)}
        </div>
      </div>
    );
  }

  if (!profile) return null;

  const phases   = profile.phase_stats   || {};
  const openings = profile.opening_stats || [];
  const ratings  = profile.rating_history || [];

  const phaseData = Object.entries(phases).map(([phase, data]) => ({
    phase:        phase.charAt(0).toUpperCase() + phase.slice(1),
    blunder_rate: Math.round(data.blunder_rate * 100),
    moves:        data.total_moves,
  }));

  const ratingData = [...ratings].reverse().map((r, i) => ({ game: i + 1, rating: r }));
  const worstPhase = phaseData.reduce(
    (max, p) => p.blunder_rate > max.blunder_rate ? p : max,
    phaseData[0] || { blunder_rate: 0, phase: '—' }
  );

  const winPct   = Math.round((profile.overall_win_rate || 0) * 100);
  const resources = report ? parseResources(report.resources) : [];
  const platform  = profile.platform || 'chesscom';

  return (
    <div className="dashboard chess-bg">

      {/* header */}
      <header className="dash-header">
        <div className="dash-logo" onClick={() => navigate('/')}>
          <span className="dash-king">♚</span>
          <span className="dash-title">CAISSA</span>
        </div>
        <div className="dash-user">
          <span className="dash-username">{username}</span>
          <span className="dash-rating">
            {ratings[0] || '—'} elo
            <span className="dash-platform">
              {platform === 'lichess' ? ' · Lichess' : ' · Chess.com'}
            </span>
          </span>
        </div>
      </header>

      <main className="dash-main">

        {/* top stats */}
        <section className="top-stats">
          {[
            { label: 'Games Analyzed', value: profile.total_games, unit: 'total stored' },
            { label: 'Recent Win Rate', value: `${winPct}%`, unit: 'last 50 games' },
            {
              label:     'Critical Weakness',
              value:     profile.worst_phase || worstPhase.phase,
              unit:      `${worstPhase.blunder_rate}% blunder rate`,
              highlight: true,
            },
            {
              label: 'Best Opening',
              value: openings[0]?.name?.split(' ').slice(0, 2).join(' ') || '—',
              unit:  `${Math.round((openings[0]?.win_rate || 0) * 100)}% win rate`,
            },
          ].map((s, i) => (
            <div key={i} className={`stat-card ${s.highlight ? 'highlight' : ''}`}>
              <span className="sc-label">{s.label}</span>
              <span className="sc-value">{s.value}</span>
              <span className="sc-unit">{s.unit}</span>
            </div>
          ))}
        </section>

        <div className="dash-grid">

          {/* blunder rates */}
          <section className="panel">
            <h3 className="panel-title">Blunder Rate by Phase</h3>
            <div className="panel-body">
              {phaseData.map(p => (
                <div key={p.phase} className="phase-row">
                  <span className="phase-name">{p.phase}</span>
                  <div className="phase-bar-track">
                    <div
                      className="phase-bar-fill"
                      style={{
                        width: `${Math.min(p.blunder_rate, 100)}%`,
                        background: p.blunder_rate > 30
                          ? 'var(--red)'
                          : p.blunder_rate > 15
                            ? 'var(--accent)'
                            : 'var(--green)',
                      }}
                    />
                  </div>
                  <span className="phase-pct">{p.blunder_rate}%</span>
                </div>
              ))}
              <p className="panel-note">
                Reference players at your level average ~9% middlegame blunder rate.
              </p>
            </div>
          </section>

          {/* rating history */}
          <section className="panel">
            <h3 className="panel-title">Rating History</h3>
            <div className="panel-body chart-body">
              {ratingData.length > 1 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={ratingData}>
                    <XAxis dataKey="game" tick={{ fill: 'var(--text2)', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: 'var(--text2)', fontSize: 10 }} axisLine={false} tickLine={false} domain={['auto', 'auto']} />
                    <Tooltip
                      contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 0, fontFamily: 'var(--font-mono)', fontSize: 11 }}
                      labelFormatter={v => `Game ${v}`}
                    />
                    <Line type="monotone" dataKey="rating" stroke="var(--accent)" strokeWidth={1.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <p className="panel-note">Not enough games for trajectory.</p>
              )}
            </div>
          </section>

          {/* opening performance */}
          <section className="panel panel-wide">
            <h3 className="panel-title">Opening Performance</h3>
            <div className="panel-body">
              <table className="opening-table">
                <thead>
                  <tr>
                    <th>Opening</th>
                    <th>Games</th>
                    <th>Win Rate</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {openings.slice(0, 8).map((o, i) => (
                    <tr key={i}>
                      <td className="opening-name">{o.name}</td>
                      <td className="opening-games">{o.games}</td>
                      <td className="opening-wr">{Math.round(o.win_rate * 100)}%</td>
                      <td className="opening-bar-cell">
                        <div className="opening-bar-track">
                          <div
                            className="opening-bar-fill"
                            style={{
                              width: `${Math.round(o.win_rate * 100)}%`,
                              background: o.win_rate > 0.55 ? 'var(--green)' : o.win_rate < 0.35 ? 'var(--red)' : 'var(--accent)',
                            }}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* AI report */}
          <section className="panel panel-wide report-panel">
            <h3 className="panel-title">
              AI Research Report
              <span className="panel-badge">Gemini</span>
              {report && (
                <button
                  className="view-report-btn"
                  onClick={() => navigate(`/report/${username}`)}
                >
                  View Full Report →
                </button>
              )}
            </h3>
            <div className="panel-body report-body">
              {report ? (
                <>
                  <div className="report-meta">
                    <span>Weakness: <strong>{report.weakness_phase}</strong></span>
                    <span>Blunder rate: <strong>{Math.round(report.blunder_rate * 100)}%</strong></span>
                    <span className="report-date">
                      {new Date(report.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  {resources.length > 0 ? (
                    <div className="resources-grid">
                      {resources.map((r, i) => <ResourceCard key={i} resource={r} />)}
                    </div>
                  ) : (
                    <pre className="report-raw">{report.resources}</pre>
                  )}
                  <button
                    className="analyze-btn"
                    onClick={handleGenerateReport}
                    disabled={generating}
                    style={{ marginTop: '1.25rem', width: 'fit-content' }}
                  >
                    {generating ? '⟳ Regenerating...' : '↺ Regenerate Report'}
                  </button>
                </>
              ) : (
                <div className="report-empty">
                  <p>
                    No report yet. Generate one to get personalized study
                    recommendations from AI agents that search YouTube and Lichess.
                  </p>
                  <button className="analyze-btn" onClick={handleGenerateReport} disabled={generating}>
                    {generating ? '⟳ Agents running (~2 min)...' : '✦ Generate AI Report'}
                  </button>
                  {generating && (
                    <p className="generating-note">
                      AI agents are searching YouTube and Lichess for resources
                      matched to your specific weakness profile...
                    </p>
                  )}
                </div>
              )}
            </div>
          </section>

        </div>
      </main>
    </div>
  );
}
