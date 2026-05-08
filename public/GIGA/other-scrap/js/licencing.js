let sigCanvas, sigCtx, isDrawing = false;

function initSignaturePad() {
    sigCanvas = document.getElementById('sigCanvas');
    if(!sigCanvas) return;
    
    // Make canvas full width of parent
    sigCanvas.width = sigCanvas.parentElement.offsetWidth;
    
    sigCtx = sigCanvas.getContext('2d');
    sigCtx.strokeStyle = "#D4AF37";
    sigCtx.lineWidth = 3;
    sigCtx.lineCap = "round";

    sigCanvas.addEventListener('mousedown', startDraw);
    sigCanvas.addEventListener('mousemove', draw);
    sigCanvas.addEventListener('mouseup', stopDraw);
    sigCanvas.addEventListener('mouseout', stopDraw);
    
    // Touch support
    sigCanvas.addEventListener('touchstart', (e) => {
        e.preventDefault();
        const touch = e.touches[0];
        const mouseEvent = new MouseEvent("mousedown", {
            clientX: touch.clientX, clientY: touch.clientY
        });
        sigCanvas.dispatchEvent(mouseEvent);
    });
    sigCanvas.addEventListener('touchend', () => {
        const mouseEvent = new MouseEvent("mouseup", {});
        sigCanvas.dispatchEvent(mouseEvent);
    });
    sigCanvas.addEventListener('touchmove', (e) => {
        e.preventDefault();
        const touch = e.touches[0];
        const mouseEvent = new MouseEvent("mousemove", {
            clientX: touch.clientX, clientY: touch.clientY
        });
        sigCanvas.dispatchEvent(mouseEvent);
    });
}

function getPos(e) {
    const rect = sigCanvas.getBoundingClientRect();
    return {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
    };
}

function startDraw(e) {
    isDrawing = true;
    const pos = getPos(e);
    sigCtx.beginPath();
    sigCtx.moveTo(pos.x, pos.y);
}

function draw(e) {
    if (!isDrawing) return;
    const pos = getPos(e);
    sigCtx.lineTo(pos.x, pos.y);
    sigCtx.stroke();
}

function stopDraw() { isDrawing = false; }
function clearSignature() { sigCtx.clearRect(0, 0, sigCanvas.width, sigCanvas.height); }

