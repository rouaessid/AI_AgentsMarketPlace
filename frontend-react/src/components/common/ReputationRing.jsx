import PropTypes from 'prop-types'

function repColor(score) {
  if (score >= 90) return '#10b981'
  if (score >= 75) return '#6366f1'
  if (score >= 60) return '#f59e0b'
  return '#f43f5e'
}

export default function ReputationRing({ score, size = 64, stroke = 5 }) {
  const r      = (size - stroke * 2) / 2
  const circ   = 2 * Math.PI * r
  const offset = circ - (score / 100) * circ
  const color  = repColor(score)

  return (
    <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none"
          stroke="#e2e8f0" strokeWidth={stroke} />
        <circle cx={size/2} cy={size/2} r={r} fill="none"
          stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={circ} strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 0.8s ease' }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-bold text-am-text leading-none" style={{ fontSize: size * 0.26 }}>{score}</span>
        <span className="text-am-muted leading-none" style={{ fontSize: size * 0.14 }}>REP</span>
      </div>
    </div>
  )
}

ReputationRing.propTypes = {
  score:  PropTypes.number.isRequired,
  size:   PropTypes.number,
  stroke: PropTypes.number,
}
