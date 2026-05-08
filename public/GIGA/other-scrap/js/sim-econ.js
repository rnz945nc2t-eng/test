let revenueChart, antimatterChart;
const generations = [
    { name: 'Gen 1', years: [2026, 2027, 2028, 2029, 2030], positronRate: 1e12, computeScale: 1e12, antimatterYield: 1e-12, color: '#3b82f6' },
    { name: 'Gen 2', years: [2030, 2031, 2032, 2033, 2034, 2035], positronRate: 1e15, computeScale: 1e15, antimatterYield: 1e-9, color: '#8b5cf6' },
    { name: 'Gen 3', years: [2035, 2036, 2037, 2038, 2039, 2040], positronRate: 1e17, computeScale: 1e17, antimatterYield: 1e-6, color: '#ec4899' },
    { name: 'Gen 4', years: [2040, 2041, 2042, 2043], positronRate: 1e19, computeScale: 1e19, antimatterYield: 1e-3, color: '#f97316' },
    { name: 'Gen 5', years: [2043, 2044, 2045], positronRate: 1e20, computeScale: 1e20, antimatterYield: 0.1, color: '#eab308' },
    { name: 'Gen 6', years: [2045, 2046], positronRate: 1e21, computeScale: 1e21, antimatterYield: 10, color: '#22c55e' }
];

function formatCurrency(num) {
    if (num >= 1e12) return '$' + (num / 1e12).toFixed(2) + 'T';
    if (num >= 1e9) return '$' + (num / 1e9).toFixed(2) + 'B';
    if (num >= 1e6) return '$' + (num / 1e6).toFixed(2) + 'M';
    if (num >= 1e3) return '$' + (num / 1e3).toFixed(2) + 'K';
    return '$' + num.toFixed(2);
}
function formatNumber(num) {
    if (num >= 1e18) return (num / 1e18).toFixed(2) + 'E';
    if (num >= 1e15) return (num / 1e15).toFixed(2) + 'P';
    if (num >= 1e12) return (num / 1e12).toFixed(2) + 'T';
    return num.toFixed(2);
}

function runEconomicSimulation() {
    const bootstrap = parseFloat(document.getElementById('bootstrapInput').value);
    const captureEff = parseFloat(document.getElementById('captureInput').value) / 100;
    const strategy = document.getElementById('strategySelect').value;
    const years = []; for (let y = 2026; y <= 2046; y++) years.push(y);
    const computeRevenue = new Array(21).fill(0);
    const antimatterRevenue = new Array(21).fill(0);
    const antimatterProduction = new Array(21).fill(0);
    let totalComp = 0, totalAM = 0, totalGrams = 0, peakFLOPS = 0;
    const strategyMult = {
        balanced: { comp: 1.0, am: 1.0 },
        computation: { comp: 1.5, am: 0.7 },
        antimatter: { comp: 0.6, am: 1.8 },
        aggressive: { comp: 1.3, am: 1.3 }
    }[strategy];

    years.forEach((year, idx) => {
        let currentGen = generations[0];
        for (let gen of generations) { if (gen.years.includes(year)) { currentGen = gen; break; } }
        const genIndex = generations.indexOf(currentGen);
        const yearInGen = currentGen.years.indexOf(year);
        const bootstrapFactor = Math.pow(bootstrap, genIndex) * (1 + yearInGen * 0.1);
        const captureFactor = 0.2 + (captureEff - 0.2) * (genIndex / 6);
        const flops = currentGen.computeScale * bootstrapFactor;
        peakFLOPS = Math.max(peakFLOPS, flops);
        const gramsPerYear = currentGen.antimatterYield * bootstrapFactor * captureFactor;
        antimatterProduction[idx] = gramsPerYear;
        totalGrams += gramsPerYear;
        const pflops = flops / 1e15;
        const pricePerPFLOPS = 1e6 * Math.pow(0.85, idx);
        computeRevenue[idx] = pflops * pricePerPFLOPS * strategyMult.comp;
        totalComp += computeRevenue[idx];
        const marketMaturity = Math.min(idx / 15, 1);
        const basePrice = 62.5e12;
        const priceDecline = Math.pow(0.7, Math.log10(totalGrams + 1));
        const effectivePrice = basePrice * priceDecline * (0.0001 + marketMaturity * 0.01);
        antimatterRevenue[idx] = gramsPerYear * effectivePrice * strategyMult.am;
        totalAM += antimatterRevenue[idx];
    });

    const grandTotal = totalComp + totalAM;
    document.getElementById('compRevenue').innerText = formatCurrency(totalComp);
    document.getElementById('antimatterRevenue').innerText = formatCurrency(totalAM);
    document.getElementById('totalAntimatter').innerText = totalGrams.toExponential(2) + 'g';
    document.getElementById('peakCompute').innerText = formatNumber(peakFLOPS / 1e15) + 'FLOPS';
    document.getElementById('totalRevenue').innerText = 'Total: ' + formatCurrency(grandTotal);

    updateGenerationTimeline(bootstrap);
    updateRevenueChart(years, computeRevenue, antimatterRevenue);
    updateAntimatterChart(years, antimatterProduction);
}

