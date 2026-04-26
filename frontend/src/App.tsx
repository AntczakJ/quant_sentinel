import { Routes, Route } from 'react-router-dom'
import { Shell } from '@/components/Shell'
import Dashboard from '@/pages/Dashboard'
import Trades from '@/pages/Trades'
import Models from '@/pages/Models'
import ChartPage from '@/pages/Chart'
import Settings from '@/pages/Settings'

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/trades" element={<Trades />} />
        <Route path="/models" element={<Models />} />
        <Route path="/chart" element={<ChartPage />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Dashboard />} />
      </Routes>
    </Shell>
  )
}
