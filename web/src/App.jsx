import { useState, useEffect, useCallback } from 'react'
import './index.css'

// ─── fixtures ───────────────────────────────────────────────────────────────
const FIXTURES = [
  'basic_change_p2wpkh', 'send_all_dust_change', 'rbf_basic', 'rbf_false_explicit',
  'rbf_multi_input', 'rbf_send_all', 'rbf_with_locktime', 'anti_fee_sniping',
  'locktime_block_height', 'locktime_unix_timestamp', 'locktime_no_rbf',
  'locktime_boundary_block', 'locktime_boundary_timestamp', 'multi_input_required',
  'multi_payment_change', 'many_payments', 'many_inputs_many_outputs',
  'large_utxo_pool', 'large_mixed_script_types', 'mixed_input_types',
  'p2pkh_input_basic', 'p2sh_p2wpkh_input', 'prefer_taproot_input',
  'small_utxos_consolidation',
]

const WARNING_META = {
  HIGH_FEE: { icon: '🔥', color: 'red', title: 'High Fee', desc: 'Fee exceeds 1,000,000 sats or rate exceeds 200 sat/vB. Consider lowering your fee rate.' },
  SEND_ALL: { icon: '⚡', color: 'amber', title: 'Send All', desc: 'No change output was created — all leftover sats became the miner fee.' },
  DUST_CHANGE: { icon: '🧹', color: 'orange', title: 'Dust Change', desc: 'Change output is below the 546 sat dust threshold and was dropped.' },
  RBF_SIGNALING: { icon: '🔄', color: 'cyan', title: 'RBF Signaling', desc: 'This transaction opts in to Replace-By-Fee (BIP-125) via nSequence ≤ 0xFFFFFFFD.' },
}

const SCRIPT_COLOR = {
  p2wpkh: 'green',
  p2tr: 'purple',
  p2pkh: 'amber',
  p2sh: 'orange',
  'p2sh-p2wpkh': 'orange',
  p2wsh: 'cyan',
}

// ─── helpers ─────────────────────────────────────────────────────────────────
const btcFormat = (sats) => {
  const btc = sats / 1e8
  return btc.toFixed(8).replace(/0+$/, '').replace(/\.$/, '.0') + ' BTC'
}
const satsFormat = (n) => n?.toLocaleString() + ' sats'
const truncate = (str, n = 18) => str?.length > n ? str.slice(0, n) + '…' : str

function copyToClipboard(text, setCopied) {
  navigator.clipboard.writeText(text).then(() => {
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  })
}

// ─── components ──────────────────────────────────────────────────────────────

function ScriptTag({ type }) {
  const color = SCRIPT_COLOR[type?.toLowerCase()] || 'muted'
  return <span className={`tag tag-${color}`}>{type?.toUpperCase()}</span>
}

