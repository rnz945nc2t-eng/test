import React, { useState, useEffect, useRef } from 'react';
import { Cpu, Zap, Layers, Send, Shield, Activity, Info, Globe } from 'lucide-react';

const App: React.FC = () => {
  const [messages, setMessages] = useState<{role: 'user' | 'io', content: string, status?: string}[]>([
    { role: 'io', content: 'Io Crystalline interface online. HST v8.1 modules active. Pell-Lucas temporal spine stabilized. How may I assist your inquiry beyond the horizon?' }
  ]);
  const [input, setInput] = useState('');
  const [isThinking, setIsThinking] = useState(false);
  const [stats] = useState({
    speedup: '943x',
    latency: '0.0006s',
    context: '∞',
    efficiency: '99.9%'
  });

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isThinking]);

  const handleSend = () => {
    if (!input.trim() || isThinking) return;

    const userMsg = input.trim();
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setInput('');
    setIsThinking(true);

    // Simulate Io thinking process
    setTimeout(() => {
      setMessages(prev => [...prev, {
        role: 'io',
        content: `Analyzing "${userMsg}" through hyperbolic Poincaré embeddings... Inference stabilized via Closed IF Set caching.`,
        status: 'verified'
      }]);
      setIsThinking(false);
    }, 1500);
  };

  return (
    <div className="min-h-screen bg-[#050608] text-[#f0f2f8] font-sans selection:bg-[#4f8aff]/30 flex flex-col">
      {/* Header */}
      <header className="h-16 border-b border-white/10 flex items-center justify-between px-6 bg-[#050608]/80 backdrop-blur-md sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-gradient-to-br from-[#4f8aff] to-[#2dd4bf] rounded-lg flex items-center justify-center font-bold text-sm text-white shadow-[0_0_15px_rgba(79,138,255,0.3)]">
            Io
          </div>
          <h1 className="syne font-extrabold text-xl tracking-tight">Io AI</h1>
          <div className="px-2 py-0.5 rounded-full border border-[#2dd4bf]/30 bg-[#2dd4bf]/10 text-[#2dd4bf] text-[10px] mono uppercase tracking-wider font-bold">
            v8.1 Crystalline
          </div>
        </div>
        <nav className="hidden md:flex items-center gap-6">
          <a href="#" className="text-sm text-[#8890a8] hover:text-white transition-colors">Architecture</a>
          <a href="#" className="text-sm text-[#8890a8] hover:text-white transition-colors">Lattice</a>
          <div className="w-px h-4 bg-white/10" />
          <button className="flex items-center gap-2 px-4 py-1.5 bg-[#4f8aff] hover:bg-[#4f8aff]/90 text-white rounded-lg text-sm font-medium transition-all shadow-[0_0_20px_rgba(79,138,255,0.2)]">
            <Globe size={14} />
            Network
          </button>
        </nav>
      </header>

      <main className="flex-1 flex flex-col md:flex-row overflow-hidden">
        {/* Sidebar - Stats */}
        <aside className="w-full md:w-64 border-r border-white/5 bg-[#090b10] p-6 flex flex-col gap-6 overflow-y-auto">
          <div>
            <div className="text-[10px] mono text-[#5a6070] uppercase tracking-widest mb-4">Core Metrics</div>
            <div className="grid grid-cols-2 md:grid-cols-1 gap-4">
              <StatCard icon={<Zap size={14} />} label="Speedup" value={stats.speedup} color="#2dd4bf" />
              <StatCard icon={<Activity size={14} />} label="Latency" value={stats.latency} color="#4f8aff" />
              <StatCard icon={<Layers size={14} />} label="Context" value={stats.context} color="#a78bfa" />
              <StatCard icon={<Shield size={14} />} label="Cache" value={stats.efficiency} color="#f0c96e" />
            </div>
          </div>

          <div className="mt-auto">
            <div className="p-4 rounded-xl bg-white/5 border border-white/5">
              <div className="flex items-center gap-2 mb-2">
                <Info size={14} className="text-[#4f8aff]" />
                <span className="text-xs font-semibold syne">Module Status</span>
              </div>
              <ul className="space-y-2">
                <ModuleItem label="Pell-Lucas" active />
                <ModuleItem label="Diamond Mixer" active />
                <ModuleItem label="Closed IF Set" active />
                <ModuleItem label="Hebbian Weight" active />
              </ul>
            </div>
          </div>
        </aside>

        {/* Chat Area */}
        <section className="flex-1 flex flex-col bg-[#050608] relative">
          {/* Messages */}
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto p-6 md:p-10 space-y-8 io-scrollbar"
          >
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] md:max-w-[70%] ${msg.role === 'user' ? 'bg-[#171b28] border-white/10' : 'bg-transparent'} p-4 rounded-2xl border transition-all`}>
                  {msg.role === 'io' && (
                    <div className="flex items-center gap-2 mb-3">
                      <div className="w-5 h-5 bg-[#4f8aff]/20 rounded flex items-center justify-center">
                        <Cpu size={12} className="text-[#4f8aff]" />
                      </div>
                      <span className="text-[10px] mono text-[#4f8aff] uppercase tracking-widest font-bold">Io Intelligence</span>
                      {msg.status === 'verified' && (
                        <span className="text-[8px] px-1.5 py-0.5 rounded bg-[#2dd4bf]/10 text-[#2dd4bf] border border-[#2dd4bf]/20">VERIFIED</span>
                      )}
                    </div>
                  )}
                  <p className={`text-sm md:text-base leading-relaxed ${msg.role === 'user' ? 'text-[#f0f2f8]' : 'text-[#8890a8]'} font-light`}>
                    {msg.content}
                  </p>
                </div>
              </div>
            ))}
            {isThinking && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 p-4">
                  <div className="flex gap-1">
                    <div className="w-1.5 h-1.5 bg-[#4f8aff] rounded-full animate-bounce [animation-delay:-0.3s]"></div>
                    <div className="w-1.5 h-1.5 bg-[#2dd4bf] rounded-full animate-bounce [animation-delay:-0.15s]"></div>
                    <div className="w-1.5 h-1.5 bg-[#a78bfa] rounded-full animate-bounce"></div>
                  </div>
                  <span className="text-[10px] mono text-[#5a6070] uppercase tracking-widest ml-2">Crystalline Processing...</span>
                </div>
              </div>
            )}
          </div>

          {/* Input Area */}
          <div className="p-6 bg-gradient-to-t from-[#050608] via-[#050608] to-transparent">
            <div className="max-w-4xl mx-auto relative">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder="Query Io's crystalline core..."
                className="w-full bg-[#111420] border border-white/10 rounded-2xl py-4 pl-6 pr-14 text-sm focus:outline-none focus:border-[#4f8aff]/50 focus:ring-1 focus:ring-[#4f8aff]/20 transition-all placeholder:text-[#5a6070]"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || isThinking}
                className="absolute right-3 top-1/2 -translate-y-1/2 w-10 h-10 bg-[#4f8aff] hover:bg-[#4f8aff]/90 disabled:bg-[#111420] disabled:text-[#5a6070] rounded-xl flex items-center justify-center transition-all shadow-[0_0_15px_rgba(79,138,255,0.2)]"
              >
                <Send size={18} />
              </button>
            </div>
            <div className="mt-4 flex justify-center gap-6">
              <div className="flex items-center gap-2 text-[10px] mono text-[#5a6070]">
                <div className="w-1.5 h-1.5 rounded-full bg-[#2dd4bf]"></div>
                HST PIPELINE: ACTIVE
              </div>
              <div className="flex items-center gap-2 text-[10px] mono text-[#5a6070]">
                <div className="w-1.5 h-1.5 rounded-full bg-[#4f8aff]"></div>
                943X DENY CACHE: ENABLED
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
};

const StatCard = ({ icon, label, value, color }: any) => (
  <div className="p-3 rounded-xl bg-white/[0.03] border border-white/5 hover:border-white/10 transition-colors">
    <div className="flex items-center gap-2 mb-1 opacity-50">
      <span style={{ color }}>{icon}</span>
      <span className="text-[9px] mono uppercase tracking-wider">{label}</span>
    </div>
    <div className="text-xl syne font-bold" style={{ color: value === '∞' ? '#a78bfa' : 'white' }}>{value}</div>
  </div>
);

const ModuleItem = ({ label, active }: any) => (
  <li className="flex items-center justify-between">
    <span className="text-[10px] mono text-[#8890a8]">{label}</span>
    <div className={`w-1.5 h-1.5 rounded-full ${active ? 'bg-[#2dd4bf] shadow-[0_0_5px_#2dd4bf]' : 'bg-white/10'}`}></div>
  </li>
);

export default App;
