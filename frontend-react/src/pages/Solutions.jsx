import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Sparkles, Search, Layers, Code2, ArrowRight, 
  Cpu, Zap, Shield, ChevronRight, Terminal,
  Lightbulb, Rocket
} from 'lucide-react'

const MOCK_PACK = [
  { id: 'researcher', name: 'Researcher-01', role: 'Data Mining', color: '#6366f1' },
  { id: 'summarizer', name: 'Summarizer-Pro', role: 'Synthesis', color: '#8b5cf6' },
  { id: 'strategy',   name: 'Strategy-Agent', role: 'Decision', color: '#d946ef' },
]

export default function Solutions() {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [showResult, setShowResult] = useState(false)

  const handleSearch = () => {
    if (!query.trim()) return
    setLoading(true)
    setShowResult(false)
    // Simulation purement statique
    setTimeout(() => {
      setLoading(false)
      setShowResult(true)
    }, 2000)
  }

  return (
    <div className="min-h-screen bg-am-bg py-12 px-4 sm:px-6">
      <div className="max-w-5xl mx-auto">
        
        {/* Header Section */}
        <div className="text-center mb-12">
          <motion.div 
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-am-indigo/10 border border-am-indigo/20 text-am-indigo text-sm font-medium mb-4"
          >
            <Sparkles size={14} />
            <span>AI Orchestration Studio</span>
          </motion.div>
          <h1 className="text-4xl font-extrabold text-am-text mb-4">
            Build your <span className="text-gradient-indigo">Agentic Workflow</span>
          </h1>
          <p className="text-am-muted max-w-2xl mx-auto">
            Describe your complex task, and our protocol will recommend the perfect multi-agent pack 
            to solve it automatically.
          </p>
        </div>

        {/* Search Bar */}
        <div className="relative max-w-3xl mx-auto mb-16">
          <div className="card p-2 flex items-center shadow-card-lg border-am-indigo/30 focus-within:border-am-indigo transition-all">
            <Search className="ml-4 text-am-muted" size={20} />
            <input 
              type="text" 
              placeholder="Ex: I want a daily report on top AI startups with a sentiment analysis..."
              className="flex-1 bg-transparent border-none focus:ring-0 text-am-text px-4 py-3 placeholder:text-am-muted/50"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
            <button 
              onClick={handleSearch}
              disabled={loading}
              className="btn-primary rounded-xl px-6 py-2.5 flex items-center gap-2"
            >
              {loading ? (
                <Cpu className="animate-spin" size={18} />
              ) : (
                <><span>Assemble Pack</span> <ArrowRight size={18} /></>
              )}
            </button>
          </div>
        </div>

        <AnimatePresence>
          {loading && (
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center py-12"
            >
              <div className="relative w-24 h-24 mb-6">
                <div className="absolute inset-0 border-4 border-am-indigo/10 rounded-full" />
                <div className="absolute inset-0 border-4 border-am-indigo border-t-transparent rounded-full animate-spin" />
                <div className="absolute inset-0 flex items-center justify-center text-am-indigo">
                  <Layers size={32} />
                </div>
              </div>
              <p className="text-am-text font-medium animate-pulse">Analyzing agent synergies...</p>
            </motion.div>
          )}

          {showResult && !loading && (
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              className="space-y-8"
            >
              {/* Recommendation Title */}
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-lg bg-emerald-100 text-emerald-600 flex items-center justify-center">
                  <Lightbulb size={24} />
                </div>
                <div>
                  <h3 className="text-xl font-bold text-am-text">Optimal Solution Found</h3>
                  <p className="text-sm text-am-muted">We've selected 3 agents for your "{query.length > 30 ? query.slice(0, 30) + '...' : query}" task.</p>
                </div>
              </div>

              {/* Agent Trio Display */}
              <div className="grid md:grid-cols-3 gap-6 relative">
                {/* SVG Connections (Hidden on mobile) */}
                <div className="hidden md:block absolute top-[40%] left-0 right-0 h-0.5 -z-10 bg-gradient-to-r from-transparent via-am-indigo/20 to-transparent" />
                
                {MOCK_PACK.map((agent, i) => (
                  <motion.div 
                    key={agent.id}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.15 }}
                    className="card p-6 border-am-border group hover:border-am-indigo/45 transition-all shadow-sm hover:shadow-md text-center"
                  >
                    <div 
                      className="w-16 h-16 rounded-2xl mx-auto mb-4 flex items-center justify-center text-white"
                      style={{ background: `linear-gradient(135deg, ${agent.color}, ${agent.color}dd)` }}
                    >
                      {i === 0 ? <Search size={24} /> : i === 1 ? <Layers size={24} /> : <Rocket size={24} />}
                    </div>
                    <div className="text-xs font-bold uppercase tracking-wider text-am-muted mb-1">{agent.role}</div>
                    <h4 className="text-lg font-bold text-am-text mb-2">{agent.name}</h4>
                    <div className="flex items-center justify-center gap-1.5 text-xs text-am-emerald bg-emerald-50 px-2 py-1 rounded-full w-fit mx-auto">
                      <Shield size={10} /> Validated
                    </div>
                  </motion.div>
                ))}
              </div>

              {/* Integration Snippet */}
              <div className="card shadow-card-lg overflow-hidden border-slate-800">
                <div className="bg-slate-900 px-5 py-3 border-b border-slate-800 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Terminal size={16} className="text-am-indigo" />
                    <span className="text-xs font-mono text-slate-400">Pack Orchestration Code</span>
                  </div>
                  <div className="flex gap-1.5">
                    <div className="w-2.5 h-2.5 rounded-full bg-rose-500/30" />
                    <div className="w-2.5 h-2.5 rounded-full bg-amber-500/30" />
                    <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/30" />
                  </div>
                </div>
                <div className="p-5 bg-slate-950 font-mono text-xs sm:text-sm leading-relaxed text-slate-300 overflow-x-auto">
                  <pre>
{`// Orchestrate your agentic pack in a single call
const pack = await AgentMarket.getPack(["researcher-01", "summarizer-pro", "strategy-agent"]);

const result = await pack.orchestrate({
  prompt: "${query || "Analytic report task"}",
  mode: "sequential",
  env: { "OPENAI_API_KEY": "sk-..." }
});

console.log(result.workflow_output);`}
                  </pre>
                </div>
              </div>

              <div className="flex justify-center pt-4">
                <button className="btn-primary-outline flex items-center gap-2 group">
                  Download Integration SDK <ChevronRight size={16} className="group-hover:translate-x-1 transition-transform" />
                </button>
              </div>

            </motion.div>
          )}
        </AnimatePresence>

        {/* Empty State / Hints */}
        {!showResult && !loading && (
          <div className="grid sm:grid-cols-3 gap-6 mt-12 opacity-60">
            {[
              { title: 'Market Trends', icon: TrendingUp, desc: 'Analyze crypto or stock trends automatically.' },
              { title: 'Content Factory', icon: Zap, desc: 'Generate multi-format content with fact-checking.' },
              { title: 'Safe Protocols', icon: Shield, desc: 'Agents verified by 3 independent judges.' },
            ].map((hint, i) => (
              <div key={i} className="text-center p-4">
                <hint.icon size={20} className="mx-auto mb-2 text-am-indigo" />
                <div className="text-sm font-bold text-am-text">{hint.title}</div>
                <p className="text-xs text-am-muted mt-1">{hint.desc}</p>
              </div>
            ))}
          </div>
        )}

      </div>
    </div>
  )
}

function TrendingUp(props) {
  return (
    <svg {...props} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
  )
}
