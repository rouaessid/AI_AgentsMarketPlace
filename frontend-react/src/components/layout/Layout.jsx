import { Outlet } from 'react-router-dom'
import Navbar from './Navbar'
import AuthModal from '../auth/AuthModal'

export default function Layout() {
  return (
    <div className="min-h-screen bg-am-bg">
      <Navbar />
      <AuthModal />
      <main className="pt-16">
        <Outlet />
      </main>
    </div>
  )
}