async function submitContract() {
    const btn = document.getElementById('signBtn');
    const status = document.getElementById('formStatus');
    btn.disabled = true;
    btn.innerText = "PROCESSING ENCRYPTION & UPLOADING...";

    const name = document.getElementById('signerName').value;
    const email = document.getElementById('signerEmail').value;
    const usage = document.getElementById('usageType').value;
    const revenue = document.getElementById('revenueProj').value;
    const signatureData = sigCanvas.toDataURL();

    // Legal Logic
    let royaltyRate = "10%";
    if(usage === 'CORE') royaltyRate = "15%";
    if(usage === 'RND') royaltyRate = "0% (Evaluation Only)";

    const contractData = {
        name, email, usage, revenue, royaltyRate,
        timestamp: new Date().toISOString(),
        signature: signatureData
    };

    // 1. Send to Cloudflare Worker
    try {
        await fetch('https://aethyr.aethyr-one.workers.dev', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(contractData)
        });
        status.innerText = "DATA SECURED IN AETHYR REGISTRY.";
    } catch (err) {
        console.warn("Network Warning: Offline signing mode activated.");
        status.innerText = "OFFLINE MODE: LOCAL CONTRACT GENERATED.";
    }

    // 2. Generate PDF Client-Side
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF();
    const dateStr = new Date().toLocaleString();
    const refID = Math.random().toString(36).substr(2, 9).toUpperCase();

    // Title
    doc.setFont("times", "bold");
    doc.setFontSize(16);
    doc.text("INTELLECTUAL PROPERTY LICENSING AGREEMENT", 105, 20, null, null, "center");
    
    doc.setFontSize(9);
    doc.setFont("times", "normal");
    doc.text(`Reference ID: ${refID}`, 105, 26, null, null, "center");
    doc.text(`Executed Date: ${dateStr}`, 105, 30, null, null, "center");

    // Line separation
    doc.setLineWidth(0.5);
    doc.line(20, 32, 190, 32);

    let yPos = 40;
    const leftMargin = 20;
    const lineHeight = 5;
    const maxWidth = 170;

    function addHeader(text) {
        doc.setFont("times", "bold");
        doc.setFontSize(11);
        doc.text(text, leftMargin, yPos);
        yPos += lineHeight + 2;
        doc.setFont("times", "normal");
        doc.setFontSize(9);
    }

    function addPara(text) {
        const splitText = doc.splitTextToSize(text, maxWidth);
        doc.text(splitText, leftMargin, yPos);
        yPos += (splitText.length * lineHeight) + 4;
    }

    // 1. Parties
    addHeader("1. PARTIES TO THE AGREEMENT");
    addPara(`This Agreement is made between Miloš M. Ilić, residing in the Republic of Serbia (hereinafter "Licensor" or "Author"), and ${name} (contact: ${email}), (hereinafter "Licensee").`);

    // 2. Definitions & Subject Matter
    addHeader("2. DEFINITIONS & SUBJECT MATTER");
    addPara(`"IP Assets" refers collectively to the proprietary technical designs, conceptual frameworks, schematic data, and intellectual property assets hosted on the domain 'aethyr-global.com'. These assets are the exclusive creation and property of Miloš M. Ilić.`);
    addPara(`Specific assets covered include, but are not limited to, the 'HST' (Hyper-Spatial Transport) architecture, 'ORRT' specifications, and related advanced physics models designed by the Author.`);

    // 3. Grant of License
    addHeader("3. GRANT OF LICENSE");
    addPara(`Subject to the terms and conditions of this Agreement, Licensor hereby grants to Licensee a limited, non-exclusive, non-transferable, revocable license to use the IP Assets solely for the purpose of: ${usage === 'CORE' ? 'CORE INFRASTRUCTURE DEVELOPMENT & KEY INVENTION UTILIZATION' : 'AUXILIARY IMPLEMENTATION & SUPPORTING SYSTEMS'}.`);
    addPara(`This license does not convey any rights of ownership or title in the IP Assets to the Licensee.`);

    // 4. Royalties
    addHeader("4. ROYALTIES & COMPENSATION");
    addPara(`In consideration for the rights granted herein, Licensee agrees to pay Licensor a royalty fee of ${royaltyRate} of Gross Revenue generated from any product, service, or derivative work utilizing the IP Assets.`);
    addPara(`Payments shall be made quarterly within thirty (30) days of the quarter's end. Licensee shall provide a written report detailing the calculation of royalties due.`);

    // 5. Term & Termination
    addHeader("5. TERM AND TERMINATION");
    addPara(`This Agreement is effective as of the date of execution and shall remain in force unless terminated by either party with 90 days written notice. Licensor reserves the right to terminate this agreement immediately upon any breach of the terms herein by Licensee.`);

    // 6. Confidentiality
    addHeader("6. CONFIDENTIALITY");
    addPara(`Licensee agrees to maintain the confidentiality of any non-public technical data provided by Licensor. Reverse engineering or unauthorized distribution of the IP Assets is strictly prohibited.`);

    // 7. Disclaimer
    addHeader("7. DISCLAIMER OF WARRANTY");
    addPara(`THE IP ASSETS ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. LICENSOR SHALL NOT BE LIABLE FOR ANY DAMAGES ARISING OUT OF THE USE OR INABILITY TO USE THE IP ASSETS.`);

    // 8. Governing Law
    addHeader("8. GOVERNING LAW");
    addPara(`This Agreement shall be governed by and construed in accordance with the laws of the Republic of Serbia, without regard to its conflict of laws principles. Any disputes arising hereunder shall be subject to the exclusive jurisdiction of the courts located in Belgrade, Serbia.`);

    // Signature
    yPos += 10;
    doc.setFont("times", "bold");
    doc.text("IN WITNESS WHEREOF, the Licensee has executed this Agreement electronically.", leftMargin, yPos);
    
    yPos += 10;
    doc.addImage(signatureData, 'PNG', leftMargin, yPos, 60, 20);
    
    yPos += 25;
    doc.setFontSize(8);
    doc.setFont("times", "italic");
    doc.text(`Digitally Signed by: ${name}`, leftMargin, yPos);
    doc.text(`Timestamp: ${dateStr}`, leftMargin, yPos + 4);
    doc.text(`Digital Fingerprint: ${refID}`, leftMargin, yPos + 8);

    doc.save(`Aethyr_License_${name.replace(/\s/g, '_')}.pdf`);

    setTimeout(() => {
        btn.innerText = "ACCESS GRANTED - DOWNLOADING ASSETS";
        setTimeout(() => {
            loadPdf('Aethyr_HST.pdf', 'hst'); // Auto-switch to first doc
        }, 1500);
    }, 1000);
}