function updateGenerationTimeline(bootstrap) {
    const timeline = document.getElementById('generationTimeline');
    timeline.innerHTML = '';
    generations.forEach((gen, idx) => {
        const div = document.createElement('div');
        div.className = 'flex items-center justify-between p-3 bg-black/40 rounded border border-gold/20 tech-font';
        div.innerHTML = `
            <div class="flex items-center gap-3">
                <span class="gen-badge" style="background-color: ${gen.color}20; color: ${gen.color}; border: 1px solid ${gen.color}">${gen.name}</span>
                <span class="text-[10px]">${gen.years[0]}-${gen.years[gen.years.length-1]}</span>
            </div>
            <div class="text-right"><div class="text-[9px] opacity-50">Compute</div><div class="text-[10px]">${formatNumber(gen.computeScale * Math.pow(bootstrap, idx))}FLOPS</div></div>
            <div class="text-right"><div class="text-[9px] opacity-50">Antimatter</div><div class="text-[10px]">${gen.antimatterYield.toExponential(1)}g/yr</div></div>`;
        timeline.appendChild(div);
    });
}

function updateRevenueChart(years, comp, am) {
    const ctx = document.getElementById('revenueChart').getContext('2d');
    if (revenueChart) revenueChart.destroy();
    revenueChart = new Chart(ctx, {
        type: 'line',
        data: { labels: years, datasets: [
            { label: 'Compute Rental', data: comp, borderColor: '#D4AF37', backgroundColor: 'rgba(212, 175, 55, 0.1)', fill: true, tension: 0.4 },
            { label: 'Antimatter Sales', data: am, borderColor: '#ef4444', backgroundColor: 'rgba(239, 68, 68, 0.1)', fill: true, tension: 0.4 }
        ]},
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top', labels: { color: '#94a3b8', font: { size: 10, family: 'Share Tech Mono' } } } }, scales: { y: { type: 'logarithmic', grid: { color: 'rgba(212, 175, 55, 0.1)' }, ticks: { color: '#94a3b8', font: { size: 9, family: 'Share Tech Mono' }, callback: function(value) { return formatCurrency(value); } } }, x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 9, family: 'Share Tech Mono' } } } } }
    });
}

function updateAntimatterChart(years, production) {
    const ctx = document.getElementById('antimatterChart').getContext('2d');
    if (antimatterChart) antimatterChart.destroy();
    antimatterChart = new Chart(ctx, {
        type: 'bar',
        data: { labels: years, datasets: [{ label: 'Annual Production', data: production, backgroundColor: 'rgba(239, 68, 68, 0.6)', borderColor: '#ef4444', borderWidth: 1 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { type: 'logarithmic', grid: { color: 'rgba(212, 175, 55, 0.1)' }, ticks: { color: '#94a3b8', font: { size: 9, family: 'Share Tech Mono' }, callback: function(value) { return value.toExponential(0) + ' g'; } } }, x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 9, family: 'Share Tech Mono' } } } } }
    });
}

function initEconSim() {
    const bootstrapInput = document.getElementById('bootstrapInput');
    const captureInput = document.getElementById('captureInput');
    if(bootstrapInput && captureInput) {
        bootstrapInput.oninput = () => { document.getElementById('bootstrapValue').innerText = bootstrapInput.value + 'x'; };
        captureInput.oninput = () => { document.getElementById('captureValue').innerText = captureInput.value + '%'; };
        document.getElementById('runEconSim').onclick = runEconomicSimulation;
        runEconomicSimulation();
    }
}