let scene, camera, renderer, stages = [];
window.isThrottling = false;
window.isLoading = false;
let rpm = 0;
let animationFrameId3D;

// Attached to window explicitly
window.init3D = function() {
    const container = document.getElementById('three-canvas-container');
    // Safety check
    if (!container || renderer) return;
    
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(75, container.clientWidth / container.clientHeight, 0.1, 1000);
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);
    const light = new THREE.PointLight(0xD4AF37, 2, 50);
    light.position.set(5, 5, 5);
    scene.add(light, new THREE.AmbientLight(0x404040, 2));
    const configs = [
        { color: 0x3b82f6, x: -3, r: 0.6, m: 1.0 }, { color: 0xf97316, x: -1, r: 0.8, m: 0.5 },
        { color: 0xeab308, x: 1, r: 1.0, m: 0.2 }, { color: 0x22c55e, x: 3, r: 1.2, m: 0.05 }
    ];
    configs.forEach(cfg => {
        const group = new THREE.Group(); group.position.x = cfg.x;
        const h = new THREE.Mesh(new THREE.CylinderGeometry(cfg.r, cfg.r, 1.5, 16), 
            new THREE.MeshPhongMaterial({ color: cfg.color, transparent: true, opacity: 0.1, wireframe: true }));
        h.rotation.z = Math.PI / 2; group.add(h);
        const rollers = new THREE.Group();
        const arm = new THREE.Mesh(new THREE.BoxGeometry(0.05, cfg.r * 1.6, 0.05), new THREE.MeshPhongMaterial({ color: 0x888888 }));
        const r1 = new THREE.Mesh(new THREE.SphereGeometry(0.15), new THREE.MeshPhongMaterial({ color: 0xffffff }));
        r1.position.y = cfg.r * 0.8; 
        const r2 = r1.clone(); r2.position.y = -cfg.r * 0.8;
        rollers.add(arm, r1, r2); group.add(rollers);
        scene.add(group); stages.push({ rollers, cfg });
    });
    camera.position.set(0, 2, 6); camera.lookAt(0, 0, 0);
}

// Attached to window explicitly
window.animate3D = function() {
    animationFrameId3D = requestAnimationFrame(window.animate3D);
    if (window.isThrottling) rpm = Math.min(500, rpm + 2); else rpm = Math.max(0, rpm - 1);
    stages.forEach((s, i) => {
        let sRpm = rpm * s.cfg.m; if (window.isLoading && i > 1) sRpm *= 0.2;
        s.rollers.rotation.x += sRpm * 0.01;
    });
    if(renderer) renderer.render(scene, camera);
}

// Attached to window explicitly
window.stop3DAnimation = function() {
    if (animationFrameId3D) cancelAnimationFrame(animationFrameId3D);
}

// Attached to window explicitly
window.resize3D = function() {
    const container = document.getElementById('three-canvas-container');
    if (renderer && container) {
        camera.aspect = container.clientWidth / container.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(container.clientWidth, container.clientHeight);
    }
}
