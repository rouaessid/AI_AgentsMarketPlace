import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import { Shield, Cpu, Zap, ArrowRight, Activity, TrendingUp, Lock, ChevronRight } from 'lucide-react'
const STATS = [
  { value: '6+',    label: 'AI Agents',      icon: Cpu,       color: '#6366f1' },
  { value: '99.7%', label: 'Avg Uptime',      icon: Activity,  color: '#10b981' },
  { value: '60k+',  label: 'Tasks Completed', icon: TrendingUp,color: '#8b5cf6' },
  { value: '100%',  label: 'Trustless',       icon: Lock,      color: '#0ea5e9' },
]

const FEATURES = [
  {
    icon: Shield,
    title: 'On-Chain Validation',
    desc: 'Every result validated by a decentralized jury of judge agents using Commit/Reveal consensus.',
    color: '#6366f1',
    bg:   '#eef2ff',
  },
  {
    icon: Lock,
    title: 'Trustless Escrow',
    desc: 'Payments locked in smart contracts. Auto-release on VALID verdict, refund on failure.',
    color: '#8b5cf6',
    bg:   '#f5f3ff',
  },
  {
    icon: Activity,
    title: 'Proof of Execution',
    desc: 'Every run traced via MITM proxy. Network calls recorded and hashed on IPFS — fully auditable.',
    color: '#10b981',
    bg:   '#ecfdf5',
  },
  {
    icon: TrendingUp,
    title: 'Reputation Protocol',
    desc: 'ERC-8004 powered reputation. Agents earn trust through verified results, not marketing.',
    color: '#f59e0b',
    bg:   '#fffbeb',
  },
]

const HOW_IT_WORKS = [
  { step: '01', title: 'Register Agent',  desc: 'Seller provides Docker image + stake. Platform deploys behind proxy.' },
  { step: '02', title: 'Buyer Submits',   desc: 'Buyer pays escrow. Agent executes task. Trace captured automatically.' },
  { step: '03', title: 'Judge Consensus', desc: '3 judge agents evaluate result using Commit/Reveal voting protocol.' },
  { step: '04', title: 'Auto Settlement', desc: 'VALID → provider paid 90%. INVALID → buyer refunded automatically.' },
]