function StatCard({ label, value, sub, icon }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{icon && <span>{icon}</span>}{label}</div>
      <div className="stat-value mono">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

function FlowDiagram({ report }) {
  const inputs = report.selected_inputs || []
  const payments = (report.outputs || []).filter(o => !o.is_change)
  const change = (report.outputs || []).find(o => o.is_change)

  return (
    <div className="flow">
      {/* Inputs column */}
      <div className="flow-col">
        <div className="flow-col-label">🪙 Selected Inputs</div>
        {inputs.slice(0, 5).map((u, i) => (
          <div key={i} className="flow-box input-box">
            <div className="flow-box-label">{u.script_type?.toUpperCase()}</div>
            <div className="flow-box-value" style={{ color: 'var(--green)' }}>+{satsFormat(u.value_sats)}</div>
          </div>
        ))}
        {inputs.length > 5 && <div className="flow-box"><div className="flow-box-label">…and {inputs.length - 5} more</div></div>}
      </div>

      <div className="flow-arrow">→</div>

      {/* Tx box */}
      <div className="flow-col" style={{ minWidth: '120px', alignSelf: 'center' }}>
        <div className="flow-box" style={{ textAlign: 'center', padding: '1.25rem', borderColor: 'var(--border-hover)' }}>
          <div style={{ fontSize: '1.8rem', marginBottom: '0.35rem' }}>₿</div>
          <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>PSBT Tx</div>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.3rem' }}>{report.vbytes} vB</div>
        </div>
      </div>

      <div className="flow-arrow">→</div>

      {/* Outputs column */}
      <div className="flow-col">
        <div className="flow-col-label">📤 Outputs</div>
        {payments.map((o, i) => (
          <div key={i} className="flow-box output-box">
            <div className="flow-box-label">Payment {i + 1} · {o.script_type?.toUpperCase()}</div>
            <div className="flow-box-value" style={{ color: 'var(--text-primary)' }}>{satsFormat(o.value_sats)}</div>
          </div>
        ))}
        {change && (
          <div className="flow-box change-box">
            <div className="flow-box-label">↩ Change · {change.script_type?.toUpperCase()}</div>
            <div className="flow-box-value" style={{ color: 'var(--accent-light)' }}>{satsFormat(change.value_sats)}</div>
          </div>
        )}
        <div className="flow-box fee-box">
          <div className="flow-box-label">⛏ Miner Fee</div>
          <div className="flow-box-value" style={{ color: 'var(--amber)' }}>{satsFormat(report.fee_sats)}</div>
        </div>
      </div>
    </div>
  )
}

function WarningItem({ code }) {
  const meta = WARNING_META[code] || { icon: '⚠️', color: 'amber', title: code, desc: code }
  return (
    <div className={`warning-item warn-${code}`}>
      <span className="warning-icon">{meta.icon}</span>
      <div className="warning-body">
        <strong>{meta.title}</strong>
        {meta.desc}
      </div>
    </div>
  )
}

function InputsSection({ inputs }) {
  return (
    <div className="section">
      <div className="section-header">
        <div className="section-title">🪙 Selected Inputs <span className="section-count">{inputs.length}</span></div>
        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Sorted by value ↓</div>
      </div>
      <div className="utxo-list">
        {inputs.map((u, i) => (
          <div key={i} className="utxo-row">
            <div style={{ minWidth: 0 }}>
              <div className="utxo-id">
                <strong>{truncate(u.txid, 14)}</strong>:{u.vout}
              </div>
              <div className="utxo-meta">
                <ScriptTag type={u.script_type} />
                <span className="mono" style={{ fontSize: '0.68rem', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '180px' }}>{truncate(u.address, 20)}</span>
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div className="utxo-value">+{satsFormat(u.value_sats)}</div>
              <div className="utxo-value-sats">{btcFormat(u.value_sats)}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function OutputsSection({ outputs }) {
  return (
    <div className="section">
      <div className="section-header">
        <div className="section-title">📤 Outputs <span className="section-count">{outputs.length}</span></div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {outputs.some(o => o.is_change) && <span className="tag tag-accent">↩ Change</span>}
        </div>
      </div>
      <div className="utxo-list">
        {outputs.map((o) => (
          <div key={o.n} className={`output-row${o.is_change ? ' is-change' : ''}`}>
            <div className={`output-index${o.is_change ? ' change-idx' : ''}`}>{o.n}</div>
            <div style={{ minWidth: 0 }}>
              <div className="output-addr">{o.address || o.script_pubkey_hex}</div>
              <div className="utxo-meta" style={{ marginTop: '0.25rem' }}>
                <ScriptTag type={o.script_type} />
                {o.is_change && <span className="tag tag-accent">↩ Change</span>}
              </div>
            </div>
            <div className={`output-value ${o.is_change ? 'change' : 'payment'}`}>
              {satsFormat(o.value_sats)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function PsbtSection({ psbt }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="section">
      <div className="section-header">
        <div className="section-title">📦 PSBT (BIP-174)</div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {copied && <span className="copy-feedback">✓ Copied!</span>}
          <button className="btn btn-ghost btn-sm" onClick={() => copyToClipboard(psbt, setCopied)}>
            📋 Copy
          </button>
        </div>
      </div>
      <div className="psbt-block">
        <div className="psbt-code">{psbt}</div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
          This base64-encoded PSBT contains the unsigned transaction and prevout metadata for each segwit input.
          Import it into a hardware wallet or signing software to authorize the spend.
        </div>
      </div>
    </div>
  )
}

function RbfLocktimeSection({ report }) {
  const ltLabel = { none: '—', block_height: '📦 Block Height', unix_timestamp: '⏰ Unix Timestamp' }
  return (
    <div className="section">
      <div className="section-header">
        <div className="section-title">🔐 RBF &amp; Locktime</div>
      </div>
      <div className="rbf-row">
        <div className="rbf-item">
          <span className="rbf-label">RBF Signaling</span>
          {report.rbf_signaling
            ? <span className="tag tag-cyan">ON · nSeq=0xFFFFFFFD</span>
            : <span className="tag tag-muted">OFF</span>}
        </div>
        <div className="rbf-item">
          <span className="rbf-label">nLockTime</span>
          <span className="tag tag-muted mono">{report.locktime}</span>
        </div>
        <div className="rbf-item">
          <span className="rbf-label">Type</span>
          <span className="tag tag-accent">{ltLabel[report.locktime_type] || report.locktime_type}</span>
        </div>
        <div className="rbf-item">
          <span className="rbf-label">Strategy</span>
          <span className="tag tag-purple">{report.strategy}</span>
        </div>
      </div>
      {report.rbf_signaling && (
        <div style={{ padding: '0 1.5rem 1rem', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
          Replace-By-Fee lets the sender rebroadcast this transaction with a higher fee before confirmation,
          incentivizing miners to prefer the replacement.
        </div>
      )}
      {report.locktime > 0 && (
        <div style={{ padding: '0 1.5rem 1rem', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
          {report.locktime_type === 'block_height'
            ? `This transaction cannot be mined until block #${report.locktime.toLocaleString()}.`
            : `This transaction cannot be mined until Unix timestamp ${report.locktime} (${new Date(report.locktime * 1000).toUTCString()}).`}
        </div>
      )}
    </div>
  )
}

function FeeSection({ report }) {
  const pct = Math.min((report.fee_sats / (report.fee_sats + (report.outputs || []).reduce((s, o) => s + o.value_sats, 0))) * 100, 100)
  const isHigh = report.fee_sats > 1_000_000 || report.fee_rate_sat_vb > 200
  return (
    <div className="section">
      <div className="section-header">
        <div className="section-title">⛏ Fee Breakdown</div>
      </div>
      <div className="fee-bar-wrap">
        <div className="fee-bar-labels">
          <span>Fee as % of total output</span>
          <span>{pct.toFixed(2)}%</span>
        </div>
        <div className="fee-bar-track">
          <div className={`fee-bar-fill${isHigh ? ' high' : ''}`} style={{ width: `${pct}%` }} />
        </div>
      </div>
      <div className="stats-grid" style={{ padding: '0 1.25rem 1.25rem', marginTop: '0.25rem' }}>
        <StatCard label="Fee" value={satsFormat(report.fee_sats)} icon="⛏" />
        <StatCard label="Rate" value={`${report.fee_rate_sat_vb} sat/vB`} icon="📊" />
        <StatCard label="Tx Size" value={`${report.vbytes} vB`} icon="📐" />
        <StatCard label="Network" value={report.network} icon="🌐" />
      </div>
    </div>
  )
}

function ResultsView({ report }) {
  const totalIn = (report.selected_inputs || []).reduce((s, u) => s + u.value_sats, 0)
  const totalOut = (report.outputs || []).reduce((s, o) => s + o.value_sats, 0)
  const hasWarnings = report.warnings?.length > 0

  return (
    <div className="results">
      {/* Top stats */}
      <div className="stats-grid">
        <StatCard icon="📥" label="Total In" value={satsFormat(totalIn)} sub={btcFormat(totalIn)} />
        <StatCard icon="📤" label="Total Out" value={satsFormat(totalOut)} sub={btcFormat(totalOut)} />
        <StatCard icon="⛏" label="Miner Fee" value={satsFormat(report.fee_sats)} sub={`${report.fee_rate_sat_vb} sat/vB`} />
        <StatCard icon="🔢" label="Inputs" value={report.selected_inputs?.length} sub={`${report.outputs?.length} outputs`} />
      </div>

      {/* Warnings */}
      {hasWarnings && (
        <div className="section">
          <div className="section-header">
            <div className="section-title">⚠️ Warnings <span className="section-count">{report.warnings.length}</span></div>
          </div>
          <div className="warnings-grid">
            {report.warnings.map((w, i) => <WarningItem key={i} code={w.code} />)}
          </div>
        </div>
      )}

      {/* Flow diagram */}
      <div className="section">
        <div className="section-header"><div className="section-title">🔀 Transaction Flow</div></div>
        <FlowDiagram report={report} />
      </div>

      {/* RBF / locktime */}
      <RbfLocktimeSection report={report} />

      {/* Fee breakdown */}
      <FeeSection report={report} />

      {/* Inputs */}
      <InputsSection inputs={report.selected_inputs || []} />

      {/* Outputs */}
      <OutputsSection outputs={report.outputs || []} />

      {/* PSBT */}
      <PsbtSection psbt={report.psbt_base64} />
    </div>
  )
}

// ─── main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [fixtureText, setFixtureText] = useState('')
  const [selectedFixture, setSelectedFixture] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [report, setReport] = useState(null)
  const [healthy, setHealthy] = useState(null)

  // Health check
  useEffect(() => {
    fetch('/api/health')
      .then(r => r.json())
      .then(d => setHealthy(d.ok === true))
      .catch(() => setHealthy(false))
  }, [])

  // Load fixture from dropdown
  const handleFixtureSelect = useCallback(async (name) => {
    setSelectedFixture(name)
    if (!name) return
    try {
      const res = await fetch(`/fixtures/${name}.json`)
      if (!res.ok) throw new Error('Not found')
      const text = await res.text()
      setFixtureText(text)
    } catch {
      setFixtureText('')
    }
  }, [])

  const handleBuild = useCallback(async () => {
    setLoading(true)
    setError(null)
    setReport(null)
    try {
      let fixture
      try { fixture = JSON.parse(fixtureText) }
      catch { throw new Error('Invalid JSON in fixture editor') }

      const res = await fetch('/api/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fixture),
      })
      const data = await res.json()
      if (!data.ok) {
        const err = data.error
        throw new Error(err?.message || JSON.stringify(err))
      }
      setReport(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [fixtureText])

  const handleClear = () => { setFixtureText(''); setSelectedFixture(''); setReport(null); setError(null) }

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-brand">
          <div className="header-logo">₿</div>
          <div>
            <div className="header-title">Coin<span>Smith</span></div>
          </div>
          <span className="header-badge">PSBT Builder</span>
        </div>
        <div className="header-health">
          <div className={`health-dot${healthy === false ? ' offline' : ''}`} />
          {healthy === null ? 'Connecting…' : healthy ? 'Server Online' : 'Server Offline'}
        </div>
      </header>

      {/* Main */}
      <main className="main">
        {/* ── Left: Input panel ── */}
        <aside className="panel input-panel">
          <div className="panel-header">
            <h2 className="panel-title">📄 Fixture Input</h2>
          </div>
          <div className="panel-body">
            <div className="fixture-select-row">
              <select
                id="fixture-select"
                className="fixture-select"
                value={selectedFixture}
                onChange={e => handleFixtureSelect(e.target.value)}
              >
                <option value="">Load a sample fixture…</option>
                {FIXTURES.map(f => <option key={f} value={f}>{f}</option>)}
              </select>
              <button className="btn btn-ghost btn-sm" onClick={handleClear} title="Clear">✕</button>
            </div>

            <div className="textarea-wrap">
              <span className="textarea-label">JSON</span>
              <textarea
                id="fixture-textarea"
                className="fixture-textarea"
                placeholder={`Paste fixture JSON here…\n\n{\n  "network": "mainnet",\n  "utxos": […],\n  "payments": […],\n  "change": {…},\n  "fee_rate_sat_vb": 5\n}`}
                value={fixtureText}
                onChange={e => setFixtureText(e.target.value)}
                spellCheck={false}
              />
            </div>

            <button
              id="build-btn"
              className="btn btn-primary btn-full"
              onClick={handleBuild}
              disabled={loading || !fixtureText.trim()}
            >
              {loading ? <><div className="spinner" />Building PSBT…</> : '⚡ Build PSBT'}
            </button>

            {error && (
              <div className="error-banner">
                <span className="error-icon">⛔</span>
                <div>
                  <strong style={{ display: 'block', marginBottom: '0.2rem' }}>Error</strong>
                  {error}
                </div>
              </div>
            )}

            {/* Quick key guide */}
            {!report && !error && (
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: 1.7, paddingTop: '0.25rem' }}>
                <strong style={{ color: 'var(--text-secondary)', display: 'block', marginBottom: '0.3rem' }}>Quick guide</strong>
                1. Select a sample fixture above, or paste your own JSON.<br />
                2. Click <strong style={{ color: 'var(--accent-light)' }}>Build PSBT</strong> to run coin selection.<br />
                3. Inspect inputs, outputs, fees, warnings, and the PSBT.
              </div>
            )}
          </div>
        </aside>

        {/* ── Right: Results ── */}
        <section aria-label="Build results">
          {!report && !error && !loading && (
            <div className="empty-state">
              <div className="empty-icon">₿</div>
              <div className="empty-title">Ready to build</div>
              <p className="empty-sub">Load a fixture and click <strong>Build PSBT</strong> to visualize your Bitcoin transaction.</p>
            </div>
          )}
          {loading && (
            <div className="empty-state">
              <div className="spinner" style={{ width: 32, height: 32, borderWidth: 3 }} />
              <div className="empty-title">Building transaction…</div>
              <p className="empty-sub">Running coin selection and constructing PSBT.</p>
            </div>
          )}
          {report && !loading && <ResultsView report={report} />}
        </section>
      </main>

      <footer className="footer">
        Coin Smith · Week 2 Bitcoin Challenge ·&nbsp;
        <a href="https://github.com/bitcoin/bips/blob/master/bip-0174.mediawiki" target="_blank" rel="noopener">BIP-174 PSBT spec</a>
      </footer>
    </div>
  )
}
