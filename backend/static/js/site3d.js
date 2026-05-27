/* Чистая параметрическая 3D-модель участка.
   Задача этой версии — не декоративная «красивая игрушка», а понятный макет:
   - чёткие границы площадки;
   - несколько схем размещения;
   - разные площадки получают разные стартовые схемы;
   - без крупных случайных объектов, которые ломают масштаб сцены. */

const Site3D = (() => {
    let current = null;
    const currentLayouts = {};

    const LAYOUTS = {
        linear: {
            title: 'Линейная схема',
            note: 'цех, склад и служебные объекты выстроены вдоль основного внутреннего проезда',
            workshop: [-24, -18], warehouse: [36, -18], office: [-82, 34], checkpoint: [-110, 72], parking: [-66, 46],
            logistics: [74, -24], social: [46, 40], housing: [22, 32], green: [0, 54]
        },
        campus: {
            title: 'Кампусная схема',
            note: 'социальный блок вынесен в отдельный сектор, а производство и логистика разведены по сторонам участка',
            workshop: [-22, -16], warehouse: [34, -12], office: [58, 32], checkpoint: [112, 72], parking: [40, 46],
            logistics: [74, -26], social: [-74, 38], housing: [-92, 30], green: [-34, 54]
        },
        logistics: {
            title: 'Логистическая схема',
            note: 'грузовой двор приближен к восточному выезду, склад находится рядом с цехом, соцблок отделён от транспорта',
            workshop: [-28, -22], warehouse: [24, -20], office: [-82, 34], checkpoint: [-110, 72], parking: [-64, 46],
            logistics: [74, -16], social: [22, 40], housing: [48, 32], green: [-18, 54]
        },
        compact: {
            title: 'Компактная схема',
            note: 'объекты собраны компактно, но без наложений: общественный блок на юге, логистика на востоке',
            workshop: [-18, -12], warehouse: [24, -8], office: [50, 34], checkpoint: [112, 72], parking: [36, 46],
            logistics: [74, -22], social: [-74, 40], housing: [-92, 32], green: [-32, 56]
        }
    };

    const LAYOUT_KEYS = Object.keys(LAYOUTS);

    const SPORT_LABELS = {
        outdoor_gym: 'спорт-зона',
        stadium: 'стадион',
        pool: 'бассейн',
        gym: 'спортзал',
        hockey_rink: 'хоккейная площадка',
    };

    function valueOf(v) {
        return (v && typeof v === 'object' && 'value' in v) ? v.value : v;
    }

    function hashRegionId(id) {
        return Array.from(String(id || '')).reduce((s, ch) => s + ch.charCodeAt(0), 0);
    }

    function defaultLayoutKey(region) {
        return LAYOUT_KEYS[hashRegionId(region?.id) % LAYOUT_KEYS.length];
    }

    function getCurrentLayout(regionId) {
        if (regionId && currentLayouts[regionId]) return currentLayouts[regionId];
        if (current?.regionId && currentLayouts[current.regionId]) return currentLayouts[current.regionId];
        return null;
    }

    function hexColor(value, fallback) {
        try { return new THREE.Color(value || fallback); }
        catch { return new THREE.Color(fallback); }
    }

    function getStyle(region, input) {
        const palette = region?.culture?.color_palette || ['#D9C7A2', '#8B5A2B', '#6E7F80', '#A3B18A'];
        const arch = valueOf(input?.arch_priority) || 'authenticity';
        const primary = hexColor(palette[0], '#d8c7a7');
        const secondary = hexColor(palette[1], '#8b5a2b');
        const accent = hexColor(palette[2], '#697e81');
        const green = hexColor(palette[3], '#91aa78');

        if (arch === 'techno') {
            return {
                sky: new THREE.Color('#edf4fb'), ground: new THREE.Color('#dfe4df'), site: new THREE.Color('#cdd4cf'),
                workshop: new THREE.Color('#c9d1d8'), warehouse: new THREE.Color('#b8c1c9'), office: new THREE.Color('#303946'),
                road: new THREE.Color('#656a70'), logistics: new THREE.Color('#d2d0cb'), social: new THREE.Color('#d7e4d1'),
                green, accent, deco: secondary, border: new THREE.Color('#323844')
            };
        }
        if (arch === 'eco') {
            return {
                sky: new THREE.Color('#f1f9f3'), ground: new THREE.Color('#dde8d5'), site: new THREE.Color('#cfdcc8'),
                workshop: new THREE.Color('#e1e9de'), warehouse: new THREE.Color('#c9d6c1'), office: new THREE.Color('#8b6a4c'),
                road: new THREE.Color('#6f6d68'), logistics: new THREE.Color('#ded6ca'), social: new THREE.Color('#dcead4'),
                green: new THREE.Color('#6f9b63'), accent, deco: secondary, border: new THREE.Color('#3d503c')
            };
        }
        return {
            sky: new THREE.Color('#f7f2ea'), ground: new THREE.Color('#e9e1d4'), site: new THREE.Color('#d7d1c2'),
            workshop: primary, warehouse: new THREE.Color('#d0c3af'), office: secondary,
            road: new THREE.Color('#6d6863'), logistics: new THREE.Color('#e2d7cc'), social: new THREE.Color('#e6eadc'),
            green, accent, deco: secondary, border: new THREE.Color('#4d443c')
        };
    }

    function disposeCurrent() {
        if (!current) return;
        current.resizeObserver?.disconnect?.();
        current.animationFrame && cancelAnimationFrame(current.animationFrame);
        current.renderer?.dispose?.();
        if (current.root && current.renderer?.domElement && current.root.contains(current.renderer.domElement)) {
            current.renderer.domElement.remove();
        }
        current = null;
    }

    function render(root, ranked, region, input, options = {}) {
        if (!root || !ranked || !region) return;
        if (typeof THREE === 'undefined') {
            root.innerHTML = '<div class="viewer3d__error">Three.js не загрузился. Обновите страницу через Ctrl+F5.</div>';
            return;
        }
        const layoutKey = options.layoutKey || getCurrentLayout(region.id) || defaultLayoutKey(region);
        build(root, ranked, region, input, layoutKey, options);
    }

    function build(root, ranked, region, input, layoutKey, options = {}) {
        disposeCurrent();
        const normalizedLayoutKey = LAYOUTS[layoutKey] ? layoutKey : defaultLayoutKey(region);
        currentLayouts[region.id] = normalizedLayoutKey;
        const layout = LAYOUTS[normalizedLayoutKey] || LAYOUTS.linear;
        const style = getStyle(region, input);

        root.innerHTML = `
            <div class="viewer3d__top">
                <div>
                    <div class="viewer3d__title">3D-макет площадки</div>
                    <div class="viewer3d__subtitle">${layout.title}: ${layout.note}. Для разных площадок выбирается разная стартовая схема, а ниже можно переключить вариант вручную.</div>
                </div>
                <div class="viewer3d__controls">
                    <button type="button" class="viewer3d__btn" data-view="south">Юг</button>
                    <button type="button" class="viewer3d__btn" data-view="north">Север</button>
                    <button type="button" class="viewer3d__btn" data-view="west">Запад</button>
                    <button type="button" class="viewer3d__btn" data-view="east">Восток</button>
                    <button type="button" class="viewer3d__btn" data-view="top">Сверху</button>
                    <button type="button" class="viewer3d__btn" data-view="reset">Сброс</button>
                </div>
            </div>
            <div class="viewer3d__layout-switch">
                ${LAYOUT_KEYS.map(key => `<button type="button" class="viewer3d__layout-btn ${key === normalizedLayoutKey ? 'active' : ''}" data-layout="${key}">${LAYOUTS[key].title}</button>`).join('')}
            </div>
            <div class="viewer3d__layout">
                <div class="viewer3d__canvas-wrap">
                    <div class="viewer3d__canvas"></div>
                    <div class="viewer3d__hint">ЛКМ — вращать · колёсико — масштаб · клик по объекту — описание</div>
                </div>
                <aside class="viewer3d__side">
                    <div class="viewer3d__card viewer3d__card--info">
                        <div class="viewer3d__card-title">Выбранный объект</div>
                        <div class="viewer3d__object-name" id="viewer3d-object-name">${layout.title}</div>
                        <div class="viewer3d__object-text" id="viewer3d-object-text">Макет показывает границы участка, функциональные зоны, цех, склад, общественный вход, грузовой двор и социальный блок.</div>
                    </div>
                    <div class="viewer3d__card">
                        <div class="viewer3d__card-title">Легенда</div>
                        <div class="viewer3d__legend">${legendHtml(ranked, region, input, layout)}</div>
                    </div>
                </aside>
            </div>
        `;

        root.querySelectorAll('[data-layout]').forEach(btn => {
            btn.addEventListener('click', () => build(root, ranked, region, input, btn.dataset.layout, options));
        });

        const canvasHost = root.querySelector('.viewer3d__canvas');
        const infoTitle = root.querySelector('#viewer3d-object-name');
        const infoText = root.querySelector('#viewer3d-object-text');
        const width = Math.max(canvasHost.clientWidth || 760, 760);
        const height = Math.max(canvasHost.clientHeight || 600, 600);

        const bundle = createSceneBundle(width, height, ranked, region, input, normalizedLayoutKey);
        const { scene, camera, renderer, controls } = bundle;
        const clickable = [];
        scene.traverse(obj => {
            if (obj.userData && obj.userData.name && obj.userData.description) clickable.push({ mesh: obj, ...obj.userData });
        });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        canvasHost.appendChild(renderer.domElement);

        const raycaster = new THREE.Raycaster();
        const pointer = new THREE.Vector2();
        renderer.domElement.addEventListener('pointerdown', (event) => {
            const rect = renderer.domElement.getBoundingClientRect();
            pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
            pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
            raycaster.setFromCamera(pointer, camera);
            const intersects = raycaster.intersectObjects(clickable.map(x => x.mesh), true);
            if (!intersects.length) return;
            const picked = findUserData(intersects[0].object);
            if (!picked) return;
            infoTitle.textContent = picked.name || 'Объект';
            infoText.textContent = picked.description || '';
            highlight(clickable, picked.rootMesh || intersects[0].object);
        });

        const views = {
            south: [0, 105, 180], north: [0, 105, -180], west: [-180, 105, 0], east: [180, 105, 0],
            top: [0, 270, 0.01], reset: [156, 138, 156]
        };
        root.querySelectorAll('[data-view]').forEach(btn => {
            btn.addEventListener('click', () => {
                const v = views[btn.dataset.view];
                if (!v) return;
                controls.setView(v[0], v[1], v[2]);
            });
        });

        const resizeObserver = new ResizeObserver(() => {
            const w = Math.max(canvasHost.clientWidth || 760, 760);
            const h = Math.max(canvasHost.clientHeight || 600, 600);
            updateCamera(camera, w, h);
            renderer.setSize(w, h);
        });
        resizeObserver.observe(canvasHost);

        function animate() {
            current.animationFrame = requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        }
        current = { root: canvasHost, renderer, resizeObserver, animationFrame: null, regionId: region.id, layoutKey: normalizedLayoutKey };
        root.dataset.layoutKey = normalizedLayoutKey;
        root.dataset.regionId = region.id;
        if (typeof options.onLayoutChange === 'function') options.onLayoutChange(normalizedLayoutKey);
        animate();
    }


    function createSceneBundle(width, height, ranked, region, input, layoutKey) {
        const normalizedLayoutKey = LAYOUTS[layoutKey] ? layoutKey : defaultLayoutKey(region);
        const layout = LAYOUTS[normalizedLayoutKey] || LAYOUTS.linear;
        const style = getStyle(region, input);

        const scene = new THREE.Scene();
        scene.background = style.sky;
        scene.fog = new THREE.Fog(style.sky.getHex(), 260, 430);

        const camera = makeCamera(width, height);
        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
        renderer.setPixelRatio(1);
        renderer.setSize(width, height);
        renderer.setClearColor(style.sky, 1);
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;

        const controls = createSimpleOrbitControls(camera, renderer.domElement, new THREE.Vector3(0, 0, 0));
        controls.setView(156, 138, 156);

        addLights(scene);
        const siteGroup = new THREE.Group();
        scene.add(siteGroup);
        const clickable = [];

        addBase(scene, siteGroup, style);
        addZones(siteGroup, layout, style);
        addRoads(siteGroup, layout, style);
        addBuildings(siteGroup, clickable, ranked, region, input, layout, style);
        addSmallObjects(siteGroup, clickable, ranked, input, layout, style);
        addLabels(scene, layout, style, input);

        return { scene, camera, renderer, controls, layout, layoutKey: normalizedLayoutKey };
    }

    async function captureViews(ranked, region, input, layoutKey) {
        if (typeof THREE === 'undefined') throw new Error('THREE is not loaded');
        const bundle = createSceneBundle(920, 520, ranked, region, input, layoutKey);
        const { scene, camera, renderer, controls } = bundle;
        const views = {
            south: [0, 105, 180],
            north: [0, 105, -180],
            west: [-180, 105, 0],
            east: [180, 105, 0],
        };
        const shots = {};
        for (const [key, v] of Object.entries(views)) {
            controls.setView(v[0], v[1], v[2]);
            renderer.render(scene, camera);
            shots[key] = renderer.domElement.toDataURL('image/png');
        }
        renderer.dispose();
        return shots;
    }

    function makeCamera(width, height) {
        const aspect = width / height;
        const frustum = 230;
        const camera = new THREE.OrthographicCamera(
            frustum * aspect / -2, frustum * aspect / 2, frustum / 2, frustum / -2, 0.1, 1000
        );
        camera.zoom = 0.84;
        camera.updateProjectionMatrix();
        return camera;
    }

    function updateCamera(camera, width, height) {
        const aspect = width / height;
        const frustum = 230;
        camera.left = frustum * aspect / -2;
        camera.right = frustum * aspect / 2;
        camera.top = frustum / 2;
        camera.bottom = frustum / -2;
        camera.updateProjectionMatrix();
    }

    function addLights(scene) {
        scene.add(new THREE.HemisphereLight(0xffffff, 0xb8b4aa, 1.25));
        const sun = new THREE.DirectionalLight(0xffffff, 1.35);
        sun.position.set(120, 180, 95);
        sun.castShadow = true;
        sun.shadow.mapSize.width = 2048;
        sun.shadow.mapSize.height = 2048;
        sun.shadow.camera.left = -170;
        sun.shadow.camera.right = 170;
        sun.shadow.camera.top = 170;
        sun.shadow.camera.bottom = -170;
        scene.add(sun);
    }

    function addBase(scene, group, style) {
        const outer = new THREE.Mesh(
            new THREE.PlaneGeometry(520, 420),
            new THREE.MeshStandardMaterial({ color: lighten(style.ground, 0.05), roughness: 0.95 })
        );
        outer.rotation.x = -Math.PI / 2;
        outer.position.y = -0.25;
        scene.add(outer);

        const site = new THREE.Mesh(
            new THREE.BoxGeometry(240, 1.4, 160),
            new THREE.MeshStandardMaterial({ color: style.site, roughness: 0.86 })
        );
        site.position.y = 0;
        site.receiveShadow = true;
        group.add(site);

        const borderMat = new THREE.LineBasicMaterial({ color: style.border, linewidth: 2 });
        const border = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(240.8, 1.8, 160.8)), borderMat);
        border.position.y = 0.2;
        group.add(border);

        // Плотный контур участка на уровне земли.
        const pts = [[-120, -80], [120, -80], [120, 80], [-120, 80], [-120, -80]];
        const geom = new THREE.BufferGeometry().setFromPoints(pts.map(p => new THREE.Vector3(p[0], 1.05, p[1])));
        group.add(new THREE.Line(geom, new THREE.LineBasicMaterial({ color: style.border, linewidth: 3 })));

        // Ограждение: небольшие стойки по периметру.
        const postMat = new THREE.MeshStandardMaterial({ color: style.border });
        for (let x = -112; x <= 112; x += 16) {
            addPost(group, x, -80, postMat); addPost(group, x, 80, postMat);
        }
        for (let z = -64; z <= 64; z += 16) {
            addPost(group, -120, z, postMat); addPost(group, 120, z, postMat);
        }
    }

    function addPost(group, x, z, mat) {
        const post = new THREE.Mesh(new THREE.BoxGeometry(1.2, 4, 1.2), mat);
        post.position.set(x, 2.3, z);
        group.add(post);
    }

    function addZones(group, layout, style) {
        const prodX = (layout.workshop[0] + layout.warehouse[0]) / 2;
        const prodZ = (layout.workshop[1] + layout.warehouse[1]) / 2;
        const publicX = (layout.office[0] + layout.parking[0]) / 2;
        const publicZ = (layout.office[1] + layout.parking[1]) / 2 + 4;

        addZone(group, prodX, prodZ, 104, 44, lighten(style.workshop, 0.42), 'Производственная зона');
        addZone(group, publicX, publicZ, 64, 34, lighten(style.office, 0.58), 'Общественная зона');
        addZone(group, layout.social[0], layout.social[1], 64, 34, style.social, 'Социальная зона');
        addZone(group, layout.logistics[0], layout.logistics[1], 48, 32, style.logistics, 'Грузовой контур');
        addZone(group, layout.green[0], layout.green[1], 56, 18, lighten(style.green, 0.36), 'Зелёная зона');
    }

    function addZone(group, x, z, w, d, color, name) {
        const mat = new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.48, roughness: 0.95 });
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, 0.12, d), mat);
        mesh.position.set(x, 0.96, z);
        mesh.userData = { name, description: `Функциональная зона: ${name.toLowerCase()}.` };
        group.add(mesh);
        const edges = new THREE.LineSegments(
            new THREE.EdgesGeometry(new THREE.BoxGeometry(w, 0.16, d)),
            new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85 })
        );
        edges.position.copy(mesh.position);
        group.add(edges);
    }

    function addRoads(group, layout, style) {
        addRoad(group, 0, 62, 226, 14, style.road, true);
        addRoad(group, 102, -2, 14, 136, style.road, false);
    }

    function addRoad(group, x, z, w, d, color, horizontal) {
        const road = new THREE.Mesh(new THREE.BoxGeometry(w, 0.28, d), new THREE.MeshStandardMaterial({ color, roughness: 0.9 }));
        road.position.set(x, 1.18, z);
        road.receiveShadow = true;
        group.add(road);
        const markMat = new THREE.MeshBasicMaterial({ color: 0xf5f1df });
        const count = horizontal ? Math.floor(w / 24) : Math.floor(d / 22);
        for (let i = 0; i < count; i++) {
            const mark = new THREE.Mesh(new THREE.BoxGeometry(horizontal ? 9 : 1.2, 0.04, horizontal ? 1.2 : 9), markMat);
            mark.position.set(horizontal ? x - w/2 + 18 + i * 24 : x, 1.36, horizontal ? z : z - d/2 + 18 + i * 22);
            group.add(mark);
        }
    }

    function addBuildings(group, clickable, ranked, region, input, layout, style) {
        const a = ranked.areas || {};
        const volume = Number(input.production_volume_kt || 500);
        addBuilding(group, clickable, {
            name: 'Производственный цех', x: layout.workshop[0], z: layout.workshop[1],
            w: clamp(50 + volume * 0.032, 54, 74), d: clamp(24 + volume * 0.012, 26, 34), h: 13,
            color: style.workshop, roof: lighten(style.workshop, 0.12), accent: style.accent,
            description: `Основной корпус производства сэндвич-панелей. Расчётная площадь: ${Math.round(a.workshop_m2 || 0)} м².`
        });
        addBuilding(group, clickable, {
            name: 'Склад', x: layout.warehouse[0], z: layout.warehouse[1],
            w: clamp(22 + (a.warehouse_m2 || 0) * 0.012, 22, 32), d: 18, h: 9,
            color: style.warehouse, roof: lighten(style.warehouse, 0.12), accent: style.border,
            description: `Склад сырья и готовой продукции. Расчётная площадь: ${Math.round(a.warehouse_m2 || 0)} м².`
        });
        addBuilding(group, clickable, {
            name: 'АБК', x: layout.office[0], z: layout.office[1], w: 20, d: 13, h: 7,
            color: style.office, roof: lighten(style.office, 0.12), accent: style.accent,
            description: 'Административно-бытовой корпус у общественного входа.'
        });
        addBuilding(group, clickable, {
            name: 'КПП', x: layout.checkpoint[0], z: layout.checkpoint[1], w: 12, d: 8, h: 4,
            color: new THREE.Color('#ecebe5'), roof: new THREE.Color('#d7d2c6'), accent: style.border,
            description: 'Контрольно-пропускной пункт на въезде.'
        });
    }

    function addBuilding(group, clickable, cfg) {
        const g = new THREE.Group();
        const body = new THREE.Mesh(new THREE.BoxGeometry(cfg.w, cfg.h, cfg.d), new THREE.MeshStandardMaterial({ color: cfg.color, roughness: 0.78 }));
        body.position.y = 1.4 + cfg.h / 2;
        body.castShadow = true;
        body.receiveShadow = true;
        g.add(body);
        const roof = new THREE.Mesh(new THREE.BoxGeometry(cfg.w + 1.5, 1.2, cfg.d + 1.5), new THREE.MeshStandardMaterial({ color: cfg.roof, roughness: 0.75 }));
        roof.position.y = 1.4 + cfg.h + 0.6;
        roof.castShadow = true;
        g.add(roof);
        const accent = new THREE.Mesh(new THREE.BoxGeometry(cfg.w + 0.5, 0.6, 0.6), new THREE.MeshStandardMaterial({ color: cfg.accent }));
        accent.position.set(0, 1.4 + cfg.h * 0.58, cfg.d/2 + 0.34);
        g.add(accent);
        addWindows(g, cfg);
        g.position.set(cfg.x, 0, cfg.z);
        g.userData = { name: cfg.name, description: cfg.description };
        group.add(g);
        clickable.push({ mesh: g, baseColor: cfg.color.clone() });
        return g;
    }

    function addWindows(group, cfg) {
        const winMat = new THREE.MeshStandardMaterial({ color: 0xdceaf0, roughness: 0.2, metalness: 0.05 });
        const count = Math.max(2, Math.floor(cfg.w / 16));
        for (let i = 0; i < count; i++) {
            const win = new THREE.Mesh(new THREE.BoxGeometry(4, 2.5, 0.35), winMat);
            win.position.set(-cfg.w/2 + 8 + i * ((cfg.w - 16) / Math.max(1, count-1)), 1.4 + cfg.h * 0.55, cfg.d/2 + 0.38);
            group.add(win);
        }
    }

    function addSmallObjects(group, clickable, ranked, input, layout, style) {
        addParking(group, clickable, layout.parking[0], layout.parking[1], style, Math.round((input.employees || 80) * 0.45));
        addLogistics(group, clickable, layout.logistics[0], layout.logistics[1], style);
        addSocial(group, clickable, layout.social[0], layout.social[1], ranked, input, style);
        addLandscaping(group, style, layout);
    }

    function addParking(group, clickable, x, z, style, spaces) {
        const pad = new THREE.Mesh(new THREE.BoxGeometry(28, 0.18, 14), new THREE.MeshStandardMaterial({ color: 0xc6c8cc }));
        pad.position.set(x, 1.32, z);
        group.add(pad);
        const lineMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
        for (let i = 0; i < 10; i++) {
            const line = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.04, 5.5), lineMat);
            line.position.set(x - 11 + i * 2.45, 1.43, z);
            group.add(line);
        }
        const proxy = new THREE.Group();
        proxy.position.set(x, 1.5, z);
        proxy.userData = { name: 'Парковка', description: `Парковка перед проходной. Расчётно: до ${spaces} машиномест.` };
        group.add(proxy);
        clickable.push({ mesh: proxy, baseColor: style.road.clone() });
    }

    function addLogistics(group, clickable, x, z, style) {
        const pad = new THREE.Mesh(new THREE.BoxGeometry(28, 0.18, 16), new THREE.MeshStandardMaterial({ color: 0xd8cfc4 }));
        pad.position.set(x, 1.34, z);
        group.add(pad);
        for (let i = 0; i < 2; i++) {
            const pack = new THREE.Mesh(new THREE.BoxGeometry(10, 2.8, 5), new THREE.MeshStandardMaterial({ color: 0xe6e4dc }));
            pack.position.set(x - 6 + i*10, 2.9, z - 4);
            pack.castShadow = true;
            group.add(pack);
        }
        const proxy = new THREE.Group();
        proxy.position.set(x, 1.5, z);
        proxy.userData = { name: 'Грузовой двор', description: 'Отдельная зона приёмки сырья и отгрузки готовых панелей.' };
        group.add(proxy);
        clickable.push({ mesh: proxy, baseColor: style.accent.clone() });
    }

    function addSocial(group, clickable, x, z, ranked, input, style) {
        if ((input.housing?.pct || 0) > 0) {
            for (let i = 0; i < 2; i++) {
                const block = new THREE.Mesh(new THREE.BoxGeometry(9, 6, 7), new THREE.MeshStandardMaterial({ color: 0xc7b9a5 }));
                block.position.set(x - 8 + i*9, 4.7, z - 2);
                block.userData = { name: 'Жильё сотрудников', description: `Жилой блок для ${input.housing.pct}% сотрудников.` };
                block.castShadow = true;
                group.add(block);
                clickable.push({ mesh: block, baseColor: block.material.color.clone() });
            }
        }
        if ((input.kindergarten_per_100 || 0) > 0) {
            const kd = new THREE.Mesh(new THREE.BoxGeometry(14, 4.5, 10), new THREE.MeshStandardMaterial({ color: 0xf0dca9 }));
            kd.position.set(x + 4, 3.8, z - 1);
            kd.userData = { name: 'Детский сад', description: `Детский сад: ${input.kindergarten_per_100} мест на 100 сотрудников.` };
            kd.castShadow = true;
            group.add(kd);
            clickable.push({ mesh: kd, baseColor: kd.material.color.clone() });
        }
        if ((input.sport_objects || []).length) {
            const sportName = SPORT_LABELS[valueOf(input.sport_objects[0])] || 'спорт-зона';
            const sport = new THREE.Mesh(new THREE.BoxGeometry(12, 0.18, 8), new THREE.MeshStandardMaterial({ color: 0x90b47d }));
            sport.position.set(x + 15, 1.4, z + 6);
            sport.userData = { name: sportName, description: 'Спортивная зона для сотрудников и жителей.' };
            group.add(sport);
            clickable.push({ mesh: sport, baseColor: sport.material.color.clone() });
            const line = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(12, 0.22, 8)), new THREE.LineBasicMaterial({ color: 0xffffff }));
            line.position.copy(sport.position);
            group.add(line);
        }
    }

    function addLandscaping(group, style, layout) {
        for (let i = 0; i < 5; i++) addTree(group, -96 + i*18, 68, style.green);
        for (let i = 0; i < 4; i++) addTree(group, layout.green[0] - 14 + i*9, layout.green[1], style.green);
        for (let i = 0; i < 3; i++) addTree(group, 106, -36 + i*20, style.green);
    }

    function addTree(group, x, z, color) {
        const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.65, 3.2, 6), new THREE.MeshStandardMaterial({ color: 0x79583b }));
        trunk.position.set(x, 3, z);
        const crown = new THREE.Mesh(new THREE.SphereGeometry(2.3, 10, 10), new THREE.MeshStandardMaterial({ color }));
        crown.position.set(x, 5.4, z);
        trunk.castShadow = crown.castShadow = true;
        group.add(trunk, crown);
    }

    function addLabels(scene, layout, style, input) {
        const prodX = (layout.workshop[0] + layout.warehouse[0]) / 2;
        const prodZ = (layout.workshop[1] + layout.warehouse[1]) / 2 - 26;
        const publicX = (layout.office[0] + layout.parking[0]) / 2;
        const publicZ = (layout.office[1] + layout.parking[1]) / 2 + 22;
        const labels = [
            ['ПРОИЗВОДСТВО', prodX, prodZ],
            ['ОБЩЕСТВЕННЫЙ ВХОД', publicX, publicZ],
            ['ЛОГИСТИКА', layout.logistics[0], layout.logistics[1] - 24],
            ['СОЦИАЛЬНЫЙ БЛОК', layout.social[0], layout.social[1] + 24],
            ['ОЗЕЛЕНЕНИЕ', layout.green[0], layout.green[1] + 16],
        ];
        labels.forEach(([text, x, z]) => {
            const sprite = makeTextSprite(text, '#273142', 'rgba(255,255,255,0.92)');
            sprite.position.set(x, 18, z);
            sprite.scale.set(28, 5.8, 1);
            sprite.material.depthTest = false;
            scene.add(sprite);
        });
    }

    function makeTextSprite(text, color, background) {
        const canvas = document.createElement('canvas');
        canvas.width = 512; canvas.height = 128;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = background;
        roundRect(ctx, 10, 24, 492, 78, 20); ctx.fill();
        ctx.strokeStyle = 'rgba(35,42,54,0.16)'; ctx.lineWidth = 4; ctx.stroke();
        ctx.fillStyle = color;
        ctx.font = '700 34px Arial';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(text, canvas.width/2, canvas.height/2 + 2);
        const texture = new THREE.CanvasTexture(canvas);
        return new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true }));
    }

    function roundRect(ctx, x, y, w, h, r) {
        ctx.beginPath(); ctx.moveTo(x+r, y); ctx.arcTo(x+w, y, x+w, y+h, r); ctx.arcTo(x+w, y+h, x, y+h, r); ctx.arcTo(x, y+h, x, y, r); ctx.arcTo(x, y, x+w, y, r); ctx.closePath();
    }

    function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
    function lighten(color, amount) { const c = color.clone(); c.lerp(new THREE.Color('#ffffff'), amount); return c; }

    function findUserData(obj) {
        let cur = obj;
        while (cur) {
            if (cur.userData && cur.userData.name) return { ...cur.userData, rootMesh: cur };
            cur = cur.parent;
        }
        return null;
    }

    function highlight(clickable, selected) {
        clickable.forEach(item => {
            item.mesh.traverse?.(child => {
                if (child.material?.emissive) child.material.emissive.set(0x000000);
                if (child.material) child.material.emissiveIntensity = 0;
            });
        });
        selected.traverse?.(child => {
            if (child.material) {
                child.material.emissive = child.material.emissive || new THREE.Color('#000000');
                child.material.emissive.set('#f0c56b');
                child.material.emissiveIntensity = 0.22;
            }
        });
    }

    function createSimpleOrbitControls(camera, domElement, target) {
        const state = { theta: Math.PI/4, phi: 0.88, radius: 205, dragging: false, lastX: 0, lastY: 0 };
        const controls = { target: target.clone(), update, setView };
        function setView(x, y, z) {
            camera.position.set(x, y, z);
            const offset = camera.position.clone().sub(controls.target);
            state.radius = offset.length();
            state.theta = Math.atan2(offset.x, offset.z);
            state.phi = Math.acos(THREE.MathUtils.clamp(offset.y / state.radius, -1, 1));
            update();
        }
        function update() {
            state.phi = THREE.MathUtils.clamp(state.phi, 0.16, 1.42);
            state.radius = THREE.MathUtils.clamp(state.radius, 120, 300);
            camera.position.set(
                controls.target.x + state.radius * Math.sin(state.phi) * Math.sin(state.theta),
                controls.target.y + state.radius * Math.cos(state.phi),
                controls.target.z + state.radius * Math.sin(state.phi) * Math.cos(state.theta),
            );
            camera.lookAt(controls.target);
        }
        domElement.addEventListener('pointerdown', e => { state.dragging = true; state.lastX = e.clientX; state.lastY = e.clientY; });
        window.addEventListener('pointerup', () => { state.dragging = false; });
        window.addEventListener('pointermove', e => {
            if (!state.dragging) return;
            state.theta -= (e.clientX - state.lastX) * 0.006;
            state.phi += (e.clientY - state.lastY) * 0.006;
            state.lastX = e.clientX; state.lastY = e.clientY;
        });
        domElement.addEventListener('wheel', e => {
            e.preventDefault();
            if (camera.isOrthographicCamera) {
                camera.zoom = THREE.MathUtils.clamp(camera.zoom - e.deltaY * 0.0012, 0.62, 1.7);
                camera.updateProjectionMatrix();
            } else {
                state.radius += e.deltaY * 0.06;
            }
        }, { passive: false });
        update(); return controls;
    }

    function legendHtml(ranked, region, input, layout) {
        const sport = (input?.sport_objects || []).map(valueOf).map(x => SPORT_LABELS[x] || 'спорт-зона').join(', ') || 'не выбран';
        const rows = [
            ['Схема', layout.title],
            ['Площадка', region.name],
            ['Цех', `${Math.round(ranked.areas?.workshop_m2 || 0)} м²`],
            ['Склад', `${Math.round(ranked.areas?.warehouse_m2 || 0)} м²`],
            ['Социальный блок', `жильё ${input?.housing?.pct || 0}% · спорт: ${sport}`],
            ['Инженерия', `${region.infrastructure?.free_power_kva || 0} кВА · газ: ${region.infrastructure?.gas_available ? 'есть' : 'нет'}`],
        ];
        return rows.map(([a,b]) => `<div class="viewer3d__legend-row"><span>${a}</span><b>${b}</b></div>`).join('');
    }

    return { render, getCurrentLayout, defaultLayoutKey, captureViews };
})();

// Expose module for app.js tab handler.
window.Site3D = Site3D;
