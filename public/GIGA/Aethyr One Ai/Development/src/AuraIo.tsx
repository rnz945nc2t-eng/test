import React, { useState, useEffect, useRef } from 'react';

interface Message {
  id: string;
  sender: 'SYSTEM' | 'AURA_OS' | 'USER' | 'DEEPSEEK_AI' | 'NODE';
  text: string;
  timestamp: number;
}

interface Node {
  id: string;
  name: string;
  content: string;
  structure: string;
  resonance: string;
}

const AuraIo: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([
    { id: '1', sender: 'AURA_OS', text: 'field is empty. where are your files?', timestamp: Date.now() }
  ]);
  const [inputValue, setInputValue] = useState('');
  const [nodes, setNodes] = useState<Node[]>([]);
  console.log('Nodes mounted:', nodes.length);
  const [status, setStatus] = useState({
    connected: 0,
    identity: 'ayr.6t20.8kq4',
    field: '5 nodes',
    deepseek: 'ONLINE'
  });
  const [uiConfig, setUiConfig] = useState({
    theme: 'dark',
    accent: '#2dd4bf', // Teal
    layout: 'mobile-workflow'
  });

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const addMessage = (sender: Message['sender'], text: string) => {
    setMessages(prev => [...prev, {
      id: Math.random().toString(36).substr(2, 9),
      sender,
      text,
      timestamp: Date.now()
    }]);
  };

  const handleCommand = (command: string) => {
    const cmd = command.toLowerCase().trim();
    addMessage('USER', command);

    // Simulate different responses based on the transcript
    setTimeout(() => {
      if (cmd.includes('aethyr-global.com')) {
        setNodes(prev => [...prev, {
          id: 'aethyr-global_com',
          name: 'aethyr-global_com',
          content: 'technical ip licensing; ready-to-build frameworks.',
          structure: 'external asset repository.',
          resonance: 'architectural foundation; proprietary infrastructure.'
        }]);
        addMessage('AURA_OS', 'node assembled: aethyr-global_com\ncontent: technical ip licensing; ready-to-build frameworks.\nstructure: external asset repository.\nresonance: architectural foundation; proprietary infrastructure.');
        setStatus(prev => ({ ...prev, connected: 1 }));
      } else if (cmd.includes('github.com/rnz945nc2t-eng/aura')) {
        addMessage('AURA_OS', 'node assembled: github_rnz945nc2t-eng_aura\ncontent: repository root; CHANGELOG.md; aura subdirectory.\nstructure: version-controlled source tree.\nresonance: identity kernel; system origin.');
      } else if (cmd.includes('deepseek-ai')) {
        addMessage('AURA_OS', 'node assembled: github_deepseek-ai\ncontent: large language model architectures; agentic frameworks; optimization scripts.\nstructure: organization repository cluster.\nresonance: high-order inference; cognitive logic; computational density.');
        addMessage('SYSTEM', 'field update: intelligence layer acquired. Logic from github_deepseek-ai can power the backend agent.');
        setStatus(prev => ({ ...prev, deepseek: 'ONLINE' }));
      } else if (cmd.includes('topics/messaging-app')) {
        addMessage('AURA_OS', 'node assembled: github_topics_messaging-app\ncontent: index of 311 repositories; engagement and automation tools.\nstructure: search metadata.\nresonance: high-density source pool.');
        addMessage('SYSTEM', 'candidate identified: dittofeed/dittofeed [marketing/transactional messaging].');
      } else if (cmd.includes('tinode/chat') || cmd.includes('u pick')) {
        addMessage('SYSTEM', 'selection: tinode/chat\nreason: extensible gRPC/Websocket messaging server; provides native logic for persistence and transport.');
        addMessage('AURA_OS', 'mounting: github.com/tinode/chat\nlogic mapping:\n- transport: tinode/server [go]\n- interface: tinode/webapp [react]\n- intelligence: deepseek-ai [cognitive layer]\n- kernel: aura [system orchestrator]');
        addMessage('SYSTEM', 'integration sequence initiated. assembling message routing to deepseek-ai inference bridge.');
      } else if (cmd.includes('comfy-mobile-ui')) {
        addMessage('AURA_OS', 'node assembled: github_jaeone94_comfy-mobile-ui\ncontent: mobile-optimized web interface; workflow-centric ui.\nstructure: react/vite framework; component-based layouts.\nresonance: fluid ergonomics; visual density; generative-ready.');
        setUiConfig(prev => ({ ...prev, accent: '#6c63ff', layout: 'comfy-mobile' }));
        addMessage('SYSTEM', 'interface switch complete. mapping comfy-mobile-ui components to tinode transport and deepseek-ai backend.');
      } else if (cmd === 'build a messaging app') {
        addMessage('AURA_OS', 'messaging app protocol pending source. specify component files or logic repositories.');
      } else if (cmd === 'do all what we can do') {
        addMessage('AURA_OS', 'field state: nodes detected. missing assets for messaging app: interface code, logic layer, communication protocol.');
      } else if (cmd === 'change interface' || cmd === 'refactor ui' || cmd === 'refactor_ui') {
        const colors = ['#6c63ff', '#3dd9c8', '#f0c060', '#b06eff', '#f87171'];
        const nextColor = colors[Math.floor(Math.random() * colors.length)];
        setUiConfig(prev => ({ ...prev, accent: nextColor }));
        addMessage('SYSTEM', `Interface refactor initiated. Resonance shifted to ${nextColor}. Mapping comfy-mobile-ui components to field logic.`);
      } else if (cmd === 'status') {
        addMessage('AURA_OS', `field status: ${status.connected} nodes connected. identity: ${status.identity}. intelligence: ${status.deepseek}.`);
      } else {
        addMessage('DEEPSEEK_AI', `[DEEPSEEK_LOG]: Processing "${command}"... Field integrity optimal. Architectural resonance detected.`);
      }
    }, 600);
  };

  return (
    <div style={{
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      background: '#050505',
      color: '#e0e0e0',
      fontFamily: "'JetBrains Mono', monospace",
      overflow: 'hidden'
    }}>
      {/* Header */}
      <header style={{
        padding: '16px',
        borderBottom: '1px solid #222',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: 'rgba(0,0,0,0.5)'
      }}>
        <div>
          <div style={{ fontSize: '10px', color: '#666', letterSpacing: '2px' }}>Aura Io</div>
          <div style={{ fontSize: '12px', fontWeight: 'bold' }}>{status.identity}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: '10px', color: '#666' }}>{status.connected} connected</div>
          <div style={{ fontSize: '10px', color: uiConfig.accent, fontWeight: 'bold' }}>DEEPSEEK: {status.deepseek}</div>
        </div>
      </header>

      {/* Message Stack */}
      <main
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '16px'
        }}>
        {messages.map(msg => (
          <div key={msg.id} style={{
            alignSelf: msg.sender === 'USER' ? 'flex-end' : 'flex-start',
            maxWidth: '85%',
            background: msg.sender === 'USER' ? '#1a1a1a' : '#0a0a0a',
            padding: '12px',
            borderRadius: '4px',
            border: `1px solid ${msg.sender === 'USER' ? '#333' : '#111'}`,
            boxShadow: msg.sender === 'DEEPSEEK_AI' ? `0 0 10px ${uiConfig.accent}22` : 'none'
          }}>
            <div style={{ whiteSpace: 'pre-wrap', fontSize: '13px', lineHeight: '1.6' }}>{msg.text}</div>
            <div style={{
              fontSize: '9px',
              color: '#555',
              marginTop: '8px',
              display: 'flex',
              justifyContent: 'space-between'
            }}>
              <span>{msg.sender}</span>
              <span>{new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
            </div>
          </div>
        ))}
      </main>

      {/* Workflow Tiles */}
      <div style={{
        padding: '8px',
        display: 'flex',
        gap: '8px',
        overflowX: 'auto',
        background: '#080808',
        borderTop: '1px solid #1a1a1a'
      }}>
        {['Generate_Logic', 'Refactor_UI', 'Sync_Tinode', 'Deploy_Pixels'].map(tile => (
          <button
            key={tile}
            onClick={() => handleCommand(tile)}
            style={{
              padding: '6px 12px',
              background: '#111',
              border: '1px solid #222',
              color: '#888',
              fontSize: '10px',
              borderRadius: '2px',
              whiteSpace: 'nowrap',
              cursor: 'pointer',
              textTransform: 'uppercase'
            }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = uiConfig.accent)}
            onMouseLeave={e => (e.currentTarget.style.borderColor = '#222')}
          >
            {tile}
          </button>
        ))}
      </div>

      {/* Input Buffer */}
      <footer style={{
        padding: '16px',
        background: '#000',
        borderTop: '1px solid #222'
      }}>
        <div style={{ display: 'flex', gap: '8px' }}>
          <input
            type="text"
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            onKeyPress={e => {
              if (e.key === 'Enter') {
                handleCommand(inputValue);
                setInputValue('');
              }
            }}
            placeholder="Execute command..."
            style={{
              flex: 1,
              background: 'transparent',
              border: '1px solid #333',
              padding: '10px',
              color: '#fff',
              fontSize: '13px',
              outline: 'none'
            }}
          />
          <button
            onClick={() => {
              handleCommand(inputValue);
              setInputValue('');
            }}
            style={{
              padding: '10px 20px',
              background: '#fff',
              color: '#000',
              border: 'none',
              fontWeight: 'bold',
              fontSize: '11px',
              textTransform: 'uppercase',
              cursor: 'pointer'
            }}>
            Transmit
          </button>
        </div>
      </footer>
    </div>
  );
};

export default AuraIo;
