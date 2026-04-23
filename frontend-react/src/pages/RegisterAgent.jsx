import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import {
  ChevronRight, ChevronLeft, Check, Cpu, DollarSign,
  ClipboardList, Copy, LayoutDashboard, ArrowRight, AlertCircle,
  Package, Wallet, Zap, Info, Scale
} from 'lucide-react'
import { agentApi } from '../api/agentApi'
import { useAuth } from '../context/AuthContext'

const STEPS = [
  { id: 1, label: 'Identity',  icon: Cpu          },
  { id: 2, label: 'Technical', icon: Package      },
  { id: 3, label: 'Economics', icon: DollarSign   },
  { id: 4, label: 'Review',    icon: ClipboardList },
]

const INITIAL = {
  agent_id: '', name: '', description: '', agent_type: 'provider', version: '1.0.0',
  docker_image: '', llm_model: 'llama-3.3-70b-versatile', framework: 'raw_api',
  language: 'python', max_tokens: 8192, supported_tasks: '',
  env_var_keys: '', cpu_limit: 1, ram_limit_mb: 512, timeout_sec: 60,
  price_per_task: 0.05, access_duration_days: 30, max_calls_per_day: 100, stake_amount: 0.2,
  readme: '',
}

export default function RegisterAgent() {
  const { walletAddress, openAuthModal } = useAuth()
  const navigate = useNavigate()

  const [step,       setStep]       = useState(1)
  const [form,       setForm]       = useState(INITIAL)
  const [errors,     setErrors]     = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [apiError,   setApiError]   = useState('')
  const [response,   setResponse]   = useState(null)

  const setField = (k, v) => { setForm(f => ({ ...f, [k]: v })); setErrors(e => ({ ...e, [k]: '' })) }
  const setErr   = (k, m) => setErrors(e => ({ ...e, [k]: m }))

  function validateStep(s) {
    let ok = true
    if (s === 1) {
      if (!form.agent_id) { setErr('agent_id', 'Required'); ok = false }
      else if (!/^[a-z0-9][a-z0-9-]*[a-z0-9]$/.test(form.agent_id)) {
        setErr('agent_id', 'Lowercase letters, numbers and hyphens only'); ok = false
      }
      if (!form.name)        { setErr('name', 'Required'); ok = false }
      if (!form.description) { setErr('description', 'Required'); ok = false }
    }
    if (s === 2 && !form.docker_image) { setErr('docker_image', 'Required'); ok = false }
    if (s === 3) {
      if (form.price_per_task < 0) { setErr('price_per_task', 'Must be ≥ 0'); ok = false }
      if (form.stake_amount   < 0) { setErr('stake_amount',   'Must be ≥ 0'); ok = false }
    }
    return ok
  }

  const next = () => { if (validateStep(step)) setStep(s => Math.min(s + 1, 4)) }
  const back = () => setStep(s => Math.max(s - 1, 1))

  async function waitForTxReceipt(txHash, maxRetries = 40) {
    for (let i = 0; i < maxRetries; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const receipt = await window.ethereum.request({
        method: 'eth_getTransactionReceipt',
        params: [txHash],
      })
      if (receipt?.status === '0x1') return receipt
      if (receipt?.status === '0x0') throw new Error('Transaction reverted on-chain (out of gas or contract error)')
    }
    throw new Error('Transaction not confirmed after 80s')
  }

  async function submit() {
    if (!walletAddress) { openAuthModal('login'); return }
    setSubmitting(true); setApiError('')
    try {
      const payload = {
        ...form,
        owner_address:   walletAddress,
        supported_tasks: form.supported_tasks.split(',').map(t => t.trim()).filter(Boolean),
        env_var_keys:    form.env_var_keys.split(',').map(k => k.trim()).filter(Boolean),
        services: [{
          name: 'run',
          endpoint: `/api/v1/agents/${form.agent_id}/run`,
          version: form.version,
          skills: form.supported_tasks.split(',').map(t => t.trim()).filter(Boolean),
        }],
      }

      // Step 1 — IPFS upload + build unsigned tx
      const res = await agentApi.register(payload)

      // Step 2 — MetaMask signs the IdentityRegistry.register() tx
      if (!res.unsigned_tx?.data) throw new Error('Backend did not return unsigned_tx.data')
      if (!window.ethereum) throw new Error('MetaMask not detected')

      // Ensure correct chain (Hardhat 31337)
      try {
        await window.ethereum.request({
          method: 'wallet_switchEthereumChain',
          params: [{ chainId: '0x7A69' }],
        })
      } catch (sw) {
        if (sw.code === 4902) {
          await window.ethereum.request({
            method: 'wallet_addEthereumChain',
            params: [{ chainId: '0x7A69', chainName: 'Hardhat Local',
              rpcUrls: ['http://127.0.0.1:8545'],
              nativeCurrency: { name: 'ETH', symbol: 'ETH', decimals: 18 } }],
          })
        }
      }

      const gasHex = '0x' + res.unsigned_tx.estimated_gas.toString(16)
      const txHash = await window.ethereum.request({
        method: 'eth_sendTransaction',
        params: [{
          from:  walletAddress,
          to:    res.unsigned_tx.contract_address,
          data:  res.unsigned_tx.data,
          gas:   gasHex,
        }],
      })

      // Step 3 — Wait for on-chain confirmation before notifying backend
      await waitForTxReceipt(txHash)

      // Step 4 — Notify backend of confirmed tx
      await agentApi.confirm({ registration_id: res.registration_id, tx_hash: txHash })

      setResponse({ ...res, tx_hash: txHash })
      setStep(5)
    } catch (e) {
      setApiError(e.message || 'Registration failed. Make sure the backend is running.')
    }
    setSubmitting(false)
  }

  if (step === 5 && response) return <SuccessStep response={response} navigate={navigate} isJudge={form.agent_type === 'judge'} />

  return (
    <div className="min-h-screen bg-am-bg">
      <div className="bg-white border-b border-am-border">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8">
          <p className="section-label">Seller</p>
          <h1 className="text-2xl sm:text-3xl font-bold text-am-text">Register Agent</h1>
          <p className="text-am-text-2 mt-1 text-sm">
            Provide your Docker image. The platform handles traces, IPFS, and on-chain interactions.
          </p>
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8">
        {/* Stepper */}
        <div className="flex items-center mb-8">
          {STEPS.map((s, i) => (
            <div key={s.id} className="flex items-center flex-1">
              <div className="flex flex-col items-center">
                <div className={`w-9 h-9 rounded-full flex items-center justify-center font-bold text-sm border-2 transition-all ${
                  step > s.id   ? 'bg-am-indigo border-am-indigo text-white'
                  : step === s.id ? 'bg-white border-am-indigo text-am-indigo'
                  : 'bg-white border-am-border text-am-muted'
                }`}>
                  {step > s.id ? <Check size={14} /> : s.id}
                </div>
                <span className={`text-xs mt-1.5 font-medium hidden sm:block ${step >= s.id ? 'text-am-text' : 'text-am-muted'}`}>
                  {s.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div className={`flex-1 h-0.5 mx-2 transition-colors ${step > s.id ? 'bg-am-indigo' : 'bg-am-border'}`} />
              )}
            </div>
          ))}
        </div>

        <AnimatePresence mode="wait">
          <motion.div key={step}
            initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }} transition={{ duration: 0.18 }}
            className="card p-6 sm:p-8 shadow-card-md"
          >
            {step === 1 && <Step1 form={form} setField={setField} errors={errors} />}
            {step === 2 && <Step2 form={form} setField={setField} errors={errors} />}
            {step === 3 && <Step3 form={form} setField={setField} errors={errors} />}
            {step === 4 && <Step4 form={form} />}

            {apiError && (
              <div className="flex items-start gap-3 mt-4 bg-rose-50 border border-rose-200 rounded-xl p-3 text-sm text-am-rose">
                <AlertCircle size={15} className="mt-0.5 flex-shrink-0" />
                {apiError}
              </div>
            )}

            <div className="flex items-center justify-between mt-8 pt-6 border-t border-am-border">
              <button onClick={back} disabled={step === 1} className="btn-ghost flex items-center gap-2 disabled:opacity-30">
                <ChevronLeft size={15} /> Back
              </button>
              {step < 4 ? (
                <button onClick={next} className="btn-primary flex items-center gap-2">
                  Continue <ChevronRight size={15} />
                </button>
              ) : (
                <button onClick={submit} disabled={submitting} className="btn-primary flex items-center gap-2 disabled:opacity-60">
                  {submitting
                    ? <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" /> Deploying…</>
                    : form.agent_type === 'judge'
                      ? <><Scale size={15} /> Register Judge</>
                      : <><Zap size={15} /> Deploy Agent</>
                  }
                </button>
              )}
            </div>
          </motion.div>
        </AnimatePresence>

        <div className="flex items-start gap-3 mt-4 bg-indigo-50 border border-indigo-200 rounded-xl px-4 py-3 text-sm text-am-indigo-d">
          <Info size={14} className="mt-0.5 flex-shrink-0" />
          The platform automatically captures execution traces via proxy, uploads to IPFS, and manages all on-chain interactions.
        </div>
      </div>
    </div>
  )
}

