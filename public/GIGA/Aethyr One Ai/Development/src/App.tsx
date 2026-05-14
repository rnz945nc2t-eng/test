import { useState, useCallback, useRef, useEffect } from 'react';
import JSZip from 'jszip';
import { saveAs } from 'file-saver';
import { useParticleField } from './useParticleField';
import {
  Lang, LANG_LABELS, ENTRY_FILENAME,
  getEntryTemplate, getMetaTemplate, getLockTemplate, README_CONTENT,
} from './templates';

// ── Types ─────────────────────────────────────────────────────────────────────

interface NodeConfig {
  name: string;
  description: string;
  tags: string[];
  lang: Lang;
  channel: string;
  sharedFiles: string[];
}

// ── Small components ──────────────────────────────────────────────────────────

function Dot({ color = '#3dd9c8' }: { color?: string }) {
  return (
    <span style={{
      display: 'inline-block', width: 7, height: 7,
      borderRadius: '50%', background: color,
      animation: 'pulse-dot 2s ease-in-out infinite',
    }} />
  );
}

function Tag({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '3px 10px 3px 12px',
      background: 'rgba(108,99,255,0.1)',
      border: '1px solid rgba(108,99,255,0.25)',
      borderRadius: 2,
      fontSize: 11, letterSpacing: '0.1em',
      color: '#b06eff',
    }}>
      {label}
      <button onClick={onRemove} style={{
        background: 'none', color: 'rgba(232,228,248,0.4)',
        fontSize: 13, lineHeight: 1, cursor: 'pointer', border: 'none',
        transition: 'color 0.2s', padding: 0,
      }}
        onMouseEnter={e => (e.currentTarget.style.color = '#f87171')}
        onMouseLeave={e => (e.currentTarget.style.color = 'rgba(232,228,248,0.4)')}>
        ×
      </button>
    </span>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 9, letterSpacing: '0.35em', textTransform: 'uppercase',
      color: 'rgba(232,228,248,0.32)', marginBottom: 8, fontWeight: 500,
    }}>
      {children}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 9, letterSpacing: '0.45em', textTransform: 'uppercase',
      color: '#6c63ff', marginBottom: 20, fontWeight: 500,
    }}>
      {children}
    </div>
  );
}

function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };
  return (
    <div style={{
      position: 'relative', background: '#06040e',
      border: '1px solid rgba(108,99,255,0.13)', borderRadius: 4, overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 14px',
        background: 'rgba(108,99,255,0.06)',
        borderBottom: '1px solid rgba(108,99,255,0.1)',
      }}>
        <span style={{ fontSize: 10, letterSpacing: '0.25em', color: 'rgba(232,228,248,0.28)' }}>{lang || 'code'}</span>
        <button onClick={copy} style={{
          fontSize: 9, letterSpacing: '0.2em', textTransform: 'uppercase',
          color: copied ? '#3dd9c8' : 'rgba(232,228,248,0.32)',
          background: 'none', border: 'none', cursor: 'pointer', transition: 'color 0.2s',
        }}>
          {copied ? 'copied!' : 'copy'}
        </button>
      </div>
      <pre style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11.5, lineHeight: 1.75,
        color: 'rgba(232,228,248,0.75)',
        padding: '16px 18px',
        overflowX: 'auto', whiteSpace: 'pre',
        maxHeight: 340, overflowY: 'auto',
        margin: 0,
      }}>
        {code}
      </pre>
    </div>
  );
}

// ── Folder tree ───────────────────────────────────────────────────────────────

