// Фон: многослойный перцептрон, через который бьют разряды-молнии по случайным траекториям.
(function () {
    const canvas = document.getElementById('neural-bg');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const CYAN = [0, 240, 255];
    const PINK = [255, 43, 214];
    const WHITE = [255, 255, 255];
    const MAX_BOLTS = 24;
    const BOLT_SPEED = 32;      // рёбер в секунду — разряд пробивает сеть за доли секунды
    const BOLT_LINGER = 0.45;   // сколько секунд молния мерцает после удара
    const BRANCH_CHANCE = 0.3;  // шанс боковой ветки на каждом нейроне
    const BOLT_JITTER = 0.015;   // разброс излома относительно длины связи

    let W = 0, H = 0, dpr = 1;
    let layers = [];   // [[node, …], …]
    let edges = [];    // все связи между соседними слоями
    let bolts = [];
    let flash = 0;     // общая вспышка экрана при массовом разряде
    let flashColor = CYAN;
    let lastTime = 0;
    let nextSpawn = 0, nextBurst = 0, nextBackprop = 0;
    let rafId = null;

    const rand = (a, b) => a + Math.random() * (b - a);
    const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
    const rgba = (c, a) => `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${Math.max(0, Math.min(1, a)).toFixed(3)})`;
    const mix = (a, b, t) => [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * t));

    // Предотрисованное свечение — дешевле, чем shadowBlur на каждом кадре
    function makeGlow(color) {
        const size = 64;
        const c = document.createElement('canvas');
        c.width = c.height = size;
        const g = c.getContext('2d');
        const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
        grad.addColorStop(0, rgba(WHITE, 1));
        grad.addColorStop(0.15, rgba(color, 0.9));
        grad.addColorStop(0.45, rgba(color, 0.25));
        grad.addColorStop(1, rgba(color, 0));
        g.fillStyle = grad;
        g.fillRect(0, 0, size, size);
        return c;
    }
    const glowCyan = makeGlow(CYAN);
    const glowPink = makeGlow(PINK);
    const glowFor = (color) => (color === CYAN ? glowCyan : glowPink);

    // ---------- Построение сети ----------

    function build() {
        dpr = Math.min(window.devicePixelRatio || 1, 1.75);
        W = window.innerWidth;
        H = window.innerHeight;
        canvas.width = Math.round(W * dpr);
        canvas.height = Math.round(H * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        const layerCount = Math.max(4, Math.min(9, Math.round(W / 210)));
        const marginX = W * 0.06;
        const marginY = H * 0.1;
        layers = [];
        edges = [];
        bolts = [];

        for (let l = 0; l < layerCount; l++) {
            const isEdgeLayer = l === 0 || l === layerCount - 1;
            const count = isEdgeLayer ? Math.round(rand(4, 6)) : Math.round(rand(5, 9));
            const x = marginX + (l * (W - marginX * 2)) / (layerCount - 1);
            const layer = [];
            for (let n = 0; n < count; n++) {
                const y = marginY + ((n + 0.5) * (H - marginY * 2)) / count;
                layer.push({
                    layer: l,
                    x0: x + rand(-18, 18),
                    y0: y + rand(-14, 14),
                    x: x, y: y,
                    phase: rand(0, Math.PI * 2),
                    amp: rand(4, 10),
                    heat: 0,
                    heatColor: CYAN,
                    out: [], in: [],
                });
            }
            layers.push(layer);
        }

        for (let l = 0; l < layers.length - 1; l++) {
            for (const a of layers[l]) {
                for (const b of layers[l + 1]) {
                    const edge = { a, b, heat: 0, color: CYAN, weight: rand(0.35, 1) };
                    a.out.push(edge);
                    b.in.push(edge);
                    edges.push(edge);
                }
            }
        }
    }

    // ---------- Молнии ----------

    // Случайная траектория от узла: на каждом шаге — случайный нейрон следующего слоя
    function randomPath(node, dir, maxSteps) {
        const path = [node];
        let current = node;
        for (let i = 0; i < maxSteps; i++) {
            const options = dir > 0 ? current.out : current.in;
            if (!options.length) break;
            const edge = pick(options);
            current = dir > 0 ? edge.b : edge.a;
            path.push(current);
        }
        return path;
    }

    function edgeBetween(a, b) {
        return a.out.find((e) => e.b === b) || b.out.find((e) => e.b === a);
    }

    function strike(node, dir, opts) {
        if (bolts.length >= MAX_BOLTS) return;
        const options = opts || {};
        const path = randomPath(node, dir, options.maxSteps || Infinity);
        if (path.length < 2) return;
        bolts.push({
            path: path,
            dir: dir,
            color: dir > 0 ? CYAN : PINK,
            age: 0,
            width: options.width || 1,
            reached: 0,          // сколько узлов пути уже «пробито»
            canBranch: options.canBranch !== false,
        });
        node.heat = 1;
        node.heatColor = dir > 0 ? CYAN : PINK;
    }

    // Ломаная линия между двумя точками — смещение середины, новый излом каждый кадр
    function jagged(ax, ay, bx, by, detail) {
        const points = [[ax, ay], [bx, by]];
        let spread = Math.hypot(bx - ax, by - ay) * BOLT_JITTER;
        for (let level = 0; level < detail; level++) {
            for (let i = points.length - 1; i > 0; i--) {
                const [x1, y1] = points[i - 1];
                const [x2, y2] = points[i];
                const dx = x2 - x1, dy = y2 - y1;
                const len = Math.hypot(dx, dy) || 1;
                const offset = rand(-spread, spread);
                points.splice(i, 0, [(x1 + x2) / 2 - (dy / len) * offset, (y1 + y2) / 2 + (dx / len) * offset]);
            }
            spread *= 0.55;
        }
        return points;
    }

    function updateBolts(dt) {
        for (let i = bolts.length - 1; i >= 0; i--) {
            const bolt = bolts[i];
            bolt.age += dt;
            const segments = bolt.path.length - 1;
            const progress = Math.min(segments, bolt.age * BOLT_SPEED);
            const reachedNow = Math.floor(progress) + 1;

            // Разряд дошёл до новых нейронов — вспышка, след на связи, возможная ветка
            for (let n = bolt.reached; n < Math.min(reachedNow, bolt.path.length); n++) {
                const node = bolt.path[n];
                node.heat = 1;
                node.heatColor = bolt.color;
                if (n > 0) {
                    const edge = edgeBetween(bolt.path[n - 1], node);
                    if (edge) { edge.heat = 1; edge.color = bolt.color; }
                }
                if (bolt.canBranch && n > 0 && n < segments && Math.random() < BRANCH_CHANCE) {
                    strike(node, bolt.dir, { maxSteps: Math.round(rand(1, 3)), width: 0.6, canBranch: false });
                }
            }
            bolt.reached = Math.max(bolt.reached, reachedNow);

            const strikeTime = segments / BOLT_SPEED;
            if (bolt.age > strikeTime + BOLT_LINGER) bolts.splice(i, 1);
        }
    }

    function drawBolt(bolt) {
        const segments = bolt.path.length - 1;
        const progress = Math.min(segments, bolt.age * BOLT_SPEED);
        const strikeTime = segments / BOLT_SPEED;
        const after = Math.max(0, bolt.age - strikeTime);
        // После удара молния мерцает и гаснет
        let alpha = after > 0 ? 1 - after / BOLT_LINGER : 1;
        alpha *= 0.55 + Math.random() * 0.45;
        if (alpha <= 0) return;

        // Собираем видимую часть пути в одну ломаную
        const points = [];
        for (let s = 0; s < Math.ceil(progress); s++) {
            const a = bolt.path[s];
            const b = bolt.path[s + 1];
            const part = Math.min(1, progress - s);
            const bx = a.x + (b.x - a.x) * part;
            const by = a.y + (b.y - a.y) * part;
            const seg = jagged(a.x, a.y, bx, by, 4);
            if (points.length) seg.shift();
            points.push(...seg);
        }
        if (points.length < 2) return;

        const stroke = (color, width, a) => {
            ctx.strokeStyle = rgba(color, a);
            ctx.lineWidth = width * bolt.width;
            ctx.beginPath();
            ctx.moveTo(points[0][0], points[0][1]);
            for (let i = 1; i < points.length; i++) ctx.lineTo(points[i][0], points[i][1]);
            ctx.stroke();
        };

        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        stroke(bolt.color, 9, alpha * 0.12);          // широкое свечение
        stroke(bolt.color, 3.5, alpha * 0.45);        // цветной канал
        stroke(mix(bolt.color, WHITE, 0.75), 1.2, alpha * 0.95); // раскалённое ядро

        // Яркая точка на острие, пока разряд летит
        if (after === 0) {
            const [hx, hy] = points[points.length - 1];
            const size = 46 * bolt.width;
            ctx.drawImage(glowFor(bolt.color), hx - size / 2, hy - size / 2, size, size);
        }
    }

    // ---------- Обновление ----------

    function update(dt, now) {
        const time = now / 1000;
        for (const layer of layers) {
            for (const node of layer) {
                node.x = node.x0 + Math.sin(time * 0.35 + node.phase) * node.amp;
                node.y = node.y0 + Math.cos(time * 0.28 + node.phase * 1.3) * node.amp;
                node.heat *= Math.exp(-dt * 2.2);
            }
        }
        const edgeDecay = Math.exp(-dt * 1.1);
        for (const edge of edges) edge.heat *= edgeDecay;
        flash *= Math.exp(-dt * 6);

        updateBolts(dt);

        // Одиночные разряды со входа
        if (now > nextSpawn) {
            strike(pick(layers[0]), 1);
            nextSpawn = now + rand(450, 1200);
        }
        // Прямой проход — гроза: несколько молний со входов разом и вспышка
        if (now > nextBurst) {
            const inputs = layers[0].slice().sort(() => Math.random() - 0.5);
            inputs.slice(0, Math.min(inputs.length, Math.round(rand(3, 5)))).forEach((node) => strike(node, 1, { width: 1.25 }));
            flash = 1;
            flashColor = CYAN;
            nextBurst = now + rand(5500, 9000);
        }
        // «Обратное распространение ошибки» — розовые молнии с выхода
        if (now > nextBackprop) {
            strike(pick(layers[layers.length - 1]), -1);
            nextBackprop = now + rand(2200, 4200);
        }
    }

    // ---------- Отрисовка ----------

    function draw() {
        ctx.clearRect(0, 0, W, H);

        if (flash > 0.01) {
            ctx.fillStyle = rgba(flashColor, flash * 0.05);
            ctx.fillRect(0, 0, W, H);
        }

        // Все связи одним путём — тонкая «паутина»
        ctx.beginPath();
        for (const e of edges) {
            ctx.moveTo(e.a.x, e.a.y);
            ctx.lineTo(e.b.x, e.b.y);
        }
        ctx.strokeStyle = 'rgba(140, 170, 255, 0.07)';
        ctx.lineWidth = 1;
        ctx.stroke();

        ctx.globalCompositeOperation = 'lighter';

        // Остаточное свечение связей, по которым ударил разряд
        for (const e of edges) {
            if (e.heat < 0.02) continue;
            const grad = ctx.createLinearGradient(e.a.x, e.a.y, e.b.x, e.b.y);
            const other = e.color === CYAN ? mix(CYAN, PINK, 0.35) : mix(PINK, CYAN, 0.35);
            grad.addColorStop(0, rgba(e.color, e.heat * 0.6 * e.weight));
            grad.addColorStop(1, rgba(other, e.heat * 0.45 * e.weight));
            ctx.strokeStyle = grad;
            ctx.lineWidth = 0.6 + e.heat * 1.4;
            ctx.beginPath();
            ctx.moveTo(e.a.x, e.a.y);
            ctx.lineTo(e.b.x, e.b.y);
            ctx.stroke();
        }

        for (const bolt of bolts) drawBolt(bolt);

        // Нейроны
        for (const layer of layers) {
            for (const n of layer) {
                if (n.heat > 0.03) {
                    const size = 18 + n.heat * 40;
                    ctx.globalAlpha = n.heat;
                    ctx.drawImage(glowFor(n.heatColor), n.x - size / 2, n.y - size / 2, size, size);
                    ctx.globalAlpha = 1;
                    ctx.strokeStyle = rgba(n.heatColor, n.heat * 0.8);
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, 6 + (1 - n.heat) * 12, 0, Math.PI * 2);
                    ctx.stroke();
                }
                ctx.fillStyle = rgba(mix([170, 200, 255], n.heatColor, n.heat), 0.35 + n.heat * 0.65);
                ctx.beginPath();
                ctx.arc(n.x, n.y, 2.6 + n.heat * 1.6, 0, Math.PI * 2);
                ctx.fill();
            }
        }

        ctx.globalCompositeOperation = 'source-over';
    }

    // ---------- Цикл ----------

    function frame(now) {
        const dt = Math.min(0.05, (now - lastTime) / 1000 || 0);
        lastTime = now;
        update(dt, now);
        draw();
        rafId = requestAnimationFrame(frame);
    }

    function start() {
        if (rafId !== null) return;
        lastTime = performance.now();
        rafId = requestAnimationFrame(frame);
    }

    function stop() {
        if (rafId !== null) cancelAnimationFrame(rafId);
        rafId = null;
    }

    // Статичный кадр с «застывшими» молниями для тех, у кого отключены анимации
    function drawStatic() {
        for (let i = 0; i < 3; i++) strike(pick(layers[0]), 1);
        for (const bolt of bolts) bolt.age = (bolt.path.length - 1) / BOLT_SPEED;
        updateBolts(0);
        draw();
    }

    build();
    if (reduceMotion) {
        drawStatic();
    } else {
        start();
        document.addEventListener('visibilitychange', () => (document.hidden ? stop() : start()));
    }

    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            build();
            if (reduceMotion) drawStatic();
        }, 200);
    });
})();