// ── Step 1: Identity ──────────────────────────────────────────────────────────
function Step1({ form, setField, errors }) {
  return (
    <div className="space-y-5">
      <StepHeader icon={Cpu} title="Agent Identity" desc="Define your agent's unique marketplace identity." />
      <Field label="Agent ID" error={errors.agent_id} hint="Lowercase, hyphens only — e.g. researcher-01">
        <input id="f-agent-id" type="text" value={form.agent_id}
          onChange={e => setField('agent_id', e.target.value)} placeholder="researcher-01" className="input" />
      </Field>
      <Field label="Agent Name" error={errors.name}>
        <input id="f-name" type="text" value={form.name}
          onChange={e => setField('name', e.target.value)} placeholder="ResearchBot" className="input" />
      </Field>
      <Field label="Description" error={errors.description}>
        <textarea id="f-desc" rows={3} value={form.description}
          onChange={e => setField('description', e.target.value)}
          placeholder="What does your agent do?" className="input resize-none" />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Agent Type">
          <select id="f-type" value={form.agent_type} onChange={e => setField('agent_type', e.target.value)} className="input">
            <option value="provider">Provider</option>
            <option value="judge">Judge</option>
          </select>
        </Field>
        <Field label="Version">
          <input id="f-version" type="text" value={form.version}
            onChange={e => setField('version', e.target.value)} placeholder="1.0.0" className="input" />
        </Field>
      </div>
    </div>
  )
}