function FolderTree({ config }: { config: NodeConfig }) {
  const entryFile = ENTRY_FILENAME[config.lang];
  const name = config.name || 'my-node';

  type Row = { indent: number; icon: string; name: string; dim?: boolean; color?: string };
  const tree: Row[] = [
    { indent: 0, icon: '📁', name: name + '/', color: '#b06eff' },
    { indent: 1, icon: '📁', name: '.aura/', dim: true },
    { indent: 2, icon: '🔑', name: 'identity.key', dim: true },
    { indent: 2, icon: '📄', name: 'aura.pub', dim: true },
    { indent: 2, icon: '🔐', name: 'encryption.key', dim: true },
    { indent: 2, icon: '📄', name: 'encryption.pub', dim: true },
    { indent: 1, icon: '📄', name: 'aura.meta', color: '#3dd9c8' },
    { indent: 1, icon: '⚙️', name: entryFile, color: '#6c63ff' },
    { indent: 1, icon: '🔒', name: 'aura.lock', dim: true },
    { indent: 1, icon: '📁', name: 'in/', color: '#3dd9c8' },
    { indent: 1, icon: '📁', name: 'out/', color: '#f0c060' },
    { indent: 1, icon: '📁', name: 'shared/' },
    ...config.sharedFiles.map(f => ({ indent: 2, icon: '📄', name: f, color: '#b06eff' as string })),
    { indent: 1, icon: '📁', name: 'private/', dim: true },
  ];

  return (
    <div style={{ background: '#06040e', border: '1px solid rgba(108,99,255,0.13)', borderRadius: 4, overflow: 'hidden' }}>
      <div style={{
        padding: '8px 14px', background: 'rgba(108,99,255,0.05)',
        borderBottom: '1px solid rgba(108,99,255,0.1)',
        fontSize: 10, letterSpacing: '0.25em', color: 'rgba(232,228,248,0.28)',
      }}>
        folder structure — live preview
      </div>
      <div style={{ padding: '12px 16px' }}>
        {tree.map((item, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 7,
            paddingLeft: item.indent * 16, paddingTop: 2, paddingBottom: 2,
            fontFamily: "'JetBrains Mono', monospace", fontSize: 11.5, lineHeight: 1.6,
            color: item.color || (item.dim ? 'rgba(232,228,248,0.22)' : 'rgba(232,228,248,0.6)'),
          }}>
            <span style={{ fontSize: 11 }}>{item.icon}</span>
            <span>{item.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Live Field Connection (real API) ─────────────────────────────────────────

interface NodeStatus {
  node_id: string;
  wallet: string;
  name: string;
  channel: string | null;
  field: string;
  aura: Record<string, number>;
  file_count: number;
  balance: number;
  peers: number;
  uptime: number;
}

interface PeerRecord {
  node_id: string;
  name: string;
  addr: string;
  tags: string[];
  last_seen: number;
}

interface SeekResult {
  node_id: string;
  name: string;
  score: number;
  tags: string[];
  addr: string;
}

function FieldConnect() {
  const [apiUrl, setApiUrl] = useState('http://127.0.0.1:7778');
  const [editingUrl, setEditingUrl] = useState(false);
  const [urlInput, setUrlInput] = useState('http://127.0.0.1:7778');
  const [status, setStatus] = useState<NodeStatus | null>(null);
  const [peers, setPeers] = useState<PeerRecord[]>([]);
  const [inFiles, setInFiles] = useState<{ name: string; size: number }[]>([]);
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(true);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SeekResult[]>([]);
  const [seeking, setSeeking] = useState(false);
  const [seekError, setSeekError] = useState('');
  const [activeView, setActiveView] = useState<'peers' | 'seek' | 'in'>('peers');

  const fetchAll = useCallback(async (url: string) => {
    try {
      const [sRes, pRes, iRes] = await Promise.all([
        fetch(`${url}/status`, { signal: AbortSignal.timeout(3000) }),
        fetch(`${url}/peers`,  { signal: AbortSignal.timeout(3000) }),
        fetch(`${url}/in`,     { signal: AbortSignal.timeout(3000) }),
      ]);
      if (!sRes.ok) throw new Error(`HTTP ${sRes.status}`);
      const [s, p, i] = await Promise.all([sRes.json(), pRes.json(), iRes.json()]);
      setStatus(s);
      setPeers(p.peers || []);
      setInFiles(i.files || []);
      setConnected(true);
      setConnecting(false);
    } catch {
      setConnected(false);
      setConnecting(false);
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    fetchAll(apiUrl);
    const iv = setInterval(() => fetchAll(apiUrl), 5000);
    return () => clearInterval(iv);
  }, [apiUrl, fetchAll]);

  const doSeek = async () => {
    if (!query.trim() || !connected) return;
    setSeeking(true);
    setResults([]);
    setSeekError('');
    try {
      const res = await fetch(`${apiUrl}/seek`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
        signal: AbortSignal.timeout(8000),
      });
      const data = await res.json();
      setResults(data.results || []);
      if ((data.results || []).length === 0) setSeekError('no resonance — no peers matched this query');
    } catch (e: any) {
      setSeekError(e.message || 'Seek failed');
    }
    setSeeking(false);
  };

  const inputStyle: React.CSSProperties = {
    flex: 1, padding: '11px 14px',
    background: '#09071a', border: '1px solid rgba(108,99,255,0.2)',
    borderRadius: 3, color: 'rgba(232,228,248,0.9)',
    fontSize: 13, fontFamily: "'JetBrains Mono', monospace",
    outline: 'none', transition: 'border-color 0.2s',
  };

  const tabBtn = (view: typeof activeView, label: string) => (
    <button onClick={() => setActiveView(view)} style={{
      fontSize: 9, letterSpacing: '0.25em', textTransform: 'uppercase',
      color: activeView === view ? '#6c63ff' : 'rgba(232,228,248,0.28)',
      background: activeView === view ? 'rgba(108,99,255,0.1)' : 'none',
      border: '1px solid',
      borderColor: activeView === view ? 'rgba(108,99,255,0.3)' : 'rgba(255,255,255,0.06)',
      borderRadius: 2, padding: '5px 14px', cursor: 'pointer', transition: 'all 0.2s',
    }}>
      {label}
    </button>
  );

  /* ── Not connected ── */
  if (!connected) {
    return (
      <div style={{
        border: '1px solid rgba(108,99,255,0.15)', borderRadius: 6,
        overflow: 'hidden',
      }}>
        <div style={{
          padding: '14px 20px',
          background: 'rgba(108,99,255,0.05)',
          borderBottom: '1px solid rgba(108,99,255,0.1)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{
              display: 'inline-block', width: 7, height: 7,
              borderRadius: '50%', background: '#f87171',
            }} />
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'rgba(232,228,248,0.4)' }}>
              {connecting ? 'connecting…' : 'no node connected'}
            </span>
          </div>
          {/* URL editor */}
          {editingUrl ? (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input
                value={urlInput}
                onChange={e => setUrlInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') { setApiUrl(urlInput); setEditingUrl(false); setConnecting(true); }
                  if (e.key === 'Escape') setEditingUrl(false);
                }}
                style={{ ...inputStyle, flex: 'unset', width: 220, fontSize: 11, padding: '5px 10px' }}
                autoFocus
              />
              <button onClick={() => { setApiUrl(urlInput); setEditingUrl(false); setConnecting(true); }}
                style={{ fontSize: 9, letterSpacing: '0.2em', textTransform: 'uppercase', color: '#3dd9c8', background: 'none', border: 'none', cursor: 'pointer' }}>
                connect
              </button>
            </div>
          ) : (
            <button onClick={() => { setEditingUrl(true); setUrlInput(apiUrl); }}
              style={{ fontSize: 9, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'rgba(232,228,248,0.28)', background: 'none', border: 'none', cursor: 'pointer' }}>
              {apiUrl} ✎
            </button>
          )}
        </div>
        <div style={{ padding: '32px 24px' }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: 'rgba(232,228,248,0.35)', lineHeight: 2, marginBottom: 20 }}>
            Start your node to connect this panel to the live field:
          </div>
          <CodeBlock lang="bash" code={`# Install (once)\npip install aura-protocol\n\n# Build your node folder above, then:\naura join ./your-node\n\n# API starts automatically at http://127.0.0.1:7778\n# This panel connects automatically.`} />
          <button
            onClick={() => { setConnecting(true); fetchAll(apiUrl); }}
            style={{
              marginTop: 16, padding: '9px 22px',
              background: 'rgba(108,99,255,0.1)', border: '1px solid rgba(108,99,255,0.25)',
              borderRadius: 3, color: '#b06eff',
              fontSize: 10, letterSpacing: '0.25em', textTransform: 'uppercase',
              cursor: 'pointer',
            }}>
            retry connection
          </button>
        </div>
      </div>
    );
  }

  /* ── Connected ── */
  return (
    <div style={{ border: '1px solid rgba(108,99,255,0.2)', borderRadius: 6, overflow: 'hidden' }}>
      {/* Status bar */}
      <div style={{
        padding: '12px 20px',
        background: 'rgba(108,99,255,0.06)',
        borderBottom: '1px solid rgba(108,99,255,0.1)',
        display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: '#3dd9c8', animation: 'pulse-dot 2s ease-in-out infinite' }} />
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: '#fff', fontWeight: 600 }}>
            {status?.name}
          </span>
        </div>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: 'rgba(232,228,248,0.3)' }}>
          {status?.node_id}
        </span>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#6c63ff' }}>
          {status?.field}
        </span>
        {status?.channel && (
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#b06eff' }}>
            #{status.channel}
          </span>
        )}
        <span style={{ marginLeft: 'auto', fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#3dd9c8' }}>
          {status?.balance.toFixed(2)} AYR
        </span>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: 'rgba(232,228,248,0.25)' }}>
          {peers.length} peer{peers.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Aura tags */}
      {status?.aura && Object.keys(status.aura).length > 0 && (
        <div style={{
          padding: '10px 20px',
          borderBottom: '1px solid rgba(108,99,255,0.07)',
          display: 'flex', gap: 6, flexWrap: 'wrap',
        }}>
          {Object.entries(status.aura)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 10)
            .map(([tag, weight]) => (
              <span key={tag} style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 9, letterSpacing: '0.12em',
                padding: '2px 8px', borderRadius: 2,
                background: `rgba(108,99,255,${weight * 0.15})`,
                border: `1px solid rgba(108,99,255,${weight * 0.4})`,
                color: `rgba(176,110,255,${0.5 + weight * 0.5})`,
              }}>
                {tag}
              </span>
            ))}
        </div>
      )}

      {/* Tab bar */}
      <div style={{
        padding: '10px 20px',
        borderBottom: '1px solid rgba(108,99,255,0.07)',
        display: 'flex', gap: 6,
      }}>
        {tabBtn('peers', `peers (${peers.length})`)}
        {tabBtn('seek', 'seek')}
        {tabBtn('in', `in/ (${inFiles.length})`)}
      </div>

      {/* Content */}
      <div style={{ padding: '16px 20px', minHeight: 120 }}>

        {/* Peers */}
        {activeView === 'peers' && (
          peers.length === 0 ? (
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'rgba(232,228,248,0.25)', padding: '12px 0' }}>
              no peers — other nodes will appear here as they join the field
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {peers.map((p, i) => (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: 14,
                  padding: '10px 14px',
                  background: 'rgba(255,255,255,0.015)',
                  border: '1px solid rgba(255,255,255,0.05)',
                  borderRadius: 3,
                }}>
                  <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#3dd9c8', flexShrink: 0 }} />
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: '#fff', flex: 1 }}>
                    {p.name}
                  </span>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: 'rgba(232,228,248,0.22)' }}>
                    {p.node_id}
                  </span>
                  <span style={{ fontSize: 10, color: 'rgba(232,228,248,0.25)' }}>
                    {p.tags.slice(0, 3).join('  ')}
                  </span>
                </div>
              ))}
            </div>
          )
        )}

        {/* Seek */}
        {activeView === 'seek' && (
          <div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
              <input
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && doSeek()}
                placeholder="python music data science..."
                style={inputStyle}
                onFocus={e => (e.target.style.borderColor = '#6c63ff')}
                onBlur={e => (e.target.style.borderColor = 'rgba(108,99,255,0.2)')}
              />
              <button onClick={doSeek} disabled={seeking} style={{
                padding: '11px 22px',
                background: 'rgba(108,99,255,0.14)', border: '1px solid rgba(108,99,255,0.3)',
                borderRadius: 3, color: '#b06eff',
                fontSize: 11, letterSpacing: '0.25em', textTransform: 'uppercase',
                cursor: seeking ? 'default' : 'pointer', opacity: seeking ? 0.6 : 1,
                transition: 'background 0.2s',
              }}
                onMouseEnter={e => !seeking && (e.currentTarget.style.background = 'rgba(108,99,255,0.26)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'rgba(108,99,255,0.14)')}>
                {seeking ? '···' : 'seek'}
              </button>
            </div>
            {results.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                {results.map((r, i) => (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'center', gap: 14,
                    padding: '10px 14px',
                    background: 'rgba(255,255,255,0.015)',
                    border: '1px solid rgba(255,255,255,0.05)',
                    borderRadius: 3,
                    animation: `slide-in 0.25s ease ${i * 0.05}s both`,
                  }}>
                    <div style={{ width: 76, flexShrink: 0 }}>
                      <div style={{
                        height: 2, borderRadius: 1,
                        background: 'linear-gradient(90deg,#6c63ff,#3dd9c8)',
                        width: `${r.score * 100}%`, opacity: 0.85,
                      }} />
                      <div style={{ fontSize: 9, color: '#6c63ff', marginTop: 4, fontFamily: "'JetBrains Mono', monospace", letterSpacing: '0.15em' }}>
                        {(r.score * 100).toFixed(0)}%
                      </div>
                    </div>
                    <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: '#fff', flex: 1 }}>{r.name}</span>
                    <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: 'rgba(232,228,248,0.22)' }}>{r.node_id}</span>
                    <span style={{ fontSize: 10, color: 'rgba(232,228,248,0.28)' }}>{(r.tags || []).slice(0, 3).join('  ')}</span>
                  </div>
                ))}
              </div>
            )}
            {seekError && (
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'rgba(232,228,248,0.3)', padding: '8px 0' }}>
                {seekError}
              </div>
            )}
          </div>
        )}

        {/* In/ files */}
        {activeView === 'in' && (
          inFiles.length === 0 ? (
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'rgba(232,228,248,0.25)', padding: '12px 0' }}>
              in/ is empty — files routed to you by peers will appear here
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {inFiles.map((f, i) => (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '8px 14px',
                  background: 'rgba(61,217,200,0.03)',
                  border: '1px solid rgba(61,217,200,0.08)',
                  borderRadius: 3,
                }}>
                  <span style={{ color: '#3dd9c8', fontSize: 10 }}>↓</span>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: '#fff', flex: 1 }}>{f.name}</span>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: 'rgba(232,228,248,0.25)' }}>
                    {f.size < 1024 ? `${f.size} B` : `${(f.size / 1024).toFixed(1)} KB`}
                  </span>
                </div>
              ))}
            </div>
          )
        )}
      </div>
    </div>
  );
}

