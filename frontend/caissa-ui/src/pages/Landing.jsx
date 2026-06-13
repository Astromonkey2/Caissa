import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import './Landing.css';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default function Landing() {
  const [username, setUsername] = useState('');
  const [platform, setPlatform] = useState('chesscom');
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username.trim()) return;
    setLoading(true);
    setError('');
    try {
      await axios.post(`${API}/api/onboard/${username.trim()}?platform=${platform}`);
      navigate(`/dashboard/${username.trim()}`);
    } catch (err) {
      setError('Could not reach the analysis server. Please try again in a moment.');
      setLoading(false);
    }
  };

  const placeholder = platform === 'lichess' ? 'your lichess username' : 'your username';
  const prefix      = platform === 'lichess' ? 'lichess.org / ' : 'chess.com / ';

  return (
    <div className="landing chess-bg">

      {/* board decoration */}
      <div className="board-deco">
        {Array.from({ length: 64 }).map((_, i) => (
          <div
            key={i}
            className={`cell ${(Math.floor(i / 8) + i) % 2 === 0 ? 'light' : 'dark'}`}
          />
        ))}
      </div>

      <div className="landing-content">

        {/* logo */}
        <div className="logo-area">
          <div className="king-icon">♚</div>
          <h1 className="logo-text">CAISSA</h1>
          <p className="logo-sub">Chess Improvement Intelligence</p>
        </div>

        {/* tagline */}
        <div className="tagline">
          <p>
            Not a coach. Not a bot.<br />
            A system that reads your games,<br />
            finds the pattern costing you rating points,<br />
            and tells you exactly what to study.
          </p>
        </div>

        {/* platform toggle */}
        <div className="platform-toggle">
          <button
            type="button"
            className={`pt-btn ${platform === 'chesscom' ? 'active' : ''}`}
            onClick={() => setPlatform('chesscom')}
          >
            Chess.com
          </button>
          <button
            type="button"
            className={`pt-btn ${platform === 'lichess' ? 'active' : ''}`}
            onClick={() => setPlatform('lichess')}
          >
            Lichess
          </button>
        </div>

        {/* input */}
        <form className="input-area" onSubmit={handleSubmit}>
          <div className="input-wrapper">
            <span className="input-prefix">{prefix}</span>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder={placeholder}
              className="username-input"
              autoFocus
              disabled={loading}
            />
          </div>
          <button
            type="submit"
            className={`analyze-btn ${loading ? 'loading' : ''}`}
            disabled={loading || !username.trim()}
          >
            {loading ? 'Starting analysis...' : 'Analyze my games →'}
          </button>
          {error && <p className="error-msg">{error}</p>}
        </form>

        {/* platform note */}
        <p className="platform-note">
          {platform === 'lichess'
            ? '⚡ Lichess analysis is fast — evals are pre-computed, no Stockfish needed.'
            : '⏱ Chess.com analysis takes 5-15 min depending on game count.'}
        </p>

        {/* stats row */}
        <div className="stats-row">
          <div className="stat">
            <span className="stat-num">150</span>
            <span className="stat-label">recent games</span>
          </div>
          <div className="stat-divider">·</div>
          <div className="stat">
            <span className="stat-num">607</span>
            <span className="stat-label">reference players</span>
          </div>
          <div className="stat-divider">·</div>
          <div className="stat">
            <span className="stat-num">2</span>
            <span className="stat-label">platforms</span>
          </div>
        </div>

        {/* steps */}
        <div className="steps">
          {[
            { n: '01', t: 'Fetch',    d: 'Pull your most recent 150 games' },
            { n: '02', t: 'Analyze',  d: 'Stockfish (Chess.com) or embedded evals (Lichess)' },
            { n: '03', t: 'Compare',  d: 'Collaborative filter against 600+ similar players' },
            { n: '04', t: 'Research', d: 'AI agents find exactly what to study' },
          ].map(s => (
            <div key={s.n} className="step">
              <span className="step-num">{s.n}</span>
              <span className="step-title">{s.t}</span>
              <span className="step-desc">{s.d}</span>
            </div>
          ))}
        </div>

      </div>
    </div>
  );
}