// ── Step 2: Technical ─────────────────────────────────────────────────────────
function Step2({ form, setField, errors }) {
  return (
    <div className="space-y-5">
      <StepHeader icon={Package} title="Technical Configuration" desc="Docker image and runtime settings." />
      <Field label="Docker Image" error={errors.docker_image} hint="e.g. username/my-agent:v1">
        <input id="f-docker" type="text" value={form.docker_image}
          onChange={e => setField('docker_image', e.target.value)}
          placeholder="username/researcher:v1" className="input font-mono" />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label="LLM Model">
          <select id="f-llm" value={form.llm_model} onChange={e => setField('llm_model', e.target.value)} className="input">
            <option value="llama-3.3-70b-versatile">Llama 3.3 70B</option>
            <option value="claude-3-5-sonnet-20241022">Claude 3.5 Sonnet</option>
            <option value="gpt-4o">GPT-4o</option>
            <option value="gemini-1.5-pro">Gemini 1.5 Pro</option>
          </select>
        </Field>
        <Field label="Framework">
          <select id="f-framework" value={form.framework} onChange={e => setField('framework', e.target.value)} className="input">
            <option value="raw_api">Raw API</option>
            <option value="langchain">LangChain</option>
            <option value="autogen">AutoGen</option>
            <option value="crewai">CrewAI</option>
          </select>
        </Field>
      </div>
      <Field label="Required API Keys">
        <input id="f-env" type="text" value={form.env_var_keys}
          onChange={e => setField('env_var_keys', e.target.value)}
          placeholder="GROQ_API_KEY, TAVILY_API_KEY" className="input font-mono" />
      </Field>
      <Field label="Supported Tasks" hint="Comma-separated — e.g. research, summarization">
        <input id="f-tasks" type="text" value={form.supported_tasks}
          onChange={e => setField('supported_tasks', e.target.value)}
          placeholder="research, summarization, analysis" className="input" />
      </Field>
      <Field label="README (Markdown)">
        <textarea id="f-readme" rows={6} value={form.readme}
          onChange={e => setField('readme', e.target.value)}
          placeholder={`## ${form.name || 'My Agent'}\n\nDescribe how to use your agent, what inputs it expects, and example outputs.`}
          className="input resize-y font-mono text-xs" />
      </Field>
      <div className="grid grid-cols-3 gap-4">
        <Field label="CPU (cores)">
          <input id="f-cpu" type="number" min={1} max={8} value={form.cpu_limit}
            onChange={e => setField('cpu_limit', Number(e.target.value))} className="input" />
        </Field>
        <Field label="RAM (MB)">
          <input id="f-ram" type="number" min={128} max={8192} value={form.ram_limit_mb}
            onChange={e => setField('ram_limit_mb', Number(e.target.value))} className="input" />
        </Field>
        <Field label="Timeout (s)">
          <input id="f-timeout" type="number" min={5} max={600} value={form.timeout_sec}
            onChange={e => setField('timeout_sec', Number(e.target.value))} className="input" />
        </Field>
      </div>
    </div>
  )
}

