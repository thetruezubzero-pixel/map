import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { AgentDetailPage } from '@/pages/AgentDetailPage'
import { AgentsPage } from '@/pages/AgentsPage'
import { HeirloomsPage } from '@/pages/HeirloomsPage'
import { SwarmPage } from '@/pages/SwarmPage'
import { TrainingPage } from '@/pages/TrainingPage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/agents/:id" element={<AgentDetailPage />} />
        <Route path="/swarm" element={<SwarmPage />} />
        <Route path="/training" element={<TrainingPage />} />
        <Route path="/heirlooms" element={<HeirloomsPage />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
