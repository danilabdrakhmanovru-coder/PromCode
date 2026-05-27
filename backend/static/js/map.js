/* Гибридная карта:
   - если есть корректный ключ 2ГИС и загрузилась MapGL — используется 2ГИС;
   - если ключа нет или 2ГИС не загрузился — используется OpenStreetMap;
   - плашка провайдера/ошибки полностью отключена.
*/

console.log('[MapView] hybrid script loaded');

const MapView = (() => {
    let provider = null;
    let leafletMap = null;
    let leafletLayer = null;
    let dgisMap = null;
    let dgisMarkers = [];
    let fallbackReason = '';

    const RANK_COLORS = ["#B58A2E", "#6E6C66", "#7A4F2E"];
    const INK = "#1F1E1B";
    const BG = "#FBF7EC";

    function init() {
        const container = document.getElementById('map');
        if (!container) return false;

        container.style.height = '520px';
        container.style.width = '100%';

        const dgisKey = (window.APP_CONFIG?.dgisKey || '').trim();
        const hasDgisGlobal = typeof window.mapgl !== 'undefined';

        console.log('[MapView] DGIS key present:', Boolean(dgisKey), 'mapgl loaded:', hasDgisGlobal);

        if (!dgisKey) {
            fallbackReason = 'Ключ 2ГИС не указан. Используется OpenStreetMap.';
        } else if (!hasDgisGlobal) {
            fallbackReason = 'Библиотека 2ГИС MapGL не загрузилась. Используется OpenStreetMap.';
        } else {
            try {
                provider = '2gis';
                container.innerHTML = '';

                dgisMap = new window.mapgl.Map(container, {
                    center: [56.0, 54.2],
                    zoom: 7,
                    key: dgisKey,
                    enableTrackResize: true,
                });

                return true;
            } catch (e) {
                fallbackReason = '2ГИС MapGL не инициализировалась. Используется OpenStreetMap.';
                console.warn('[MapView] 2ГИС не инициализировался, перехожу на Leaflet:', e);
                container.innerHTML = '';
            }
        }

        if (typeof L === 'undefined') {
            container.innerHTML = `
                <div class="map-fallback">
                    <i class="ti ti-map-off" style="font-size:48px;opacity:0.3;margin-bottom:1rem;"></i>
                    <p>Не загрузилась библиотека карты</p>
                    <small>${fallbackReason || 'Проверь подключение к интернету и доступность CDN.'}</small>
                </div>
            `;
            return false;
        }

        provider = 'leaflet';
        container.innerHTML = '';

        leafletMap = L.map('map').setView([54.2, 56.0], 7);

        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19,
        }).addTo(leafletMap);

        leafletLayer = L.layerGroup().addTo(leafletMap);

        setTimeout(() => {
            if (leafletMap) leafletMap.invalidateSize();
        }, 200);

        return true;
    }

    function clearMarkers() {
        if (leafletLayer) {
            leafletLayer.clearLayers();
        }

        dgisMarkers.forEach(marker => {
            try {
                if (marker.destroy) marker.destroy();
            } catch (e) {
                console.warn('[MapView] Не удалось удалить маркер 2ГИС:', e);
            }
        });

        dgisMarkers = [];
    }

    function makeRankIcon(rank, color, size) {
        const html = `
            <div style="
                width:${size}px;
                height:${size}px;
                background:${color};
                border:2px solid ${INK};
                border-radius:50%;
                display:flex;
                align-items:center;
                justify-content:center;
                color:${BG};
                font-family:'Cormorant Garamond', Georgia, serif;
                font-weight:700;
                font-size:${Math.floor(size * 0.55)}px;
                box-shadow:0 2px 6px rgba(0,0,0,0.3);
                line-height:1;
            ">${rank}</div>
        `;

        return L.divIcon({
            className: 'rank-pin',
            html,
            iconSize: [size, size],
            iconAnchor: [size / 2, size / 2],
        });
    }

    function makeDgisMarkerContent(rank, color) {
        const el = document.createElement('div');
        el.className = 'dgis-rank-pin';
        el.style.background = color;
        el.textContent = rank;
        return el;
    }

    function render2gis(results) {
        results.forEach((ranked, i) => {
            const r = ranked.region;
            const color = RANK_COLORS[i] || '#888';

            const marker = new window.mapgl.HtmlMarker(dgisMap, {
                coordinates: [r.center.lon, r.center.lat],
                html: makeDgisMarkerContent(i + 1, color),
                anchor: [18, 18],
            });

            dgisMarkers.push(marker);

            marker.getContent().title = `${i + 1}. ${r.name}`;
            marker.getContent().addEventListener('click', () => {
                if (window.App && App.selectRegion) {
                    App.selectRegion(r.id);
                }
            });
        });

        if (results.length) {
            const avgLon = results.reduce((sum, x) => sum + x.region.center.lon, 0) / results.length;
            const avgLat = results.reduce((sum, x) => sum + x.region.center.lat, 0) / results.length;

            try {
                dgisMap.setCenter([avgLon, avgLat]);
                dgisMap.setZoom(7);
            } catch (e) {
                console.warn('[MapView] Не удалось центрировать карту 2ГИС:', e);
            }
        }
    }

    function renderLeaflet(results) {
        const medals = results.slice(0, 3);

        medals.forEach((ranked, i) => {
            const r = ranked.region;
            const size = 40 - i * 4;
            const color = RANK_COLORS[i] || '#888';

            const marker = L.marker([r.center.lat, r.center.lon], {
                icon: makeRankIcon(i + 1, color, size),
            });

            marker.bindTooltip(
                `<b>${r.name}</b><br>балл ${ranked.score.final_score.toFixed(3)} · ${ranked.site_and_network_mln.toFixed(1)} млн ₽ участок/сети`,
                {
                    permanent: true,
                    direction: 'top',
                    offset: [0, -size / 2 - 4],
                    className: 'pin-tooltip',
                }
            );

            marker.on('click', () => {
                if (window.App && App.selectRegion) {
                    App.selectRegion(r.id);
                }
            });

            leafletLayer.addLayer(marker);

            (r.alternative_sites || []).forEach(alt => {
                const altMarker = L.circleMarker([alt.lat, alt.lon], {
                    radius: 5,
                    color: color,
                    fillColor: color,
                    fillOpacity: 0.45,
                    weight: 1,
                });

                altMarker.bindTooltip(
                    `<b>${alt.name}</b><br>${alt.type}`,
                    {
                        direction: 'top',
                        className: 'pin-tooltip',
                    }
                );

                leafletLayer.addLayer(altMarker);
            });
        });

        if (results.length > 0) {
            const bounds = L.latLngBounds(
                results.map(item => [item.region.center.lat, item.region.center.lon])
            );

            leafletMap.fitBounds(bounds, {
                padding: [80, 80],
                maxZoom: 8,
            });
        }

        [100, 300, 800].forEach(delay => {
            setTimeout(() => {
                if (leafletMap) leafletMap.invalidateSize();
            }, delay);
        });
    }

    function render(top3, allRegions) {
        const results = top3 || [];

        if (!provider && !init()) {
            return;
        }

        clearMarkers();

        if (provider === '2gis' && dgisMap) {
            render2gis(results);
        } else {
            renderLeaflet(results);
        }
    }

    return {
        init,
        render,
    };
})();
