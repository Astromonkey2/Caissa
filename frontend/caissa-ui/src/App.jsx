import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Landing from './pages/Landing';
import Dashboard from './pages/Dashboard';
import Report from './pages/Report';
import './App.css';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/dashboard/:username" element={<Dashboard />} />
        <Route path="/report/:username" element={<Report />} />
      </Routes>
    </Router>
  );
}

export default App;