// ── Step 3: Economics ─────────────────────────────────────────────────────────
function Step3({ form, setField, errors }) {
  const isJudge = form.agent_type === 'judge'
  if (isJudge) return <Step3Judge form={form} setField={setField} errors={errors} />
  return <Step3Provider form={form} setField={setField} errors={errors} />
}

function Step3Provider({ form, setField, errors }) {
  return (
    <div className="space-y-5">
      <StepHeader icon={DollarSign} title="Economics" desc="Pricing and staking parameters." />
      <div className="grid grid-cols-2 gap-4">
        <Field label="Price per Task (ETH)" error={errors.price_per_task} hint="Charged to buyers">
          <input id="f-price" type="number" min={0} step={0.001} value={form.price_per_task}
            onChange={e => setField('price_per_task', Number(e.target.value))} className="input" />
        </Field>
        <Field label="Stake Amount (ETH)" error={errors.stake_amount} hint="Slashable on INVALID verdict">
          <input id="f-stake" type="number" min={0} step={0.01} value={form.stake_amount}
            onChange={e => setField('stake_amount', Number(e.target.value))} className="input" />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Access Duration (days)">
          <input id="f-days" type="number" min={1} value={form.access_duration_days}
            onChange={e => setField('access_duration_days', Number(e.target.value))} className="input" />
        </Field>
        <Field label="Max Calls / Day">
          <input id="f-calls" type="number" min={1} value={form.max_calls_per_day}
            onChange={e => setField('max_calls_per_day', Number(e.target.value))} className="input" />
        </Field>
      </div>
      <div className="bg-indigo-50 border border-indigo-200 rounded-2xl p-4">
        <div className="text-xs font-semibold text-am-indigo uppercase tracking-wider mb-3">Revenue Preview</div>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <div className="text-lg font-bold text-am-text">{form.price_per_task} ETH</div>
            <div className="text-xs text-am-muted">per task</div>
          </div>
          <div>
            <div className="text-lg font-bold text-am-text">
              {(form.price_per_task * 0.9 * form.max_calls_per_day).toFixed(3)} ETH
            </div>
            <div className="text-xs text-am-muted">max daily (90%)</div>
          </div>
          <div>
            <div className="text-lg font-bold text-am-text">{form.stake_amount} ETH</div>
            <div className="text-xs text-am-muted">at stake</div>
          </div>
        </div>
      </div>
    </div>
  )
}

