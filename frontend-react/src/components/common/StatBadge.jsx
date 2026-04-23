export default function StatBadge({ label, value, unit = '', color = 'indigo', icon: Icon }) {
  const colors = {
    indigo: { text: 'text-am-indigo',  bg: 'bg-indigo-50',  border: 'border-indigo-200' },
    violet: { text: 'text-am-violet',  bg: 'bg-violet-50',  border: 'border-violet-200' },
    emerald:{ text: 'text-am-emerald', bg: 'bg-emerald-50', border: 'border-emerald-200' },
    amber:  { text: 'text-am-amber',   bg: 'bg-amber-50',   border: 'border-amber-200'  },
    sky:    { text: 'text-am-sky',     bg: 'bg-sky-50',     border: 'border-sky-200'    },
    // legacy aliases
    cyan:   { text: 'text-am-sky',     bg: 'bg-sky-50',     border: 'border-sky-200'    },
    purple: { text: 'text-am-violet',  bg: 'bg-violet-50',  border: 'border-violet-200' },
    green:  { text: 'text-am-emerald', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  }
  const c = colors[color] || colors.indigo
  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${c.bg} ${c.border}`}>
      {Icon && <Icon size={13} className={c.text} />}
      <div>
        <div className={`text-sm font-semibold leading-none ${c.text}`}>
          {value}<span className="text-xs font-normal ml-0.5 opacity-70">{unit}</span>
        </div>
        <div className="text-xs text-am-muted mt-0.5">{label}</div>
      </div>
    </div>
  )
}
