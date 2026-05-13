import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Cpu, Zap, Search } from 'lucide-react';

interface Message {
  id: string;
  text: string;
  sender: 'user' | 'io';
  sourcesCount?: number;
}

const App: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      text: "Io v2 Sacred Online. I can see beyond traditional autoregressive boundaries by fetching and patching real-time intelligence. How may I assist your inquiry?",
      sender: 'io'
    }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(scrollToBottom, [messages]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      text: input,
      sender: 'user'
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: input })
      });

      if (!response.ok) throw new Error('Failed to reach Io Engine');

      const data = await response.json();

      const ioMessage: Message = {
        id: (Date.now() + 1).toString(),
        text: data.response,
        sender: 'io',
        sourcesCount: data.sources_count
      };

      setMessages(prev => [...prev, ioMessage]);
    } catch (error) {
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        text: "Error: Could not establish resonance with Io Frankenstein Engine.",
        sender: 'io'
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-[#050608] text-[#f0f2f8] font-sans overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-white/5 bg-[#050608]/80 backdrop-blur-md sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-gradient-to-br from-[#4f8aff] to-[#2dd4bf] rounded-lg flex items-center justify-center shadow-[0_0_15px_rgba(79,138,255,0.3)]">
            <span className="text-white font-bold text-xs">Io</span>
          </div>
          <div>
            <h1 className="font-bold text-lg tracking-tight">Io v2 Sacred</h1>
            <p className="text-[10px] font-mono text-[#2dd4bf] uppercase tracking-widest opacity-70">Hierarchical Sequence Transformer · Crystalline</p>
          </div>
        </div>
        <div className="flex gap-4">
           <div className="flex items-center gap-2 px-3 py-1 bg-white/5 rounded-full border border-white/10">
             <div className="w-1.5 h-1.5 bg-[#2dd4bf] rounded-full animate-pulse shadow-[0_0_8px_#2dd4bf]"></div>
             <span className="text-[10px] font-mono text-white/50 uppercase">Neural Lattice Active</span>
           </div>
        </div>
      </header>

      {/* Main Chat Area */}
      <main className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6">
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] md:max-w-[70%] flex gap-4 ${m.sender === 'user' ? 'flex-row-reverse' : ''}`}>
              <div className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${m.sender === 'user' ? 'bg-[#4f8aff]/10 border border-[#4f8aff]/20' : 'bg-white/5 border border-white/10'}`}>
                {m.sender === 'user' ? <User size={16} className="text-[#4f8aff]" /> : <Bot size={16} className="text-[#2dd4bf]" />}
              </div>
              <div className={`space-y-2 ${m.sender === 'user' ? 'flex flex-col items-end' : 'flex flex-col items-start'}`}>
                <div className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                  m.sender === 'user'
                  ? 'bg-[#111420] border border-white/5 text-white shadow-lg'
                  : 'bg-[#0d1018] border border-white/5 text-[#f0f2f8]'
                }`}>
                  <div className="whitespace-pre-wrap">
                    {m.text}
                  </div>
                  {m.sourcesCount !== undefined && (
                    <div className="mt-4 pt-3 border-t border-white/5 flex items-center gap-3">
                       <div className="flex items-center gap-1.5 px-2 py-0.5 bg-white/5 rounded border border-white/5">
                          <Search size={10} className="text-[#2dd4bf]" />
                          <span className="text-[10px] font-mono text-[#2dd4bf]">{m.sourcesCount} Sources Fetched</span>
                       </div>
                       <div className="flex items-center gap-1.5 px-2 py-0.5 bg-white/5 rounded border border-white/5">
                          <Zap size={10} className="text-[#4f8aff]" />
                          <span className="text-[10px] font-mono text-[#4f8aff]">Patched via HST</span>
                       </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
             <div className="flex gap-4 max-w-[70%]">
                <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center">
                  <Cpu size={16} className="text-[#2dd4bf] animate-spin" />
                </div>
                <div className="px-4 py-3 rounded-2xl bg-[#0d1018] border border-white/5 flex gap-2">
                   <div className="w-1.5 h-1.5 bg-[#2dd4bf] rounded-full animate-bounce"></div>
                   <div className="w-1.5 h-1.5 bg-[#2dd4bf] rounded-full animate-bounce [animation-delay:-0.15s]"></div>
                   <div className="w-1.5 h-1.5 bg-[#2dd4bf] rounded-full animate-bounce [animation-delay:-0.3s]"></div>
                </div>
             </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </main>

      {/* Input Area */}
      <footer className="p-4 md:p-8 bg-gradient-to-t from-[#050608] to-transparent">
        <div className="max-w-4xl mx-auto relative group">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Input resonance inquiry..."
            className="w-full bg-[#111420] border border-white/10 rounded-2xl px-6 py-4 pr-16 text-sm focus:outline-none focus:border-[#4f8aff]/50 transition-all shadow-2xl placeholder:text-white/20"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="absolute right-3 top-1/2 -translate-y-1/2 w-10 h-10 bg-[#4f8aff] text-white rounded-xl flex items-center justify-center hover:bg-[#4f8aff]/80 disabled:opacity-50 disabled:hover:bg-[#4f8aff] transition-colors shadow-lg shadow-[#4f8aff]/20"
          >
            <Send size={18} />
          </button>
        </div>
        <p className="text-center text-[10px] text-white/20 mt-4 font-mono uppercase tracking-[0.2em]">
          Powered by Aethyr HST · Diamond Mixer Reversible Logic Enabled
        </p>
      </footer>
    </div>
  );
};

export default App;