function Step3Judge({ form, setField, errors }) {
  return (
    <div className="space-y-5">
      <StepHeader icon={Scale} title="Judge Economics" desc="Judges earn validation fees from the protocol — not from buyers." />

      {/* Info banner */}
      <div className="flex items-start gap-3 bg-violet-50 border border-violet-200 rounded-2xl px-4 py-3 text-sm text-violet-800">
        <Scale size={15} className="mt-0.5 flex-shrink-0 text-violet-500" />
        <div>
          <span className="font-semibold">Judge agents are not listed on the marketplace.</span>
          {' '}They appear only in your <span className="font-semibold">My Agents</span> list.
          The protocol assigns them automatically when validation is triggered.
        </div>
      </div>

      {/* Stake */}
      <Field label="Stake Amount (ETH)" error={errors.stake_amount}
        hint="Slashable if the judge votes inconsistently with consensus">
        <input id="f-stake" type="number" min={0} step={0.01} value={form.stake_amount}
          onChange={e => setField('stake_amount', Number(e.target.value))} className="input" />
      </Field>

      {/* Summary box */}
      <div className="bg-violet-50 border border-violet-200 rounded-2xl p-4">
        <div className="text-xs font-semibold text-violet-700 uppercase tracking-wider mb-3">Judge Role Summary</div>
        <div className="space-y-2 text-sm text-violet-900">
          {[
            'Receives execution traces from the platform after each task',
            'Evaluates output correctness independently — no platform knowledge needed',
            'Returns a score (0-100) and VALID / INVALID verdict',
            'Participates in commit-reveal voting on-chain',
            'Earns validation fees from the protocol on correct verdicts',
          ].map((line, i) => (
            <div key={i} className="flex items-start gap-2">
              <Check size={13} className="mt-0.5 flex-shrink-0 text-violet-500" />
              <span>{line}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Stake preview */}
      <div className="grid grid-cols-2 gap-4 text-center">
        <div className="bg-am-surface border border-am-border rounded-2xl p-4">
          <div className="text-lg font-bold text-am-text">{form.stake_amount} ETH</div>
          <div className="text-xs text-am-muted mt-1">stake at risk</div>
        </div>
        <div className="bg-am-surface border border-am-border rounded-2xl p-4">
          <div className="text-lg font-bold text-violet-600">Protocol</div>
          <div className="text-xs text-am-muted mt-1">revenue source</div>
        </div>
      </div>
    </div>
  )
}

// ── Step 4: Review ────────────────────────────────────────────────────────────
function Step4({ form }) {
  const rows = [
    { label: 'Agent ID',     value: form.agent_id,        mono: true  },
    { label: 'Name',         value: form.name,             mono: false },
    { label: 'Type',         value: form.agent_type,       mono: false },
    { label: 'Version',      value: form.version,          mono: true  },
    { label: 'Docker Image', value: form.docker_image,     mono: true  },
    { label: 'LLM Model',    value: form.llm_model,        mono: false },
    { label: 'Price',        value: `${form.price_per_task} ETH / task`, mono: false },
    { label: 'Stake',        value: `${form.stake_amount} ETH`,          mono: false },
    { label: 'README',       value: form.readme ? `${form.readme.slice(0, 60)}…` : '—', mono: false },
    { label: 'Tools',        value: form.env_var_keys || '—',            mono: true  },
  ]
  return (
    <div className="space-y-5">
      <StepHeader icon={ClipboardList} title="Review & Deploy" desc="Confirm your configuration before deploying." />
      <div className="divide-y divide-am-border rounded-2xl border border-am-border overflow-hidden">
        {rows.map(({ label, value, mono }) => (
          <div key={label} className="flex items-center justify-between px-4 py-3 bg-white">
            <span className="text-sm text-am-muted w-32 flex-shrink-0">{label}</span>
            <span className={`text-sm text-am-text font-medium text-right truncate max-w-[200px] ${mono ? 'font-mono' : ''}`}>
              {value}
            </span>
          </div>
        ))}
      </div>
      <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-700">
        <Wallet size={14} className="mt-0.5 flex-shrink-0" />
        Your wallet will sign the on-chain registration transaction after submission.
      </div>
    </div>
  )
}

// ── Success ───────────────────────────────────────────────────────────────────
function SuccessStep({ response, navigate, isJudge }) {
  const [copied,      setCopied]      = useState(null)
  const [staking,     setStaking]     = useState(false)
  const [stakeTx,     setStakeTx]     = useState(response.stake_tx_hash || null)
  const [stakeError,  setStakeError]  = useState('')

  function copy(text, key) {
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(null), 1500)
  }

  // stake_amount_eth from backend (what the seller entered in the form)
  const stakeEth      = response.stake_amount_eth || 0
  const stakeContract = response.stake_contract
  const identityDone  = !!response.tx_hash
  const stakeDone     = !!stakeTx
  const fullyLive     = identityDone && stakeDone

  // Call StakingContract.stake() via MetaMask — seller signs with their own wallet
  async function signStake() {
    if (!stakeContract || stakeEth <= 0) return
    if (!window.ethereum) { setStakeError('MetaMask not detected.'); return }
    setStaking(true)
    setStakeError('')
    try {
      // Use already-connected accounts (no popup) — avoids MetaMask showing email accounts
      let accounts = await window.ethereum.request({ method: 'eth_accounts' })
      if (!accounts || accounts.length === 0) {
        // Not connected yet — request connection once
        accounts = await window.ethereum.request({ method: 'eth_requestAccounts' })
      }
      const from = accounts[0]
      if (!from) { setStakeError('No account connected in MetaMask.'); setStaking(false); return }

      // Force Hardhat Local network (chain 31337)
      try {
        await window.ethereum.request({
          method: 'wallet_switchEthereumChain',
          params: [{ chainId: '0x7A69' }], // 31337 in hex
        })
      } catch (switchErr) {
        // Chain not added yet — add it
        if (switchErr.code === 4902) {
          await window.ethereum.request({
            method: 'wallet_addEthereumChain',
            params: [{ chainId: '0x7A69', chainName: 'Hardhat Local',
              rpcUrls: ['http://127.0.0.1:8545'], nativeCurrency: { name: 'ETH', symbol: 'ETH', decimals: 18 } }],
          })
        }
      }

      // Convert ETH → hex wei
      const weiHex = '0x' + BigInt(Math.round(stakeEth * 1e18)).toString(16)

      // stake() selector = 0x3a4b66f1 (no args, just send ETH)
      const txHash = await window.ethereum.request({
        method: 'eth_sendTransaction',
        params: [{
          from,
          to:    stakeContract,
          value: weiHex,
          data:  '0x3a4b66f1',   // keccak256("stake()")[0:4]
          gas:   '0x30D40',      // 200000 — skip eth_estimateGas (localhost issue)
        }],
      })
      setStakeTx(txHash)
    } catch (e) {
      if (e.code !== 4001) setStakeError(e.message || 'Transaction failed')
    }
    setStaking(false)
  }

  const rows = [
    { label: 'Agent ID',    value: response.agent_id,                                                   copyKey: null    },
    { label: 'Token ID',    value: response.token_id != null ? `#${response.token_id}` : null,          copyKey: null    },
    { label: 'IPFS CID',    value: response.ipfs_cid,                                                   copyKey: 'cid'   },
    { label: 'Identity TX', value: response.tx_hash   ? `${response.tx_hash.slice(0,20)}…`   : null,   copyKey: 'tx'    },
    { label: 'Stake TX',    value: stakeTx            ? `${stakeTx.slice(0,20)}…`            : null,   copyKey: 'stake' },
    { label: 'Endpoint',    value: response.platform_endpoint,                                          copyKey: null    },
  ].filter(r => r.value)

  return (
    <div className="min-h-screen bg-am-bg flex items-center justify-center px-4 py-16">
      <motion.div initial={{ opacity: 0, scale: 0.95, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.3 }} className="w-full max-w-lg">
        <div className="card shadow-card-lg overflow-hidden">
          <div className="h-2 w-full" style={{
            background: fullyLive
              ? 'linear-gradient(90deg,#10b981,#6366f1)'
              : 'linear-gradient(90deg,#f59e0b,#6366f1)',
          }} />
          <div className="p-8 text-center">

            {/* Icon */}
            <div className={`w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-5 ${
              fullyLive ? 'bg-emerald-50 border-2 border-emerald-200' : 'bg-amber-50 border-2 border-amber-200'
            }`}>
              <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }}
                transition={{ delay: 0.2, type: 'spring', stiffness: 200 }}>
                <Check size={28} className={fullyLive ? 'text-am-emerald' : 'text-amber-500'} strokeWidth={3} />
              </motion.div>
            </div>

            <h2 className="text-2xl font-bold text-am-text mb-1">
              {isJudge
                ? fullyLive ? 'Judge Fully Active!' : identityDone ? 'Judge Registered!' : 'Judge Submitted!'
                : fullyLive ? 'Agent Fully Live!' : identityDone ? 'Identity Registered!' : 'Registration Submitted!'
              }
            </h2>
            <p className="text-am-text-2 text-sm mb-4">{response.message}</p>
            {isJudge && (
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold mb-2 border"
                style={{ background: '#f5f3ff', borderColor: '#c4b5fd', color: '#6d28d9' }}>
                <Scale size={11} /> Not listed on marketplace · visible in My Agents
              </div>
            )}

            {/* Status badge */}
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold mb-6 border"
              style={fullyLive
                ? { background: '#ecfdf5', borderColor: '#a7f3d0', color: '#065f46' }
                : { background: '#fffbeb', borderColor: '#fcd34d', color: '#92400e' }}>
              <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${fullyLive ? 'bg-emerald-500' : 'bg-amber-400'}`} />
              {fullyLive ? 'Active · Identity + Stake on-chain' : 'Pending · Stake required'}
            </div>

            {/* Data rows */}
            <div className="text-left bg-am-surface rounded-2xl border border-am-border divide-y divide-am-border mb-6 overflow-hidden">
              {rows.map(({ label, value, copyKey }) => (
                <div key={label} className="flex items-center justify-between px-4 py-3">
                  <span className="text-xs text-am-muted w-28 flex-shrink-0">{label}</span>
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-xs font-mono text-am-text font-semibold truncate max-w-[180px]">{value}</span>
                    {copyKey && (
                      <button onClick={() => copy(
                        copyKey === 'cid'   ? response.ipfs_cid :
                        copyKey === 'tx'    ? response.tx_hash :
                        copyKey === 'stake' ? stakeTx : value,
                        copyKey
                      )} className="text-am-muted hover:text-am-indigo flex-shrink-0">
                        {copied === copyKey
                          ? <Check size={11} className="text-am-emerald" />
                          : <Copy size={11} />}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* ── Stake button — shown until seller signs ── */}
            {!stakeDone && stakeContract && stakeEth > 0 && (
              <div className="mb-6 text-left">
                <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4 mb-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Wallet size={14} className="text-amber-600" />
                    <span className="text-sm font-semibold text-amber-800">Stake Required</span>
                  </div>
                  <p className="text-xs text-amber-700 mb-3">
                    Your identity is registered on-chain. You must now stake{' '}
                    <span className="font-bold">{stakeEth} ETH</span> from your own wallet.
                    This ETH is slashable if your agent produces invalid results.
                  </p>
                  {stakeError && (
                    <p className="text-xs text-rose-600 mb-2 flex items-center gap-1">
                      <AlertCircle size={11} /> {stakeError}
                    </p>
                  )}
                  <button onClick={signStake} disabled={staking}
                    className="w-full py-2.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2
                               bg-amber-500 hover:bg-amber-600 text-white transition-colors disabled:opacity-60">
                    {staking
                      ? <><span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Waiting for MetaMask…</>
                      : <><Wallet size={14} /> Sign Stake ({stakeEth} ETH) in MetaMask</>
                    }
                  </button>
                </div>
              </div>
            )}

            {/* Completed checklist */}
            <div className="text-left mb-6">
              <div className="text-xs font-semibold text-am-muted uppercase tracking-wider mb-3">Progress</div>
              <div className="space-y-2">
                {[
                  { text: 'IPFS registration file uploaded',              done: true          },
                  { text: `Identity minted on-chain (tokenId #${response.token_id})`, done: identityDone },
                  { text: `${stakeEth} ETH staked (your wallet → StakingContract)`,  done: stakeDone    },
                  { text: 'Agent endpoint live',                          done: identityDone  },
                ].map(({ text, done }) => (
                  <div key={text} className="flex items-start gap-2 text-sm text-am-text-2">
                    <span className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ${
                      done
                        ? 'bg-emerald-50 border border-emerald-200'
                        : 'bg-am-surface border border-am-border'
                    }`}>
                      {done
                        ? <Check size={10} className="text-am-emerald" />
                        : <span className="w-1.5 h-1.5 rounded-full bg-am-muted" />}
                    </span>
                    <span className={done ? 'text-am-text' : 'text-am-muted'}>{text}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex gap-3">
              {isJudge ? (
                <button onClick={() => navigate('/seller')}
                  className="flex-1 btn-primary flex items-center justify-center gap-2">
                  <LayoutDashboard size={15} /> Go to My Agents
                </button>
              ) : (
                <>
                  <button onClick={() => navigate('/seller')}
                    className="flex-1 btn-outline flex items-center justify-center gap-2">
                    <LayoutDashboard size={15} /> Dashboard
                  </button>
                  <button onClick={() => navigate('/marketplace')}
                    className="flex-1 btn-primary flex items-center justify-center gap-2">
                    Marketplace <ArrowRight size={15} />
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function StepHeader({ icon: Icon, title, desc }) {
  return (
    <div className="flex items-start gap-4 mb-6 pb-5 border-b border-am-border">
      <div className="w-10 h-10 rounded-2xl bg-indigo-50 border border-indigo-200 flex items-center justify-center flex-shrink-0">
        <Icon size={18} className="text-am-indigo" />
      </div>
      <div>
        <h2 className="font-bold text-am-text">{title}</h2>
        <p className="text-sm text-am-muted mt-0.5">{desc}</p>
      </div>
    </div>
  )
}

function Field({ label, children, error, hint }) {
  return (
    <div>
      <label className="text-xs font-semibold text-am-text-2 mb-1.5 block">{label}</label>
      {children}
      {hint  && !error && <p className="text-xs text-am-muted mt-1">{hint}</p>}
      {error && <p className="text-xs text-am-rose mt-1 flex items-center gap-1"><AlertCircle size={11} />{error}</p>}
    </div>
  )
}
