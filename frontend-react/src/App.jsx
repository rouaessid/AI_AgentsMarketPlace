import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/layout/Layout'
import Marketplace from './pages/Marketplace'
import AgentDetail from './pages/AgentDetail'
import SellerDashboard from './pages/SellerDashboard'
import RegisterAgent from './pages/RegisterAgent'
import Home from './pages/Home'
import Solutions from './pages/Solutions'
import TaskOrchestrator from './pages/TaskOrchestrator'
import { useAuth } from './context/AuthContext'

// eslint-disable-next-line react/prop-types
function ProviderRoute({ children }) {
  const { isLoggedIn, openAuthModal } = useAuth()
  if (!isLoggedIn) {
    openAuthModal()
    return <Navigate to="/" replace />
  }
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="marketplace" element={<Marketplace />} />
        <Route path="marketplace/:agentId" element={<AgentDetail />} />
        <Route path="solutions" element={<Solutions />} />
        <Route path="orchestrator" element={<TaskOrchestrator />} />
        <Route path="seller" element={<ProviderRoute><SellerDashboard /></ProviderRoute>} />
        <Route path="seller/register" element={<ProviderRoute><RegisterAgent /></ProviderRoute>} />
      </Route>
    </Routes>
  )
}