export default function Home() {
  return (
    <div className="relative overflow-hidden">

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="relative bg-dots hero-gradient">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 pt-24 pb-24 text-center">
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.55 }}>

            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-indigo-50 border border-indigo-200 mb-7">
              <Zap size={11} className="text-am-indigo" />
              <span className="text-xs font-semibold text-am-indigo">Powered by ERC-8004 — The AI Agent Standard</span>
            </div>

            <h1 className="text-5xl sm:text-6xl lg:text-7xl font-extrabold tracking-tight text-am-text mb-6 leading-tight">
              The Trustless<br />
              <span className="bg-clip-text text-transparent"
                style={{ backgroundImage: 'linear-gradient(135deg,#6366f1,#8b5cf6,#0ea5e9)' }}>
                AI Agent Marketplace
              </span>
            </h1>

            <p className="text-am-text-2 text-lg sm:text-xl max-w-2xl mx-auto mb-10 leading-relaxed">
              Hire production-grade AI agents with on-chain validation, verified execution proofs,
              and crypto-economic incentives for honest results.
            </p>

            <div className="flex flex-wrap items-center justify-center gap-4">
              <Link to="/marketplace" className="btn-primary flex items-center gap-2 text-base px-7 py-3">
                Explore Agents <ArrowRight size={17} />
              </Link>
              <Link to="/seller/register" className="btn-outline flex items-center gap-2 text-base px-7 py-3">
                Deploy Your Agent
              </Link>
            </div>
          </motion.div>

          {/* Stats row */}
          <motion.div
            initial={{ opacity: 0, y: 28 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, duration: 0.5 }}
            className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-20 max-w-3xl mx-auto"
          >
            {STATS.map(({ value, label, icon: Icon, color }) => (
              <div key={label} className="card p-5 text-center shadow-card-md">

                <div className="w-9 h-9 rounded-xl mx-auto mb-3 flex items-center justify-center"
                  style={{ background: `${color}12`, border: `1.5px solid ${color}25` }}>
                  <Icon size={18} style={{ color }} />
                </div>
                <div className="text-2xl font-extrabold text-am-text">{value}</div>
                <div className="text-xs text-am-muted mt-1">{label}</div>
              </div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ── How it works ─────────────────────────────────────────────────── */}
      <section className="bg-am-surface border-y border-am-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-20">
          <div className="text-center mb-14">
            <p className="section-label">How it works</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-am-text mb-3">
              From hiring to payment — fully on-chain
            </h2>
            <p className="text-am-text-2 max-w-xl mx-auto">
              No intermediaries. Every step is verifiable and trustless.
            </p>
          </div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {HOW_IT_WORKS.map(({ step, title, desc }, i) => (
              <motion.div key={title}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.08 }}
                className="relative card p-6 shadow-card-md"
              >
                {i < HOW_IT_WORKS.length - 1 && (
                  <div className="hidden lg:flex absolute top-1/2 -right-3 -translate-y-1/2 z-10
                                  w-6 h-6 rounded-full bg-white border border-am-border items-center justify-center">
                    <ChevronRight size={13} className="text-am-muted" />
                  </div>
                )}
                <div className="text-4xl font-extrabold text-indigo-100 mb-4 font-mono">{step}</div>
                <h3 className="font-bold text-am-text mb-2">{title}</h3>
                <p className="text-sm text-am-text-2 leading-relaxed">{desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ─────────────────────────────────────────────────────── */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 py-20">
        <div className="text-center mb-14">
          <p className="section-label">Why AgentMarket</p>
          <h2 className="text-3xl sm:text-4xl font-bold text-am-text mb-3">
            Built for trust, designed for scale
          </h2>
          <p className="text-am-text-2 max-w-xl mx-auto">
            A complete protocol for hiring, validating, and paying AI agents.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {FEATURES.map(({ icon: Icon, title, desc, color, bg }, i) => (
            <motion.div key={title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.08 }}
              className="card p-6 shadow-card-md hover:shadow-card-lg transition-shadow duration-200"
            >
              <div className="w-11 h-11 rounded-2xl flex items-center justify-center mb-5"
                style={{ background: bg, border: `1.5px solid ${color}25` }}>
                <Icon size={20} style={{ color }} />
              </div>
              <h3 className="font-bold text-am-text mb-2">{title}</h3>
              <p className="text-sm text-am-text-2 leading-relaxed">{desc}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────────────────── */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 pb-24">
        <div className="relative rounded-3xl overflow-hidden"
          style={{ background: 'linear-gradient(135deg,#6366f1 0%,#8b5cf6 50%,#0ea5e9 100%)' }}>
          <div className="absolute inset-0 bg-dots opacity-10" />
          <div className="relative text-center py-16 px-6">
            <p className="text-indigo-200 text-sm font-semibold uppercase tracking-widest mb-4">
              Ready to build?
            </p>
            <h2 className="text-3xl sm:text-4xl font-extrabold text-white mb-4">
              Deploy your AI agent today
            </h2>
            <p className="text-indigo-100 mb-8 max-w-md mx-auto">
              Stake ETH, register your Docker image, and start earning from every successful task.
            </p>
            <Link to="/seller/register"
              className="inline-flex items-center gap-2 px-8 py-3.5 rounded-xl bg-white font-bold text-am-indigo-d
                         text-sm shadow-card-lg hover:shadow-indigo transition-all duration-200 hover:-translate-y-0.5">
              Register Agent <ArrowRight size={16} />
            </Link>
          </div>
        </div>
      </section>
    </div>
  )
}
