// --- Constants ---
const G_COLORS = {
    gamma: '#d946ef',
    electron: '#06b6d4',
    positron: '#ef4444',
    bg_pulse: 'rgba(217, 70, 239, 0.5)',
    grid_dim: 'rgba(212, 175, 55, 0.1)',
    grid_bright: 'rgba(212, 175, 55, 0.3)'
};

// --- Globals ---
let gCanvas, gCtx;
let gWidth = 0, gHeight = 0;
let particles = [];
let totalStored = 0;
let totalOps = 0;
let gateMode = 'AND';
let animationFrameIdGIPPC;

// --- Particle Class ---
class Particle {
    constructor(w, h, type) {
        this.x = w * 0.1; 
        this.y = h * 0.5;
        this.type = type;
        this.vx = type === 'gamma' ? 12 : (Math.random() * 2 + 3);
        this.vy = type === 'gamma' ? 0 : (Math.random() - 0.5) * 3;
        this.active = true;
        this.inTrap = false;
        this.history = [];
        this.color = type === 'gamma' ? G_COLORS.gamma : (type === 'electron' ? G_COLORS.electron : G_COLORS.positron);
        this.size = type === 'gamma' ? 1.5 : 2.5;
    }

    update(w, h) {
        if (!this.active) return;
        
        if (this.inTrap) {
            const cx = w * 0.9, cy = h * 0.5;
            this.x = cx + Math.sin(Date.now() * 0.005 + this.vx) * 15;
            this.y = cy + Math.cos(Date.now() * 0.005 + this.vy) * 20;
            return;
        }

        const targetX = w * 0.25;
        if (this.type === 'gamma' && this.x >= targetX) {
             this.active = false;
             particles.push(new Particle(w, h, 'electron'));
             particles[particles.length-1].x = this.x; particles[particles.length-1].y = this.y;
             particles.push(new Particle(w, h, 'positron'));
             particles[particles.length-1].x = this.x; particles[particles.length-1].y = this.y;
             return;
        }

        if (this.type === 'electron') { this.vy += 0.5; this.vx *= 0.95; }
        if (this.type === 'positron') {
            if (this.x > w * 0.35 && this.x < w * 0.75) {
                const distY = (h * 0.5) - this.y;
                let force = distY * 0.05; 
                if (gateMode === 'OR') force *= 0.5;
                this.vy += force; this.vx += 0.1; totalOps += 0.02;
            }
        }

        this.x += this.vx; this.y += this.vy;
        this.history.push({x: this.x, y: this.y}); if (this.history.length > 10) this.history.shift();
        
        if (this.type === 'positron' && this.x > w * 0.85 && Math.abs(this.y - h*0.5) < 60) {
            this.inTrap = true; totalStored += 0.00005;
        }
        if (this.x > w || this.y < 0 || this.y > h) this.active = false;
    }

    draw(ctx) {
        if (!this.active) return;
        ctx.beginPath(); ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
        ctx.fillStyle = this.color; 
        ctx.shadowBlur = 10; ctx.shadowColor = this.color; ctx.fill(); ctx.shadowBlur = 0;
        
        if (this.history.length > 1 && !this.inTrap) {
            ctx.beginPath(); ctx.strokeStyle = this.color; ctx.lineWidth = 1;
            ctx.moveTo(this.history[0].x, this.history[0].y);
            for (let p of this.history) ctx.lineTo(p.x, p.y);
            ctx.stroke();
        }
    }
}

// --- Main Functions ---

// Attach to window to ensure main.js can see it
window.resizeGIPPC = function() {
    // CORRECTED IDs based on your HTML
    const container = document.getElementById('gippc-container');
    gCanvas = document.getElementById('gippc-canvas');
    
    if (gCanvas && container) {
        // If the container is visible (has width), set the canvas size
        if(container.clientWidth > 0) {
            gWidth = gCanvas.width = container.clientWidth;
            gHeight = gCanvas.height = container.clientHeight;
            gCtx = gCanvas.getContext('2d');
        }
    }
}

function drawSchematic(w, h) {
    if (!gCtx) return;
    gCtx.lineWidth = 1;
    gCtx.strokeStyle = G_COLORS.grid_dim; 
    gCtx.strokeRect(w * 0.05, h * 0.4, w * 0.05, h * 0.2); // Emitter
    gCtx.fillStyle = 'rgba(255,255,255,0.1)'; 
    gCtx.fillRect(w * 0.25, h * 0.2, 10, h * 0.6); // Splitter
    gCtx.strokeStyle = G_COLORS.grid_bright; gCtx.setLineDash([5, 5]); 
    gCtx.strokeRect(w * 0.35, h * 0.25, w * 0.4, h * 0.5); // Logic
    gCtx.setLineDash([]);
    gCtx.strokeStyle = G_COLORS.positron; 
    gCtx.strokeRect(w * 0.85, h * 0.35, 60, h * 0.3); // Trap
}

// Attach to window
window.animateGIPPC = function() {
    animationFrameIdGIPPC = requestAnimationFrame(window.animateGIPPC);
    
    // Auto-resize if context is missing or size is 0
    if (!gCtx || gWidth === 0) {
        window.resizeGIPPC();
        // If still 0, it means we are hidden, so stop drawing
        if (gWidth === 0) return;
    }
    
    gCtx.clearRect(0, 0, gWidth, gHeight);
    drawSchematic(gWidth, gHeight);
    
    if (Date.now() % 500 < 50) { 
        gCtx.fillStyle = G_COLORS.bg_pulse; 
        gCtx.fillRect(gWidth * 0.05 + 10, gHeight*0.48, gWidth*0.2 - 20, 4); 
    }

    if (Math.random() < 0.1) particles.push(new Particle(gWidth, gHeight, 'gamma'));
    
    gCtx.globalCompositeOperation = 'lighter';
    particles = particles.filter(p => p.active);
    particles.forEach(p => { p.update(gWidth, gHeight); p.draw(gCtx); });
    gCtx.globalCompositeOperation = 'source-over';

    const opsEl = document.getElementById('m-ops');
    const storEl = document.getElementById('m-storage');
    if (opsEl) opsEl.innerText = totalOps.toFixed(2) + " ZettaOps";
    if (storEl) storEl.innerText = totalStored.toFixed(4) + " ng";
}

window.stopGIPPCAnimation = function() {
    if (animationFrameIdGIPPC) cancelAnimationFrame(animationFrameIdGIPPC);
}

window.resetGIPPC = function() { particles = []; totalOps = 0; totalStored = 0; }
window.toggleGate = function() { 
    gateMode = gateMode === 'AND' ? 'OR' : 'AND'; 
    document.getElementById('gate-mode-disp').innerText = gateMode; 
}
