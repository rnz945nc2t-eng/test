import { useEffect } from 'react';

interface Particle {
  x: number; y: number;
  vx: number; vy: number;
  r: number;
  pulse: number;
  speed: number;
  color: string;
}

export function useParticleField(canvasId: string) {
  useEffect(() => {
    const canvas = document.getElementById(canvasId) as HTMLCanvasElement;
    if (!canvas) return;
    const ctx = canvas.getContext('2d')!;
    let W = 0, H = 0;
    let particles: Particle[] = [];
    const mouse = { x: -999, y: -999 };
    let raf = 0;

    const COLORS = ['#6c63ff', '#3dd9c8', '#b06eff', '#6c63ff'];

    function resize() {
      W = canvas.width  = window.innerWidth;
      H = canvas.height = window.innerHeight;
      init();
    }

    function init() {
      const count = Math.min(55, Math.floor(W * H / 18000));
      particles = Array.from({ length: count }, () => ({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.22,
        vy: (Math.random() - 0.5) * 0.22,
        r: Math.random() * 1.4 + 0.5,
        pulse: Math.random() * Math.PI * 2,
        speed: 0.007 + Math.random() * 0.01,
        color: COLORS[Math.floor(Math.random() * COLORS.length)],
      }));
    }

    function draw() {
      ctx.clearRect(0, 0, W, H);

      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const a = particles[i], b = particles[j];
          const dx = a.x - b.x, dy = a.y - b.y;
          const d = Math.sqrt(dx * dx + dy * dy);
          if (d < 150) {
            ctx.beginPath();
            ctx.strokeStyle = `rgba(108,99,255,${(1 - d / 150) * 0.1})`;
            ctx.lineWidth = 0.5;
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }

      particles.forEach(n => {
        n.pulse += n.speed;
        const glow = Math.sin(n.pulse) * 0.5 + 0.5;
        const r = n.r + glow * 1.1;

        const mdx = n.x - mouse.x, mdy = n.y - mouse.y;
        const md = Math.sqrt(mdx * mdx + mdy * mdy);
        if (md < 90) {
          n.vx += (mdx / md) * 0.28;
          n.vy += (mdy / md) * 0.28;
        }
        n.vx *= 0.985; n.vy *= 0.985;
        n.x += n.vx; n.y += n.vy;
        if (n.x < 0) n.x = W; if (n.x > W) n.x = 0;
        if (n.y < 0) n.y = H; if (n.y > H) n.y = 0;

        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        const alpha = Math.floor(glow * 60 + 55).toString(16).padStart(2, '0');
        ctx.fillStyle = n.color + alpha;
        ctx.fill();
      });

      raf = requestAnimationFrame(draw);
    }

    const onMove = (e: MouseEvent) => { mouse.x = e.clientX; mouse.y = e.clientY; };
    window.addEventListener('resize', resize);
    window.addEventListener('mousemove', onMove);
    resize();
    draw();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      window.removeEventListener('mousemove', onMove);
    };
  }, [canvasId]);
}