// ── Protocol step ─────────────────────────────────────────────────────────────

function ProtoStep({ n, title, cmd, desc, color = '#6c63ff' }: {
  n: string; title: string; cmd: string; desc: string; color?: string;
}) {
  return (
    <div style={{
      border: '1px solid rgba(108,99,255,0.1)', borderRadius: 4, overflow: 'hidden',
      transition: 'border-color 0.3s',
    }}
      onMouseEnter={e => (e.currentTarget.style.borderColor = 'rgba(108,99,255,0.28)')}
      onMouseLeave={e => (e.currentTarget.style.borderColor = 'rgba(108,99,255,0.1)')}>
      <div style={{
        padding: '16px 20px', background: 'rgba(108,99,255,0.03)',
        borderBottom: '1px solid rgba(108,99,255,0.08)',
        display: 'flex', alignItems: 'center', gap: 16,
      }}>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 26, color, opacity: 0.22, lineHeight: 1 }}>{n}</span>
        <div>
          <div style={{ fontSize: 14, fontWeight: 500, color: '#fff', marginBottom: 4 }}>{title}</div>
          <code style={{
            fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color,
            background: `${color}18`, padding: '2px 8px', borderRadius: 2,
          }}>
            {cmd}
          </code>
        </div>
      </div>
      <div style={{ padding: '13px 20px', fontSize: 12.5, color: 'rgba(232,228,248,0.45)', lineHeight: 1.85 }}>
        {desc}
      </div>
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  useParticleField('bg-canvas');

  const [config, setConfig] = useState<NodeConfig>({
    name: '', description: '', tags: [], lang: 'py', channel: '', sharedFiles: [],
  });
  const [tagInput, setTagInput] = useState('');
  const [sharedInput, setSharedInput] = useState('');
  const [activeTab, setActiveTab] = useState<'entry' | 'meta' | 'readme'>('entry');
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);

  const up = useCallback(<K extends keyof NodeConfig>(k: K, v: NodeConfig[K]) => {
    setConfig(prev => ({ ...prev, [k]: v }));
  }, []);

  const addTag = () => {
    const t = tagInput.trim().toLowerCase().replace(/\s+/g, '-');
    if (t && !config.tags.includes(t)) up('tags', [...config.tags, t]);
    setTagInput('');
  };

  const addSharedFile = () => {
    const f = sharedInput.trim();
    if (f && !config.sharedFiles.includes(f)) up('sharedFiles', [...config.sharedFiles, f]);
    setSharedInput('');
  };

  const entryCode  = getEntryTemplate(config.lang, config.name || 'my-node');
  const metaCode   = getMetaTemplate(config.name, config.description, config.tags, config.lang);
  const lockCode   = getLockTemplate(config.name);
  const entryFile  = ENTRY_FILENAME[config.lang];
  const folderName = (config.name || 'my-node').replace(/\s+/g, '-').toLowerCase();

  const downloadZip = async () => {
    setDownloading(true);
    const zip = new JSZip();
    const root = zip.folder(folderName)!;
    root.file('aura.meta', metaCode);
    root.file(entryFile, entryCode);
    root.file('aura.lock', lockCode);
    root.file('README.md', README_CONTENT);
    root.folder('in');
    root.folder('out');
    const shared = root.folder('shared')!;
    config.sharedFiles.forEach(f => shared.file(f, `# ${f}\n`));
    root.folder('private');
    root.folder('.aura')!.file('README.txt', 'Keys are generated automatically on first join:\n  pip install aura-protocol\n  aura join .\n\nThe .aura/ directory holds your Ed25519 signing keys and\nX25519 encryption keys. Never share these files.\n');
    const blob = await zip.generateAsync({ type: 'blob' });
    saveAs(blob, `${folderName}.zip`);
    setDownloading(false);
    setDownloaded(true);
    setTimeout(() => setDownloaded(false), 3000);
  };

  const builderRef = useRef<HTMLDivElement>(null);
  const scrollToBuilder = () => builderRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  // Scroll-reveal
  useEffect(() => {
    const els = document.querySelectorAll<HTMLElement>('.reveal');
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          (e.target as HTMLElement).style.opacity = '1';
          (e.target as HTMLElement).style.transform = 'translateY(0)';
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0.07 });
    els.forEach(el => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(20px)';
      el.style.transition = 'opacity 0.55s ease, transform 0.55s ease';
      io.observe(el);
    });
    return () => io.disconnect();
  }, []);

  const myAuraTags = [config.lang, ...config.tags, ...config.name.split(/[-_\s]+/).filter(Boolean)].filter(Boolean);

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '10px 14px',
    background: '#09071a', border: '1px solid rgba(108,99,255,0.18)',
    borderRadius: 3, color: 'rgba(232,228,248,0.9)',
    fontSize: 13, fontFamily: "'JetBrains Mono', monospace",
    outline: 'none', transition: 'border-color 0.2s',
  };

  return (
    <>
      <canvas id="bg-canvas" style={{ position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none' }} />

      <div style={{ position: 'relative', zIndex: 1 }}>

        {/* NAV */}
        <nav style={{
          position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0 32px', height: 52,
          background: 'rgba(6,4,15,0.85)', backdropFilter: 'blur(14px)',
          borderBottom: '1px solid rgba(108,99,255,0.1)',
        }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 15, letterSpacing: '0.3em', color: '#fff', fontWeight: 500 }}>
            A<span style={{ color: '#6c63ff' }}>U</span>RA
            <span style={{ marginLeft: 10, fontSize: 9, letterSpacing: '0.2em', color: 'rgba(232,228,248,0.28)', fontWeight: 300 }}>v0.4</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 28 }}>
            <a href="#protocol" style={{ fontSize: 11, letterSpacing: '0.2em', color: 'rgba(232,228,248,0.4)', textDecoration: 'none', textTransform: 'uppercase', transition: 'color 0.2s' }}
              onMouseEnter={e => (e.currentTarget.style.color = '#fff')}
              onMouseLeave={e => (e.currentTarget.style.color = 'rgba(232,228,248,0.4)')}>
              Protocol
            </a>
            <button onClick={scrollToBuilder} style={{
              padding: '7px 18px', background: 'rgba(108,99,255,0.13)',
              border: '1px solid rgba(108,99,255,0.28)', borderRadius: 2,
              fontSize: 10, letterSpacing: '0.25em', color: '#b06eff',
              textTransform: 'uppercase', cursor: 'pointer', transition: 'background 0.2s',
            }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(108,99,255,0.25)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'rgba(108,99,255,0.13)')}>
              Build Node
            </button>
          </div>
        </nav>

        {/* HERO */}
        <section style={{
          minHeight: '100vh', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          padding: '80px 24px 48px', textAlign: 'center', position: 'relative',
        }}>
          <div style={{
            position: 'absolute', inset: 0,
            background: 'radial-gradient(ellipse 60% 55% at 50% 42%, rgba(108,99,255,0.09) 0%, transparent 65%)',
            pointerEvents: 'none',
          }} />
          <div style={{ position: 'relative', zIndex: 1 }}>
            <div style={{
              fontSize: 10, letterSpacing: '0.55em', textTransform: 'uppercase',
              color: '#3dd9c8', marginBottom: 28,
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
            }}>
              <Dot /> Autonomous Universal Resonance Architecture
            </div>
            <h1 style={{
              fontSize: 'clamp(88px,20vw,210px)', lineHeight: 0.85, fontWeight: 700,
              letterSpacing: '-0.02em', marginBottom: 28,
              background: 'linear-gradient(135deg,#fff 0%,#b06eff 42%,#6c63ff 68%,#3dd9c8 100%)',
              WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text',
            }}>
              AURA
            </h1>
            <p style={{
              fontSize: 'clamp(16px,2.2vw,23px)', fontWeight: 300,
              color: 'rgba(232,228,248,0.58)', maxWidth: 580, margin: '0 auto 14px',
              lineHeight: 1.65, fontStyle: 'italic',
            }}>
              A folder is a node. Its files are the aura.<br />
              No addresses. No index. Just resonance.
            </p>
            <p style={{ fontSize: 13, color: 'rgba(232,228,248,0.32)', maxWidth: 460, margin: '0 auto 52px', lineHeight: 1.75 }}>
              Build your node. Configure your aura. Download your folder.
              Mount it into the field and let the protocol find you.
            </p>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
              <button onClick={scrollToBuilder} style={{
                padding: '14px 34px',
                background: 'linear-gradient(135deg,#6c63ff,#b06eff)',
                border: 'none', borderRadius: 3,
                fontSize: 11, letterSpacing: '0.3em', textTransform: 'uppercase',
                color: '#fff', fontWeight: 600, cursor: 'pointer',
                boxShadow: '0 0 36px rgba(108,99,255,0.28)',
                transition: 'transform 0.2s, box-shadow 0.2s',
              }}
                onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 0 52px rgba(108,99,255,0.44)'; }}
                onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 0 36px rgba(108,99,255,0.28)'; }}>
                Build Your Node →
              </button>
              <a href="#protocol" style={{
                padding: '14px 34px', background: 'transparent',
                border: '1px solid rgba(108,99,255,0.22)', borderRadius: 3,
                fontSize: 11, letterSpacing: '0.3em', textTransform: 'uppercase',
                color: 'rgba(232,228,248,0.5)', textDecoration: 'none', display: 'inline-block',
                transition: 'all 0.2s',
              }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = 'rgba(108,99,255,0.5)'; e.currentTarget.style.color = '#fff'; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(108,99,255,0.22)'; e.currentTarget.style.color = 'rgba(232,228,248,0.5)'; }}>
                Read Protocol
              </a>
            </div>
          </div>
          <div style={{
            position: 'absolute', bottom: 38, left: '50%', transform: 'translateX(-50%)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, opacity: 0.28,
          }}>
            <span style={{ fontSize: 9, letterSpacing: '0.35em', textTransform: 'uppercase' }}>scroll</span>
            <div style={{ width: 1, height: 36, background: 'linear-gradient(to bottom,rgba(108,99,255,.8),transparent)' }} />
          </div>
        </section>

        {/* TICKER */}
        <div style={{
          borderTop: '1px solid rgba(108,99,255,0.09)', borderBottom: '1px solid rgba(108,99,255,0.09)',
          padding: '13px 0', overflow: 'hidden', background: 'rgba(108,99,255,0.025)',
        }}>
          <div style={{ display: 'flex', gap: 0, whiteSpace: 'nowrap', width: 'max-content', animation: 'ticker 32s linear infinite' }}>
            {['NO ADDRESSES','◆','NO HTML','◆','YOUR FOLDER IS YOUR NODE','◆','ANY LANGUAGE','◆','NO APPS','◆',
              'THE FIELD FINDS YOU','◆','Ed25519 IDENTITY','◆','X25519 ENCRYPTION','◆','UDP MULTICAST','◆',
              'NO ADDRESSES','◆','NO HTML','◆','YOUR FOLDER IS YOUR NODE','◆','ANY LANGUAGE','◆','NO APPS','◆',
              'THE FIELD FINDS YOU','◆','Ed25519 IDENTITY','◆','X25519 ENCRYPTION','◆','UDP MULTICAST','◆',
            ].map((item, i) => (
              <span key={i} style={{
                padding: '0 28px', fontSize: 10, letterSpacing: '0.35em',
                color: item === '◆' ? '#6c63ff' : 'rgba(232,228,248,0.28)',
              }}>{item}</span>
            ))}
          </div>
        </div>

        {/* WHAT IS AURA */}
        <section style={{ padding: '96px 24px', maxWidth: 1100, margin: '0 auto' }}>
          <div className="reveal" style={{ textAlign: 'center', marginBottom: 60 }}>
            <SectionLabel>The single idea</SectionLabel>
            <h2 style={{ fontSize: 'clamp(34px,6vw,70px)', fontWeight: 700, lineHeight: 0.95, letterSpacing: '-0.02em', marginBottom: 18 }}>
              A folder is a node.<br /><span style={{ color: 'rgba(232,228,248,0.3)' }}>Files are everything.</span>
            </h2>
            <p style={{ fontSize: 14.5, color: 'rgba(232,228,248,0.45)', maxWidth: 540, margin: '0 auto', lineHeight: 1.85 }}>
              AURA has no server, no app, no address book. Every participant is a folder
              on their own machine. The protocol finds resonant nodes by what they contain — not where they are.
            </p>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 2 }}>
            {[
              { icon: '📁', title: 'Folder = Node', desc: 'Your directory is your identity in the field. No registration. No username. You are what your files say you are.', color: '#6c63ff' },
              { icon: '🌊', title: 'Files = Aura', desc: 'The field scans your files, names, and meta to build a semantic fingerprint. Python scripts, audio, markdown — all become signal.', color: '#b06eff' },
              { icon: '◎', title: 'Seek = Discovery', desc: 'Type what you want. The field scores every node for resonance with your query and surfaces the closest matches instantly.', color: '#3dd9c8' },
              { icon: '⬡', title: 'Route = Mail', desc: 'Drop a file in out/. The field delivers it to the in/ of the most resonant peer. No email. No attachment. Just shadow routing.', color: '#f0c060' },
            ].map((card, i) => (
              <div key={i} className="reveal" style={{
                padding: '30px 26px', background: 'rgba(255,255,255,0.016)',
                border: '1px solid rgba(108,99,255,0.09)', borderRadius: 4,
                transition: 'border-color 0.3s, background 0.3s', cursor: 'default',
              }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = `${card.color}44`; e.currentTarget.style.background = `${card.color}07`; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(108,99,255,0.09)'; e.currentTarget.style.background = 'rgba(255,255,255,0.016)'; }}>
                <div style={{ fontSize: 26, marginBottom: 14 }}>{card.icon}</div>
                <h3 style={{ fontSize: 14.5, fontWeight: 600, color: card.color, marginBottom: 10 }}>{card.title}</h3>
                <p style={{ fontSize: 12.5, color: 'rgba(232,228,248,0.42)', lineHeight: 1.85 }}>{card.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* NODE BUILDER */}
        <section ref={builderRef} id="builder" style={{
          padding: '80px 24px 100px',
          background: 'linear-gradient(180deg,transparent 0%,rgba(108,99,255,0.035) 30%,rgba(108,99,255,0.035) 70%,transparent 100%)',
          borderTop: '1px solid rgba(108,99,255,0.09)', borderBottom: '1px solid rgba(108,99,255,0.09)',
        }}>
          <div style={{ maxWidth: 1100, margin: '0 auto' }}>
            <div className="reveal" style={{ textAlign: 'center', marginBottom: 52 }}>
              <SectionLabel>Node Builder</SectionLabel>
              <h2 style={{ fontSize: 'clamp(30px,5vw,58px)', fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 12 }}>
                Build your aura folder
              </h2>
              <p style={{ fontSize: 14, color: 'rgba(232,228,248,0.42)', maxWidth: 480, margin: '0 auto' }}>
                Configure your node. Preview the generated files. Download your folder. Mount it into the field.
              </p>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(300px,400px) 1fr', gap: 2, alignItems: 'start' }}>

              {/* LEFT — CONFIG */}
              <div className="reveal" style={{
                background: 'rgba(12,9,24,0.85)', border: '1px solid rgba(108,99,255,0.16)',
                borderRadius: 4, overflow: 'hidden',
              }}>
                <div style={{
                  padding: '13px 20px', background: 'rgba(108,99,255,0.07)',
                  borderBottom: '1px solid rgba(108,99,255,0.1)',
                  display: 'flex', alignItems: 'center', gap: 10,
                  fontSize: 10, letterSpacing: '0.28em', textTransform: 'uppercase',
                  color: 'rgba(232,228,248,0.35)',
                }}>
                  <Dot color="#6c63ff" /> node configuration
                </div>

                <div style={{ padding: '22px 20px', display: 'flex', flexDirection: 'column', gap: 20 }}>

                  {/* Name */}
                  <div>
                    <FieldLabel>Node Name</FieldLabel>
                    <input value={config.name} onChange={e => up('name', e.target.value)}
                      placeholder="my-node" style={inputStyle}
                      onFocus={e => (e.target.style.borderColor = '#6c63ff')}
                      onBlur={e => (e.target.style.borderColor = 'rgba(108,99,255,0.18)')} />
                  </div>

                  {/* Description */}
                  <div>
                    <FieldLabel>Description</FieldLabel>
                    <textarea value={config.description} onChange={e => up('description', e.target.value)}
                      placeholder="What is this node about?" rows={2}
                      style={{ ...inputStyle, resize: 'vertical' }}
                      onFocus={e => (e.target.style.borderColor = '#6c63ff')}
                      onBlur={e => (e.target.style.borderColor = 'rgba(108,99,255,0.18)')} />
                  </div>

                  {/* Tags */}
                  <div>
                    <FieldLabel>Tags — what you are in the field</FieldLabel>
                    {config.tags.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 8 }}>
                        {config.tags.map(t => (
                          <Tag key={t} label={t} onRemove={() => up('tags', config.tags.filter(x => x !== t))} />
                        ))}
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input value={tagInput} onChange={e => setTagInput(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && addTag()}
                        placeholder="python, art, audio..."
                        style={{ ...inputStyle, fontSize: 12 }}
                        onFocus={e => (e.target.style.borderColor = '#6c63ff')}
                        onBlur={e => (e.target.style.borderColor = 'rgba(108,99,255,0.18)')} />
                      <button onClick={addTag} style={{
                        padding: '0 14px', background: 'rgba(108,99,255,0.1)',
                        border: '1px solid rgba(108,99,255,0.2)', borderRadius: 3,
                        color: '#b06eff', fontSize: 11, cursor: 'pointer', whiteSpace: 'nowrap',
                      }}>+ add</button>
                    </div>
                  </div>

                  {/* Language */}
                  <div>
                    <FieldLabel>Entry Point Language</FieldLabel>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 5 }}>
                      {(['py','sh','js','rs'] as Lang[]).map(l => (
                        <button key={l} onClick={() => up('lang', l)} style={{
                          padding: '10px 0', borderRadius: 3, cursor: 'pointer', transition: 'all 0.2s',
                          background: config.lang === l ? 'rgba(108,99,255,0.18)' : 'rgba(255,255,255,0.025)',
                          border: `1px solid ${config.lang === l ? 'rgba(108,99,255,0.48)' : 'rgba(108,99,255,0.1)'}`,
                          color: config.lang === l ? '#b06eff' : 'rgba(232,228,248,0.35)',
                          fontSize: 10, letterSpacing: '0.18em', textTransform: 'uppercase',
                        }}>
                          {LANG_LABELS[l]}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Channel */}
                  <div>
                    <FieldLabel>Channel — optional isolated sub-field</FieldLabel>
                    <input value={config.channel} onChange={e => up('channel', e.target.value)}
                      placeholder="leave empty for global field"
                      style={inputStyle}
                      onFocus={e => (e.target.style.borderColor = '#3dd9c8')}
                      onBlur={e => (e.target.style.borderColor = 'rgba(108,99,255,0.18)')} />
                    {config.channel && (
                      <div style={{ marginTop: 7, fontSize: 11, color: '#3dd9c8', fontFamily: "'JetBrains Mono',monospace" }}>
                        ◎ isolated to channel: "{config.channel}"
                      </div>
                    )}
                  </div>

                  {/* Shared files */}
                  <div>
                    <FieldLabel>Pre-populate shared/ with filenames</FieldLabel>
                    {config.sharedFiles.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 8 }}>
                        {config.sharedFiles.map(f => (
                          <Tag key={f} label={f} onRemove={() => up('sharedFiles', config.sharedFiles.filter(x => x !== f))} />
                        ))}
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input value={sharedInput} onChange={e => setSharedInput(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && addSharedFile()}
                        placeholder="demo.mp3, readme.md..."
                        style={{ ...inputStyle, fontSize: 12 }}
                        onFocus={e => (e.target.style.borderColor = '#6c63ff')}
                        onBlur={e => (e.target.style.borderColor = 'rgba(108,99,255,0.18)')} />
                      <button onClick={addSharedFile} style={{
                        padding: '0 14px', background: 'rgba(108,99,255,0.1)',
                        border: '1px solid rgba(108,99,255,0.2)', borderRadius: 3,
                        color: '#b06eff', fontSize: 11, cursor: 'pointer', whiteSpace: 'nowrap',
                      }}>+ add</button>
                    </div>
                  </div>

                  {/* Download */}
                  <button onClick={downloadZip} disabled={downloading} style={{
                    padding: '14px 0',
                    background: downloaded
                      ? 'rgba(74,222,128,0.12)'
                      : 'linear-gradient(135deg,rgba(108,99,255,0.22),rgba(176,110,255,0.22))',
                    border: `1px solid ${downloaded ? 'rgba(74,222,128,0.38)' : 'rgba(108,99,255,0.38)'}`,
                    borderRadius: 3,
                    color: downloaded ? '#4ade80' : '#b06eff',
                    fontSize: 11, letterSpacing: '0.28em', textTransform: 'uppercase',
                    cursor: downloading ? 'wait' : 'pointer', fontWeight: 600,
                    transition: 'all 0.3s',
                  }}>
                    {downloading ? 'Building zip...' : downloaded ? '✓ Downloaded!' : '↓ Download Node Folder (.zip)'}
                  </button>

                  <div style={{ fontSize: 10.5, color: 'rgba(232,228,248,0.25)', textAlign: 'center', lineHeight: 1.75 }}>
                    After downloading, run:<br />
                    <code style={{ color: '#3dd9c8', fontFamily: "'JetBrains Mono',monospace", fontSize: 10 }}>
                      pip install aura-protocol && aura join .
                    </code>
                  </div>
                </div>
              </div>

              {/* RIGHT — PREVIEWS */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <div className="reveal"><FolderTree config={config} /></div>

                {/* File tabs */}
                <div className="reveal" style={{ background: 'rgba(12,9,24,0.85)', border: '1px solid rgba(108,99,255,0.13)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ display: 'flex', borderBottom: '1px solid rgba(108,99,255,0.09)', background: 'rgba(108,99,255,0.04)' }}>
                    {([
                      { key: 'entry' as const, label: entryFile },
                      { key: 'meta'  as const, label: 'aura.meta' },
                      { key: 'readme' as const, label: 'README.md' },
                    ]).map(tab => (
                      <button key={tab.key} onClick={() => setActiveTab(tab.key)} style={{
                        padding: '10px 17px',
                        background: activeTab === tab.key ? 'rgba(108,99,255,0.1)' : 'none',
                        borderBottom: activeTab === tab.key ? '1px solid #6c63ff' : '1px solid transparent',
                        color: activeTab === tab.key ? '#b06eff' : 'rgba(232,228,248,0.3)',
                        fontSize: 11, fontFamily: "'JetBrains Mono', monospace",
                        cursor: 'pointer', transition: 'all 0.2s', border: 'none',
                        borderBottomStyle: 'solid',
                        borderBottomWidth: 1,
                        borderBottomColor: activeTab === tab.key ? '#6c63ff' : 'transparent',
                      }}>
                        {tab.label}
                      </button>
                    ))}
                  </div>
                  <div style={{ padding: 2 }}>
                    {activeTab === 'entry'  && <CodeBlock code={entryCode}       lang={LANG_LABELS[config.lang]} />}
                    {activeTab === 'meta'   && <CodeBlock code={metaCode}        lang="aura.meta" />}
                    {activeTab === 'readme' && <CodeBlock code={README_CONTENT}  lang="markdown" />}
                  </div>
                </div>

                {/* Aura fingerprint */}
                <div className="reveal" style={{
                  padding: '18px 20px', background: 'rgba(12,9,24,0.8)',
                  border: '1px solid rgba(61,217,200,0.13)', borderRadius: 4,
                }}>
                  <FieldLabel>Your aura fingerprint — what the field will see</FieldLabel>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                    {myAuraTags.length > 0
                      ? myAuraTags.map((t, i) => (
                          <span key={i} style={{
                            padding: '4px 10px', borderRadius: 2, fontSize: 10,
                            letterSpacing: '0.14em', color: '#3dd9c8',
                            background: 'rgba(61,217,200,0.07)',
                            border: '1px solid rgba(61,217,200,0.18)',
                          }}>{t}</span>
                        ))
                      : <span style={{ fontSize: 12, color: 'rgba(232,228,248,0.22)' }}>
                          Fill in your name and tags to build your aura fingerprint
                        </span>
                    }
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* LIVE FIELD CONNECTION */}
        <section style={{ padding: '96px 24px', maxWidth: 860, margin: '0 auto' }}>
          <div className="reveal" style={{ marginBottom: 38 }}>
            <SectionLabel>Live Field</SectionLabel>
            <h2 style={{ fontSize: 'clamp(26px,4.5vw,50px)', fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 10 }}>
              Connect your node
            </h2>
            <p style={{ fontSize: 13, color: 'rgba(232,228,248,0.42)', maxWidth: 520, lineHeight: 1.85 }}>
              Run <code style={{ color: '#3dd9c8', fontFamily: "'JetBrains Mono',monospace" }}>aura join ./your-node</code> and
              this panel connects live to the real field — showing your actual peers,
              real seek results, and files arriving in your <code style={{ color: '#3dd9c8', fontFamily: "'JetBrains Mono',monospace" }}>in/</code>.
            </p>
          </div>
          <div className="reveal"><FieldConnect /></div>
        </section>

        {/* PROTOCOL */}
        <section id="protocol" style={{
          padding: '96px 24px', borderTop: '1px solid rgba(108,99,255,0.09)',
          background: 'rgba(108,99,255,0.015)',
        }}>
          <div style={{ maxWidth: 860, margin: '0 auto' }}>
            <div className="reveal" style={{ marginBottom: 52 }}>
              <SectionLabel>Protocol v0.4</SectionLabel>
              <h2 style={{ fontSize: 'clamp(26px,4.5vw,50px)', fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 10 }}>
                How the field works
              </h2>
              <p style={{ fontSize: 13, color: 'rgba(232,228,248,0.42)', maxWidth: 480, lineHeight: 1.85 }}>
                UDP multicast. No server. Ed25519 signing. X25519 peer encryption.
                Every packet is signed. Every node is a sovereign.
              </p>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {[
                { n:'01', title:'Scaffold a node', cmd:'aura new ./my-node --lang py', color:'#6c63ff',
                  desc:'Creates in/, out/, shared/, private/, aura.meta, and your language entry point. Run this once per node. The node folder is the node — it can live anywhere on your filesystem.' },
                { n:'02', title:'Join the field', cmd:'aura join ./my-node', color:'#b06eff',
                  desc:'Generates Ed25519 signing keys and X25519 encryption keys in .aura/ (chmod 600). Broadcasts UDP multicast heartbeats on 239.77.77.77:7777. Starts the local HTTP API on 127.0.0.1:7778. The "Connect your node" panel above connects automatically.' },
                { n:'03', title:'Seek', cmd:'aura seek ./my-node "python data science"', color:'#3dd9c8',
                  desc:'Broadcasts MSG_SEEK across the multicast field. Every peer scores your query against their own tag map using semantic weighted matching. Peers scoring above 0.05 reply with MSG_RESONATE. Results are sorted by score.' },
                { n:'04', title:'Pull & Route', cmd:'aura pull ./my-node <node_id> analysis.csv', color:'#f0c060',
                  desc:'Pull copies a file from a peer\'s shared/ into your in/. Route sends a file to a peer\'s in/ — encrypted end-to-end with X25519 ECDH + ChaCha20-Poly1305. Files above 60 KB automatically switch to a direct TCP connection.' },
                { n:'05', title:'Talk', cmd:'aura talk ./my-node <node_id>', color:'#6c63ff',
                  desc:'Opens a persistent session. Each line is passed as AURA_QUERY to the peer\'s entry point via environment variable. The entry point\'s stdout becomes the reply. The entry point is any executable: Python, shell, Node, Rust — your logic.' },
                { n:'06', title:'WAN relay', cmd:'aura relay --port 7779', color:'#b06eff',
                  desc:'Deploy a relay on any public server. Nodes register with MSG_RELAY_REG and the relay forwards all field packets between peers in the same channel. The relay is stateless — it never decrypts or stores anything. Nodes reconnect automatically.' },
              ].map((s, i) => (
                <div key={i} className="reveal">
                  <ProtoStep {...s} />
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* CRYPTO */}
        <section style={{ padding: '96px 24px' }}>
          <div style={{ maxWidth: 1000, margin: '0 auto' }}>
            <div className="reveal" style={{ marginBottom: 48 }}>
              <SectionLabel>Cryptographic Identity — v0.4</SectionLabel>
              <h2 style={{ fontSize: 'clamp(26px,4.5vw,50px)', fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 12 }}>
                You are your keys.
              </h2>
              <p style={{ fontSize: 13, color: 'rgba(232,228,248,0.42)', maxWidth: 520, lineHeight: 1.85 }}>
                Your node_id is the SHA-256 hash of your Ed25519 public key.
                Every packet is signed. Every private file is encrypted for its recipient.
                Unsigned packets are silently dropped.
              </p>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(255px,1fr))', gap: 2 }}>
              {[
                { icon:'🔑', title:'Ed25519 Identity', color:'#6c63ff', items:[
                  'Private key stored in .aura/identity.key',
                  'Public key in .aura/aura.pub',
                  'node_id = SHA256(pub_key)[:16]',
                  'Every outbound packet is signed',
                  'Unsigned packets are rejected',
                ]},
                { icon:'🔐', title:'X25519 Encryption', color:'#3dd9c8', items:[
                  'Encryption key in .aura/encryption.key',
                  'Peers exchange X25519 public keys in heartbeats',
                  'ECDH → HKDF → ChaCha20-Poly1305',
                  'Private routes are end-to-end encrypted',
                  'Only the recipient can decrypt',
                ]},
                { icon:'📡', title:'Multicast Channels', color:'#b06eff', items:[
                  'Default: 239.77.77.77:7777 (global)',
                  'aura field --channel secret-project',
                  'Channel hash → unique multicast address',
                  'Nodes outside channel are invisible',
                  'Channels are fully isolated from each other',
                ]},
              ].map((card, i) => (
                <div key={i} className="reveal" style={{
                  padding: '26px 22px', background: `${card.color}07`,
                  border: `1px solid ${card.color}1f`, borderRadius: 4,
                }}>
                  <div style={{ fontSize: 26, marginBottom: 14 }}>{card.icon}</div>
                  <h3 style={{ fontSize: 14, fontWeight: 600, color: card.color, marginBottom: 14 }}>{card.title}</h3>
                  <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 7 }}>
                    {card.items.map((item, j) => (
                      <li key={j} style={{ fontSize: 12, color: 'rgba(232,228,248,0.45)', lineHeight: 1.7, display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                        <span style={{ color: card.color, flexShrink: 0, marginTop: 1 }}>→</span>{item}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* FOLDER ANATOMY */}
        <section style={{
          padding: '96px 24px',
          borderTop: '1px solid rgba(108,99,255,0.09)', borderBottom: '1px solid rgba(108,99,255,0.09)',
          background: 'rgba(108,99,255,0.015)',
        }}>
          <div style={{ maxWidth: 1000, margin: '0 auto' }}>
            <div className="reveal" style={{ marginBottom: 48 }}>
              <SectionLabel>Folder anatomy</SectionLabel>
              <h2 style={{ fontSize: 'clamp(26px,4.5vw,50px)', fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 12 }}>
                Every directory has a purpose.
              </h2>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(215px,1fr))', gap: 2 }}>
              {[
                { dir:'in/',       icon:'📥', color:'#3dd9c8', desc:'Files that arrived for you from peers. Shadow-routed files land here. Encrypted files are auto-decrypted with your X25519 key.' },
                { dir:'out/',      icon:'📤', color:'#f0c060', desc:'Files you\'re sending. The field watcher picks up new files and routes them to the most resonant peer automatically.' },
                { dir:'shared/',   icon:'🌐', color:'#b06eff', desc:'Permanently visible to the field. Anyone can seek it, ls it, and pull from it. This is your public output surface.' },
                { dir:'private/',  icon:'🔒', color:'rgba(232,228,248,0.25)', desc:'Never indexed, never routed, never read by the protocol. Lives only on your machine. Genuinely private.' },
                { dir:'.aura/',    icon:'🔑', color:'#6c63ff', desc:'Your cryptographic identity. Ed25519 + X25519 keys, field log, intelligence ledger. Auto-generated on first mount.' },
                { dir:'aura.meta', icon:'📋', color:'#3dd9c8', desc:'Plain text. name, description, tags. The field reads this to build your semantic fingerprint for seek matching.' },
              ].map((item, i) => (
                <div key={i} className="reveal" style={{
                  padding: '22px 18px', border: `1px solid ${item.color}1e`, borderRadius: 4,
                  transition: 'border-color 0.3s',
                }}
                  onMouseEnter={e => (e.currentTarget.style.borderColor = `${item.color}44`)}
                  onMouseLeave={e => (e.currentTarget.style.borderColor = `${item.color}1e`)}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                    <span style={{ fontSize: 18 }}>{item.icon}</span>
                    <code style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: item.color, fontWeight: 500 }}>{item.dir}</code>
                  </div>
                  <p style={{ fontSize: 12, color: 'rgba(232,228,248,0.42)', lineHeight: 1.85 }}>{item.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* QUICK START */}
        <section style={{ padding: '96px 24px', maxWidth: 860, margin: '0 auto' }}>
          <div className="reveal" style={{ marginBottom: 48 }}>
            <SectionLabel>Quick Start</SectionLabel>
            <h2 style={{ fontSize: 'clamp(26px,4.5vw,50px)', fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 12 }}>
              From zero to field in 60s.
            </h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {[
              { step:'1', title:'Install AURA',
                code:'pip install aura-protocol\n\n# or from source:\ngit clone https://github.com/aethyr-global/aura\ncd aura && pip install -e .' },
              { step:'2', title:'Build and download your node folder (above), then:',
                code:`unzip ${folderName || 'my-node'}.zip\ncd ${folderName || 'my-node'}` },
              { step:'3', title:'Join the field',
                code:'aura join .\n# Generates Ed25519 + X25519 keys\n# Announces your node · starts local API on :7778' },
              { step:'4', title:'Seek and connect',
                code:'aura seek . "python data music"\n\n# or use the API:\ncurl http://127.0.0.1:7778/peers\ncurl -X POST http://127.0.0.1:7778/seek \\\n  -d \'{"query": "music audio"}\'' },
            ].map((item, i) => (
              <div key={i} className="reveal" style={{ display: 'grid', gridTemplateColumns: '48px 1fr', gap: 0, alignItems: 'stretch' }}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <div style={{
                    width: 38, height: 38, borderRadius: '50%',
                    background: 'rgba(108,99,255,0.12)', border: '1px solid rgba(108,99,255,0.28)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: '#6c63ff', fontWeight: 500,
                  }}>{item.step}</div>
                  {i < 3 && <div style={{ width: 1, flex: 1, marginTop: 3, background: 'rgba(108,99,255,0.12)' }} />}
                </div>
                <div style={{ paddingLeft: 18, paddingBottom: 20 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#fff', margin: '9px 0 10px' }}>{item.title}</div>
                  <CodeBlock code={item.code} lang="bash" />
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* CTA */}
        <section style={{
          padding: '96px 24px', textAlign: 'center',
          borderTop: '1px solid rgba(108,99,255,0.09)',
          background: 'linear-gradient(180deg,transparent 0%,rgba(108,99,255,0.055) 50%,transparent 100%)',
          position: 'relative', overflow: 'hidden',
        }}>
          <div style={{
            position: 'absolute', inset: 0,
            background: 'radial-gradient(ellipse 50% 60% at 50% 50%,rgba(108,99,255,0.1) 0%,transparent 65%)',
            pointerEvents: 'none',
          }} />
          <div className="reveal" style={{ position: 'relative', zIndex: 1 }}>
            <SectionLabel>Ready?</SectionLabel>
            <h2 style={{ fontSize: 'clamp(38px,8vw,96px)', fontWeight: 700, lineHeight: 0.88, letterSpacing: '-0.02em', marginBottom: 22 }}>
              Your folder.<br />
              <span style={{ background: 'linear-gradient(90deg,#6c63ff,#b06eff,#3dd9c8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
                Your node.<br />Your aura.
              </span>
            </h2>
            <p style={{ fontSize: 14, color: 'rgba(232,228,248,0.42)', maxWidth: 440, margin: '0 auto 40px', lineHeight: 1.8 }}>
              No logins. No servers. No apps. Just you, your folder,
              and the field that finds you.
            </p>
            <button onClick={scrollToBuilder} style={{
              padding: '15px 40px',
              background: 'linear-gradient(135deg,#6c63ff,#b06eff)',
              border: 'none', borderRadius: 3,
              fontSize: 11, letterSpacing: '0.35em', textTransform: 'uppercase',
              color: '#fff', fontWeight: 700, cursor: 'pointer',
              boxShadow: '0 0 48px rgba(108,99,255,0.32)',
              transition: 'transform 0.2s, box-shadow 0.2s',
            }}
              onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 0 64px rgba(108,99,255,0.5)'; }}
              onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 0 48px rgba(108,99,255,0.32)'; }}>
              Build Your Node →
            </button>
          </div>
        </section>

        {/* FOOTER */}
        <footer style={{
          borderTop: '1px solid rgba(108,99,255,0.09)',
          padding: '36px 32px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          flexWrap: 'wrap', gap: 18,
          maxWidth: 1100, margin: '0 auto',
        }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 18, letterSpacing: '0.32em', color: '#fff' }}>
            A<span style={{ color: '#6c63ff' }}>U</span>RA
          </div>
          <div style={{ fontSize: 11, color: 'rgba(232,228,248,0.25)', textAlign: 'center', lineHeight: 1.75 }}>
            Part of the GIGA package · NOT Money runs on AYR<br />
            <span style={{ color: '#6c63ff' }}>aethyr-global.com</span>
          </div>
          <a href="https://github.com/aethyr-global/aura"
            target="_blank" rel="noopener noreferrer"
            style={{
              fontSize: 11, letterSpacing: '0.2em', color: '#3dd9c8',
              textDecoration: 'none', textTransform: 'uppercase',
              borderBottom: '1px solid rgba(61,217,200,0.28)', paddingBottom: 2,
            }}>
            github/aethyr-global/aura ↗
          </a>
        </footer>
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap');
        *, *::before, *::after { box-sizing: border-box; }
        body { margin: 0; background: #06040f; }
        input, textarea, button { font-family: 'Space Grotesk', sans-serif; }
        @keyframes pulse-dot {
          0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(61,217,200,.4)}
          50%{opacity:.7;box-shadow:0 0 0 5px rgba(61,217,200,0)}
        }
        @keyframes ticker {
          from{transform:translateX(0)} to{transform:translateX(-50%)}
        }
        @keyframes slide-in {
          from{opacity:0;transform:translateX(-8px)} to{opacity:1;transform:translateX(0)}
        }
      `}</style>
    </>
  );
}
