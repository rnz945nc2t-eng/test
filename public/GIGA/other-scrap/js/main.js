// --- View Switcher ---
function clearAllViews() {
    // 1. Safe Stop: Check if functions exist before calling to prevent crash
    if (typeof window.stop3DAnimation === 'function') window.stop3DAnimation();
    if (typeof window.stopGIPPCAnimation === 'function') window.stopGIPPCAnimation();

    // 2. Hide All Containers
    const ids = [
        'pdfFrame', 
        'licensing-container', 
        'three-canvas-container', 
        'gippc-container',     // CORRECTED: Matches HTML ID
        'econ-sim-container'
    ];
    
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    // 3. Reset Nav
    document.querySelectorAll('.doc-nav-item').forEach(el => el.classList.remove('active'));
}

function openLicensing() {
    clearAllViews();
    document.getElementById('licensing-container').classList.remove('hidden');
    document.getElementById('currentDocTitle').innerText = "SIGN AND DOWNLOAD LICENCE";
    const status = document.getElementById('viewStatus');
    status.innerText = "AWAITING SIGNATURE";
    status.classList.add('text-red-500', 'animate-pulse');
    document.getElementById('nav-license').classList.add('active');
    
    if (typeof initSignaturePad === 'function') initSignaturePad();
}

function loadPdf(fileName, id) {
    clearAllViews();
    const frame = document.getElementById('pdfFrame');
    frame.classList.remove('hidden');
    frame.src = fileName;
    
    document.getElementById('currentDocTitle').innerText = fileName.toUpperCase();
    const status = document.getElementById('viewStatus');
    status.innerText = "SECURE STREAM ACTIVE";
    status.classList.remove('text-red-500', 'animate-pulse');
    
    document.getElementById(`nav-${id}`).classList.add('active');
}

function start3DSim() {
    clearAllViews();
    const container = document.getElementById('three-canvas-container');
    container.classList.remove('hidden');
    
    document.getElementById('currentDocTitle').innerText = "LIVE 3D SIMULATION - ORBITAL CASCADE";
    const status = document.getElementById('viewStatus');
    status.innerText = "PHYSICS ENGINE ACTIVE";
    status.classList.remove('text-red-500', 'animate-pulse');
    
    document.getElementById('nav-sim').classList.add('active');
    
    // START 3D
    if (typeof window.init3D === 'function') window.init3D();
    if (typeof window.animate3D === 'function') window.animate3D();
}

function startGIPPC() {
    clearAllViews();
    // CORRECTED: Matches HTML ID
    const container = document.getElementById('gippc-container');
    container.classList.remove('hidden');
    
    document.getElementById('currentDocTitle').innerText = "GIPPC SIMULATION // INTEGRATED CORE";
    const status = document.getElementById('viewStatus');
    status.innerText = "QUANTUM FLUX STABLE";
    status.classList.remove('text-red-500', 'animate-pulse');
    
    document.getElementById('nav-sim-gippc').classList.add('active');
    
    // START GIPPC - Use window. to access global functions safely
    if (typeof window.resizeGIPPC === 'function') window.resizeGIPPC();
    if (typeof window.animateGIPPC === 'function') window.animateGIPPC();
}

function startEconSim() {
    clearAllViews();
    document.getElementById('econ-sim-container').classList.remove('hidden');
    
    document.getElementById('currentDocTitle').innerText = "GIPPC ECONOMIC PROJECTIONS // 2026-2046";
    const status = document.getElementById('viewStatus');
    status.innerText = "MARKET SIMULATION ACTIVE";
    status.classList.remove('text-red-500', 'animate-pulse');
    
    document.getElementById('nav-econ-sim').classList.add('active');
    
    if (!window.econSimInitialized && typeof initEconSim === 'function') {
        initEconSim();
        window.econSimInitialized = true;
    }
}

// Global Listeners
window.addEventListener('resize', () => {
    // Only resize active views
    const threeC = document.getElementById('three-canvas-container');
    if (threeC && !threeC.classList.contains('hidden')) {
        if(typeof window.resize3D === 'function') window.resize3D();
    }
    
    // CORRECTED: Matches HTML ID
    const gippcC = document.getElementById('gippc-container');
    if (gippcC && !gippcC.classList.contains('hidden')) {
        if(typeof window.resizeGIPPC === 'function') window.resizeGIPPC();
    }
    
    if (typeof initSignaturePad === 'function') initSignaturePad();
});

window.addEventListener('load', () => {
    if (typeof initSignaturePad === 'function') initSignaturePad();
});
