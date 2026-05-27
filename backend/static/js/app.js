/* Главная логика приложения */

const App = (() => {
    const cfg = window.APP_CONFIG;
    let state = {
        rankResponse: null,
        selectedRegionId: null,
        allRegions: [],
        autoRankTimer: null,
        dataStatus: null,
        verificationAbort: null,
        dataPanelClosed: false,
        selectedLayouts: {},
    };

    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => Array.from(document.querySelectorAll(sel));


    function defaultLayoutKey(region) {
        return window.Site3D?.defaultLayoutKey?.(region) || 'linear';
    }

    function currentLayoutKey(region) {
        return state.selectedLayouts[region.id] || window.Site3D?.getCurrentLayout?.(region.id) || defaultLayoutKey(region);
    }

    function layoutAwareUrl(basePath, region, extra = {}) {
        const params = new URLSearchParams(extra);
        params.set('layout', currentLayoutKey(region));
        if (!params.has('v')) params.set('v', Date.now().toString());
        return `${basePath}?${params.toString()}`;
    }

    function refreshLayoutBoundAssets(region) {
        const report = $('#report');
        if (!report || !region) return;
        const layout = currentLayoutKey(region);
        report.querySelectorAll('[data-layout-presentation]').forEach(a => {
            a.href = `/api/presentation/${region.id}.pptx?layout=${encodeURIComponent(layout)}&v=${Date.now()}`;
        });
        report.querySelectorAll('[data-layout-render-link]').forEach(a => {
            const name = a.dataset.renderName;
            a.href = `/api/renders/${region.id}/${name}.png?layout=${encodeURIComponent(layout)}&v=${Date.now()}`;
        });
        report.querySelectorAll('[data-layout-render-img]').forEach(img => {
            const name = img.dataset.renderName;
            img.src = `/api/renders/${region.id}/${name}.png?layout=${encodeURIComponent(layout)}&v=${Date.now()}`;
        });
        report.querySelectorAll('[data-layout-label]').forEach(node => {
            node.textContent = layoutLabel(layout);
        });
        report.querySelectorAll('[data-layout-plan-link]').forEach(a => {
            a.href = `/api/renders/${region.id}/site_plan.png?layout=${encodeURIComponent(layout)}&v=${Date.now()}`;
        });
        report.querySelectorAll('[data-layout-plan-img]').forEach(img => {
            img.src = `/api/renders/${region.id}/site_plan.png?layout=${encodeURIComponent(layout)}&v=${Date.now()}`;
        });
        populate3DRenderShots(region);
    }


    async function populate3DRenderShots(region) {
        const report = $('#report');
        if (!report || !region || !window.Site3D?.captureViews || !state.rankResponse) return;
        const ranked = (state.rankResponse.top3 || []).find(r => r.region.id === region.id);
        if (!ranked) return;
        const layout = currentLayoutKey(region);
        const cards = report.querySelectorAll('[data-render-shot]');
        cards.forEach(img => img.classList.add('is-loading'));
        try {
            const shots = await window.Site3D.captureViews(ranked, region, state.rankResponse.input_echo, layout);
            report.querySelectorAll('[data-layout-render-img]').forEach(img => {
                const name = img.dataset.renderName;
                if (shots[name]) img.src = shots[name];
                img.classList.remove('is-loading');
            });
            report.querySelectorAll('[data-layout-render-link]').forEach(a => {
                const name = a.dataset.renderName;
                if (shots[name]) {
                    a.href = shots[name];
                    a.setAttribute('download', `${region.id}_${name}.png`);
                }
            });
        } catch (e) {
            console.error('captureViews failed', e);
            cards.forEach(img => img.classList.remove('is-loading'));
        }
    }



    async function downloadPresentationWith3DShots(event, region) {
        event.preventDefault();
        const link = event.currentTarget;
        const originalHtml = link.innerHTML;
        link.classList.add('disabled');
        link.innerHTML = '<i class="ti ti-loader-2"></i> Готовлю PPTX...';
        try {
            const ranked = (state.rankResponse.top3 || []).find(r => r.region.id === region.id);
            if (!ranked || !window.Site3D?.captureViews) {
                window.open(link.href, '_blank');
                return;
            }
            const layout = currentLayoutKey(region);
            const shots = await window.Site3D.captureViews(ranked, region, state.rankResponse.input_echo, layout);
            const response = await fetch(`/api/presentation/${region.id}/from-shots.pptx?layout=${encodeURIComponent(layout)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ layout, shots }),
            });
            if (!response.ok) {
                let msg = `Ошибка ${response.status}`;
                try { msg = (await response.json()).detail || msg; } catch {}
                throw new Error(msg);
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `administration_presentation_${region.id}_3dshots.pptx`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 3000);
        } catch (e) {
            console.error(e);
            alert(`Не удалось собрать презентацию со скрин-рендерами: ${e.message}`);
            window.open(link.href, '_blank');
        } finally {
            link.classList.remove('disabled');
            link.innerHTML = originalHtml;
        }
    }

    function bindPresentationLinks(region) {
        const report = $('#report');
        if (!report) return;
        report.querySelectorAll('[data-layout-presentation]').forEach(link => {
            if (link.dataset.bound3dPresentation === '1') return;
            link.dataset.bound3dPresentation = '1';
            link.addEventListener('click', (event) => downloadPresentationWith3DShots(event, region));
        });
    }

    function layoutLabel(key) {
        const labels = {
            linear: 'Линейная схема',
            campus: 'Кампусная схема',
            logistics: 'Логистическая схема',
            compact: 'Компактная схема',
        };
        return labels[key] || key;
    }

    // ============================================================
    //  API
    // ============================================================
    async function api(path, opts = {}) {
        const r = await fetch(cfg.apiBase + path, {
            headers: { 'Content-Type': 'application/json' },
            ...opts,
        });
        if (!r.ok) {
            let msg = `Ошибка ${r.status}`;
            try { msg = (await r.json()).detail || msg; } catch {}
            throw new Error(msg);
        }
        return r.json();
    }

    // ============================================================
    //  Состояние подключения (health)
    // ============================================================
    async function checkHealth() {
        const elem = $('#health-status');
        try {
            const h = await api('/health');
            elem.classList.remove('err');
            elem.classList.add('ok');
            elem.querySelector('.status__text').textContent =
                `Подключено`;
            $('#region-count').textContent = h.regions_loaded;
        } catch (e) {
            elem.classList.add('err');
            elem.querySelector('.status__text').textContent = 'Бэк недоступен';
        }
    }

    async function loadAllRegions() {
        try { state.allRegions = await api('/regions'); } catch {}
    }

    // ============================================================
    //  Управление экранами
    // ============================================================
    function openForm() {
        $('#hero').hidden = true;
        $('#app').hidden = false;
    }
    function closeForm() {
        $('#app').hidden = true;
        $('#hero').hidden = false;
    }

    async function openDataPanel() {
        const panel = $('#data-panel');
        const body = $('#data-panel-content');
        if (!panel || !body) {
            console.error('[DataPanel] Не найден #data-panel или #data-panel-content');
            return;
        }
        state.dataPanelClosed = false;
        panel.hidden = false;
        panel.classList.add('is-open');
        body.innerHTML = `<div class="loading-box"><span class="loader"></span> Загружаю сведения об источниках…</div>`;
        try {
            await renderDataPanel();
        } catch (e) {
            console.error('[DataPanel] Ошибка открытия:', e);
            body.innerHTML = `<div class="data-panel__error">Не удалось загрузить вкладку базы данных: ${e.message || e}</div>`;
        }
    }

    function closeDataPanel() {
        const panel = $('#data-panel');
        if (!panel) return;
        state.dataPanelClosed = true;
        if (state.verificationAbort) {
            try { state.verificationAbort.abort(); } catch (e) {}
            state.verificationAbort = null;
        }
        panel.hidden = true;
        panel.classList.remove('is-open');
    }

    // ============================================================
    //  Чипсы: ограничения из ТЗ — благоустройство до 3, спорт до 2
    // ============================================================
    function bindCheckables() {
        const limits = { amenities: 3, sport_objects: 2 };
        $$('.chips--checkable').forEach(group => {
            const name = group.dataset.name;
            const limit = limits[name] || 99;
            const sync = () => {
                const checked = group.querySelectorAll('input[type=checkbox]:checked').length;
                group.querySelectorAll('input[type=checkbox]').forEach(inp => {
                    inp.disabled = !inp.checked && checked >= limit;
                });
                group.dataset.count = `${checked}/${limit}`;
            };
            group.addEventListener('change', sync);
            sync();
        });
    }

    // Блокировка типа жилья при 0%
    function bindHousingLock() {
        const pctGroup = document.querySelector('[data-name="housing_pct"]');
        if (!pctGroup) return;
        const sync = () => {
            const selected = pctGroup.querySelector('input:checked')?.value;
            const typeInputs = document.querySelectorAll('[data-name="housing_type"] input');
            typeInputs.forEach(inp => { inp.disabled = (selected === '0'); });
        };
        pctGroup.addEventListener('change', sync);
        sync();
    }

    // ============================================================
    //  Сборка payload из формы
    // ============================================================
    function collectFormData() {
        const f = $('#investor-form');
        const get = (name) => f.querySelector(`[name="${name}"]`);
        const getAll = (containerSel) => Array.from(
            document.querySelectorAll(`${containerSel} input:checked`)
        ).map(i => i.value);

        return {
            production_volume_kt: +get('production_volume_kt').value,
            employees: +get('employees').value,
            budget_mln_rub: +get('budget_mln_rub').value,
            needs_railway: f.querySelector('[name="needs_railway"]:checked').value === 'true',
            max_highway_km: +get('max_highway_km').value,
            arch_priority: f.querySelector('[name="arch_priority"]:checked').value,
            amenities: getAll('[data-name="amenities"]'),
            housing: {
                pct: +f.querySelector('[name="housing_pct"]:checked').value,
                type: f.querySelector('[name="housing_type"]:checked').value,
            },
            kindergarten_per_100: +f.querySelector('[name="kindergarten_per_100"]:checked').value,
            sport_objects: getAll('[data-name="sport_objects"]'),
        };
    }

    // ============================================================
    //  Сабмит → /api/rank
    // ============================================================

    function scheduleAutoRank() {
        const loaded = $('#results-loaded');
        if (!loaded || loaded.hidden || !state.rankResponse) return;
        clearTimeout(state.autoRankTimer);
        state.autoRankTimer = setTimeout(() => {
            onSubmit({ preventDefault: () => {} });
        }, 650);
    }

    async function onSubmit(e) {
        e.preventDefault();
        const payload = collectFormData();

        // Показываем зону результатов с лоадером
        const empty = $('#results-empty');
        if (empty) { empty.hidden = true; empty.style.display = 'none'; }
        const loaded = $('#results-loaded');
        loaded.hidden = false;
        $('#ranking').innerHTML = `<div class="loading-box"><span class="loader"></span> Анализирую площадки…</div>`;
        $('#report').hidden = true;

        try {
            state.rankResponse = await api('/rank', {
                method: 'POST', body: JSON.stringify(payload)
            });
        } catch (e) {
            $('#ranking').innerHTML = `<div class="loading-box" style="color:var(--brick);">${e.message}</div>`;
            return;
        }

        renderResultsSummary();
        renderRanking();
        renderComparison();
        renderMapMaybe();
        if (state.rankResponse.top3.length > 0) {
            selectRegion(state.rankResponse.top3[0].region.id);
        }
    }

    // ============================================================
    //  Рендер ранжирования
    // ============================================================
    function renderRanking() {
        const ranking = $('#ranking');
        const results = state.rankResponse.top3;
        const medals = results.slice(0, 3);

        const medalsHtml = medals.map((r, i) => {
            const bonuses = (r.score.bonuses || []).slice(0, 3).map(b =>
                `<span class="badge"><i class="ti ti-sparkles"></i> ${b}</span>`
            ).join('');
            const reason = r.selection_reason ?
                `<div class="region-card__reason">${r.selection_reason}</div>` : '';
            const ai = r.ai_object_analysis
                ? r.ai_object_analysis.split('. ').slice(0, 1).join('. ') + '.'
                : '';
            return `
                <div class="region-card rank-${i+1}" data-id="${r.region.id}">
                    <div class="region-card__rank">${i + 1}</div>
                    <div class="region-card__body">
                        <div class="region-card__name">${r.region.name}</div>
                        <div class="region-card__subject"><i class="ti ti-map"></i> ${r.region.federal_subject || 'субъект РФ не указан'}</div>
                        <div class="region-card__stats">
                            <span>Балл <b>${(r.score.final_score * 100).toFixed(1)}</b></span>
                            <span>Смета <b>${r.estimate.total_mln.toFixed(0)} млн ₽</b></span>
                            <span>Мощн. <b>${r.region.infrastructure.free_power_kva} кВА</b></span>
                        </div>
                        ${reason}
                        ${ai ? `<div class="region-card__ai"><i class="ti ti-sparkles"></i> ${ai}</div>` : ''}
                        ${bonuses ? `<div class="region-card__bonuses">${bonuses}</div>` : ''}
                    </div>
                </div>`;
        }).join('');

        ranking.innerHTML = medalsHtml;

        ranking.querySelectorAll('.region-card').forEach(card => {
            card.addEventListener('click', () => selectRegion(card.dataset.id));
        });
    }

    function renderMapMaybe() {
        MapView.render(state.rankResponse.top3, state.allRegions);
    }

    function formatDataStatus(status) {
        const map = {
            official_verified: 'Подтверждено источником',
            official_stat: 'Официальная статистика',
            imported_official: 'Импортировано',
            registry_verified: 'Сверено с реестром',
            calculated_from_verified: 'Рассчитано автоматически',
            tariff_estimate: 'Тарифная оценка',
            market_stat_estimate: 'Рыночная оценка',
            data_confirmed: 'Автоматически сверено',
            real_object: 'Объект найден',
            partially_verified: 'Частично сверено',
            official_name_demo_metrics: 'Объект найден, метрики оценочные',
            demo_estimate: 'Оценка MVP',
            needs_review: 'Нужна ручная проверка',
            demo: 'Оценка MVP',
            "official_stat_avg_2023_2025": "Официальная статистика, среднее за 2023–2025",
            "official_stat_or_municipal_estimate": "Официальная/муниципальная оценка",
            "market_stat_estimate_2023_2025": "Рыночная оценка, 2023–2025",
            "regional_tariff_estimate_2023_2025": "Региональная тарифная оценка, 2023–2025",
            "manual_review_required": "Нужна ручная проверка",
            "source_confirmed": "Подтверждено источником",
            "registry_confirmed": "Сверено с реестром",
            "auto_calculated": "Рассчитано автоматически",
        };
        if (map[status]) return map[status];
        if (!status) return 'Оценка MVP';
        return String(status)
            .replace(/_/g, ' ')
            .replace('official stat avg 2023 2025', 'Официальная статистика, среднее за 2023–2025')
            .replace('market stat estimate 2023 2025', 'Рыночная оценка, 2023–2025')
            .replace('regional tariff estimate 2023 2025', 'Региональная тарифная оценка, 2023–2025')
            .replace('official stat or municipal estimate', 'Официальная/муниципальная оценка');
    }

    function dataStatusTitle(status) {
        const map = {
            official_verified: 'Все ключевые сведения по этому блоку подтверждены официальным источником.',
            official_stat: 'Показатель относится к официальной статистике.',
            imported_official: 'Показатель импортирован из официальной таблицы/выгрузки.',
            registry_verified: 'Показатель сверен с реестровым или региональным источником.',
            calculated_from_verified: 'Показатель рассчитан автоматически на основе проверенных координат или карточки объекта.',
            tariff_estimate: 'Показатель является тарифной оценкой и требует уточнения у сетевой организации.',
            market_stat_estimate: 'Показатель является рыночной/статистической оценкой.',
            partially_verified: 'Объект найден в открытых источниках, но часть инженерных и экономических показателей требует сверки.',
            official_name_demo_metrics: 'Название и статус объекта подтверждаются, но часть числовых метрик используется как демо-оценка.',
            demo_estimate: 'Демонстрационная оценка MVP, требуется сверка перед промышленным использованием.',
            needs_review: 'Показатель требует ручной проверки по региональным источникам.',
            official_stat_avg_2023_2025: 'Значение нормализовано по официальной статистике за 2023–2025 годы.',
            official_stat_or_municipal_estimate: 'Значение основано на официальной статистике или муниципальной оценке.',
            market_stat_estimate_2023_2025: 'Значение рассчитано как рыночная оценка по открытым данным за 2023–2025 годы.',
            regional_tariff_estimate_2023_2025: 'Значение является региональной тарифной оценкой за 2023–2025 годы.',
            manual_review_required: 'Показатель требует ручной проверки.',
            source_confirmed: 'Показатель подтверждён источником.',
            registry_confirmed: 'Показатель сверен с реестром.',
            auto_calculated: 'Показатель рассчитан автоматически.',

        };
        return map[status] || 'Статус качества данных.';
    }

    function coordLinks(region) {
        const lat = Number(region.center.lat).toFixed(6);
        const lon = Number(region.center.lon).toFixed(6);
        const yandex = `https://yandex.ru/maps/?ll=${lon}%2C${lat}&z=16&pt=${lon}%2C${lat},pm2rdm&text=${lat}%2C${lon}`;
        const dgis = `https://2gis.ru/search/${lat}%2C%20${lon}?m=${lon}%2C${lat}%2F16`;
        return { lat, lon, yandex, dgis };
    }


    // ============================================================
    //  Верхняя сводка и сравнение — чтобы пользователь сразу понял результат
    // ============================================================
    function renderResultsSummary() {
        const box = $('#results-summary');
        if (!box || !state.rankResponse) return;
        const inp = state.rankResponse.input_echo;
        const top = state.rankResponse.top3[0];
        const bestPowerReserve = top.region.infrastructure.free_power_kva - top.required_power_kva;
        const budgetOk = top.site_and_network_mln <= inp.budget_mln_rub;
        box.innerHTML = `
            <div class="summary-card summary-card--accent">
                <div class="summary-card__label">Лучший вариант</div>
                <div class="summary-card__value">${top.region.name}</div>
                <div class="summary-card__sub">${top.region.federal_subject || 'регион не указан'} · балл ${top.score.final_score.toFixed(3)}</div>
            </div>
            <div class="summary-card">
                <div class="summary-card__label">Проект</div>
                <div class="summary-card__value">${inp.production_volume_kt} тыс. м²</div>
                <div class="summary-card__sub">${inp.employees} сотрудников · ${inp.needs_railway ? 'ж/д нужна' : 'без обязательной ж/д'}</div>
            </div>
            <div class="summary-card ${budgetOk ? 'summary-card--ok' : 'summary-card--warn'}">
                <div class="summary-card__label">Участок и сети</div>
                <div class="summary-card__value">${top.site_and_network_mln.toFixed(1)} млн ₽</div>
                <div class="summary-card__sub">бюджет ${inp.budget_mln_rub} млн ₽ · ${budgetOk ? 'укладывается' : 'нужна корректировка'}</div>
            </div>
            <div class="summary-card">
                <div class="summary-card__label">Запас мощности лидера</div>
                <div class="summary-card__value">${bestPowerReserve} кВА</div>
                <div class="summary-card__sub">свободно ${top.region.infrastructure.free_power_kva} кВА, нужно ~${top.required_power_kva} кВА</div>
            </div>
        `;
    }

    function renderComparison() {
        const box = $('#comparison');
        if (!box || !state.rankResponse) return;
        const rows = state.rankResponse.top3.map((r, i) => `
            <tr data-id="${r.region.id}">
                <td class="cmp-rank"><b>#${i + 1}</b></td>
                <td class="cmp-name">
                    <button type="button" class="link-btn" data-id="${r.region.id}">${r.region.name}</button>
                    <small class="cmp-subject">${r.region.federal_subject || ''}</small>
                </td>
                <td class="cmp-score">${(r.score.final_score * 100).toFixed(1)}</td>
                <td class="cmp-road">${r.region.logistics.federal_highway_km} км</td>
                <td class="cmp-rail">${r.region.logistics.railway_available ? 'есть' : 'нет'}</td>
                <td class="cmp-power">${r.region.infrastructure.free_power_kva} кВА</td>
                <td class="cmp-budget">${r.site_and_network_mln.toFixed(1)} млн ₽</td>
                <td class="cmp-status"><span class="status-pill" title="${dataStatusTitle(r.region.data_quality?.status || 'demo')}">${formatDataStatus(r.region.data_quality?.status || 'demo')}</span></td>
            </tr>
        `).join('');
        box.innerHTML = `
            <div class="comparison-panel__head">
                <div>
                    <p class="eyebrow"><i class="ti ti-table"></i> Сравнение вариантов</p>
                    <h3>Почему эти три объекта попали в подбор</h3>
                </div>
                <div class="comparison-note">Нажмите на название площадки, чтобы открыть подробный анализ ниже.</div>
            </div>
            <div class="table-wrap table-wrap--compare">
                <table class="compare-table">
                    <colgroup>
                        <col class="col-rank">
                        <col class="col-name">
                        <col class="col-score">
                        <col class="col-road">
                        <col class="col-rail">
                        <col class="col-power">
                        <col class="col-budget">
                        <col class="col-status">
                    </colgroup>
                    <thead>
                        <tr>
                            <th class="cmp-rank">Место</th>
                            <th class="cmp-name">Площадка</th>
                            <th class="cmp-score">Балл</th>
                            <th class="cmp-road">Трасса</th>
                            <th class="cmp-rail">Ж/д</th>
                            <th class="cmp-power">Мощность</th>
                            <th class="cmp-budget">Участок/сети</th>
                            <th class="cmp-status">Статус данных</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
        box.querySelectorAll('.link-btn').forEach(btn => {
            btn.addEventListener('click', () => selectRegion(btn.dataset.id));
        });
    }



    // ============================================================
    //  Быстрые сценарии демо
    // ============================================================
    const PRESETS = {
        balanced: {
            production_volume_kt: 500,
            employees: 80,
            budget_mln_rub: 150,
            needs_railway: true,
            max_highway_km: 20,
            arch_priority: 'authenticity',
            amenities: ['alley', 'square'],
            housing_pct: 30,
            housing_type: 'dormitory',
            kindergarten_per_100: 30,
            sport_objects: ['outdoor_gym', 'stadium'],
        },
        large: {
            production_volume_kt: 900,
            employees: 160,
            budget_mln_rub: 260,
            needs_railway: true,
            max_highway_km: 35,
            arch_priority: 'techno',
            amenities: ['alley', 'square', 'health_trail'],
            housing_pct: 50,
            housing_type: 'apartment',
            kindergarten_per_100: 50,
            sport_objects: ['stadium', 'gym'],
        },
        social: {
            production_volume_kt: 350,
            employees: 120,
            budget_mln_rub: 180,
            needs_railway: false,
            max_highway_km: 25,
            arch_priority: 'eco',
            amenities: ['alley', 'square', 'pond'],
            housing_pct: 70,
            housing_type: 'dormitory',
            kindergarten_per_100: 50,
            sport_objects: ['outdoor_gym', 'stadium'],
        },
    };

    function setRangeValue(form, name, value) {
        const input = form.querySelector(`[name="${name}"]`);
        if (!input) return;
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function setRadioValue(form, name, value) {
        const input = form.querySelector(`[name="${name}"][value="${String(value)}"]`);
        if (!input) return;
        input.checked = true;
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function setCheckboxGroup(groupName, values) {
        const allowed = new Set((values || []).map(String));
        const group = document.querySelector(`[data-name="${groupName}"]`);
        if (!group) return;
        group.querySelectorAll('input[type="checkbox"]').forEach(input => {
            input.disabled = false;
            input.checked = allowed.has(input.value);
            input.dispatchEvent(new Event('change', { bubbles: true }));
        });
        group.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function updatePresetButtons(activePreset) {
        document.querySelectorAll('[data-preset]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.preset === activePreset);
        });
    }

    function applyPreset(name) {
        const preset = PRESETS[name];
        const form = $('#investor-form');
        if (!preset || !form) return;

        clearTimeout(state.autoRankTimer);
        updatePresetButtons(name);

        setRangeValue(form, 'production_volume_kt', preset.production_volume_kt);
        setRangeValue(form, 'employees', preset.employees);
        setRangeValue(form, 'budget_mln_rub', preset.budget_mln_rub);
        setRangeValue(form, 'max_highway_km', preset.max_highway_km);

        setRadioValue(form, 'needs_railway', preset.needs_railway);
        setRadioValue(form, 'arch_priority', preset.arch_priority);
        setRadioValue(form, 'housing_pct', preset.housing_pct);
        setRadioValue(form, 'housing_type', preset.housing_type);
        setRadioValue(form, 'kindergarten_per_100', preset.kindergarten_per_100);

        setCheckboxGroup('amenities', preset.amenities);
        setCheckboxGroup('sport_objects', preset.sport_objects);

        const housingGroup = document.querySelector('[data-name="housing_pct"]');
        if (housingGroup) housingGroup.dispatchEvent(new Event('change', { bubbles: true }));

        onSubmit({ preventDefault: () => {} });
    }

    function bindPresets() {
        document.querySelectorAll('[data-preset]').forEach(btn => {
            btn.addEventListener('click', (e) => { e.preventDefault(); applyPreset(btn.dataset.preset); });
        });
    }

    // ============================================================
    //  Выбор региона → загрузка справки
    // ============================================================
    async function selectRegion(regionId) {
        state.selectedRegionId = regionId;
        $$('.region-card').forEach(c => c.classList.toggle('selected', c.dataset.id === regionId));

        const report = $('#report');
        report.hidden = false;
        report.innerHTML = `<div class="loading-box"><span class="loader"></span> Готовлю аналитическую справку…</div>`;

        try {
            const detail = await api(`/region/${regionId}/brief`);
            const ranked = state.rankResponse.top3.find(r => r.region.id === regionId);
            const budget = state.rankResponse.input_echo.budget_mln_rub;
            renderReport(detail, ranked, budget);
        } catch (e) {
            report.innerHTML = `<div class="loading-box" style="color:var(--brick);">${e.message}</div>`;
        }
    }

    // ============================================================
    //  Рендер отчёта
    // ============================================================

    // ============================================================
    //  v44: пакет инвестора, риски, документы, методика, защита
    // ============================================================
    function riskItems(region, ranked, inp) {
        const risks = [];
        const infra = region.infrastructure || {};
        const log = region.logistics || {};
        const social = region.social || {};
        const economy = region.economy || {};
        const requiredPower = ranked.required_power_kva || 0;
        if ((infra.free_power_kva || 0) < requiredPower * 1.15) risks.push(['Электроснабжение', 'Небольшой запас свободной мощности: нужно запросить подтверждение мощности и ТУ у сетевой организации.']);
        if (!infra.gas_available) risks.push(['Газоснабжение', 'Газ не подтверждён как доступный: нужно запросить схему газоснабжения или технические условия.']);
        if (inp.needs_railway && !log.railway_available) risks.push(['Ж/д логистика', 'Инвестор указал потребность в ж/д, но по площадке ж/д доступ не подтверждён.']);
        if ((log.federal_highway_km || 999) > inp.max_highway_km) risks.push(['Автологистика', 'Расстояние до федеральной трассы выше заданного лимита инвестора.']);
        if (ranked.site_and_network_mln > inp.budget_mln_rub) risks.push(['Бюджет', 'Расходы на участок и сети превышают заданный бюджет: нужна оптимизация состава проекта.']);
        if ((social.kindergarten_per_100 || 0) < inp.kindergarten_per_100) risks.push(['Социальная инфраструктура', 'Показатель обеспеченности детскими садами ниже пожеланий инвестора.']);
        if (!economy.has_oez_tor) risks.push(['Льготы', 'Не подтверждён режим ОЭЗ/ТОР: нужно уточнить доступные меры поддержки.']);
        if (!risks.length) risks.push(['Ограничения не критичны', 'По текущей модели площадка проходит основные ограничения; требуется только стандартная документальная сверка.']);
        return risks;
    }

    function docsToRequest(region, ranked, inp) {
        const docs = [
            'Официальный паспорт промышленной площадки с кадастровыми и инженерными параметрами.',
            'Правоустанавливающие документы или выписка по земельному участку.',
            'Технические условия на электроснабжение и подтверждение свободной мощности.',
            'Технические условия на газоснабжение или письмо о возможности подключения.',
            'Подтверждение ж/д доступа / схемы подъездных путей, если логистика требует ж/д.',
            'Расчёт стоимости технологического присоединения и сроков подключения.',
            'Перечень региональных мер поддержки, льгот, налоговых режимов и требований к резиденту.',
            'Градостроительный план земельного участка, ПЗЗ, санитарные ограничения и красные линии.',
            'Контакты управляющей компании / оператора площадки и порядок подачи заявки инвестора.'
        ];
        return docs;
    }

    function renderRiskPanel(region, ranked, inp) {
        const risks = riskItems(region, ranked, inp);
        return `
            <div class="section-title"><i class="ti ti-alert-triangle"></i> Риски и ограничения площадки</div>
            <div class="risk-grid">
                ${risks.map(([title, text]) => `
                    <div class="risk-card">
                        <div class="risk-card__title">${title}</div>
                        <p>${text}</p>
                        <div class="risk-card__mitigation"><i class="ti ti-shield-check"></i> Мера: запросить подтверждающий документ и обновить статус поля в базе.</div>
                    </div>`).join('')}
            </div>`;
    }

    function renderRequestDocsPanel(region, ranked, inp) {
        return `
            <div class="section-title"><i class="ti ti-mail-forward"></i> Что запросить у региона / управляющей компании</div>
            <div class="docs-request">
                ${docsToRequest(region, ranked, inp).map((d, i) => `<div class="docs-request__row"><b>${i + 1}</b><span>${d}</span></div>`).join('')}
            </div>
            <div class="data-note"><i class="ti ti-info-circle"></i> Этот список автоматически формируется по выбранной площадке и закрывает поля, которые нельзя честно подтвердить без паспорта площадки или ТУ.</div>`;
    }

    function comparisonChartHtml() {
        if (!state.rankResponse?.top3?.length) return '';
        const metrics = [
            ['logistics', 'Логистика'], ['infrastructure', 'Сети'], ['economy', 'Экономика'], ['social', 'Социальная инфраструктура']
        ];
        const avgScore = (score) => {
            const vals = metrics.map(([key]) => Number(score[key] || 0));
            return vals.reduce((a, b) => a + b, 0) / vals.length;
        };
        return `
            <div class="section-title"><i class="ti ti-chart-bar"></i> Визуальное сравнение ТОП-3</div>
            <div class="data-note"><i class="ti ti-info-circle"></i> Для сравнения используется шкала 0–100. Средний балл — это четыре базовых критерия, рейтинг модели — средний балл с ограниченными бонусами за условия инвестора и льготные режимы.</div>
            <div class="score-chart">
                ${state.rankResponse.top3.map((r, idx) => {
                    const avg = avgScore(r.score);
                    const modelPts = Number(r.score.final_score || 0) * 100;
                    return `
                    <div class="score-chart__item" data-id="${r.region.id}">
                        <div class="score-chart__head"><b>#${idx + 1} ${r.region.name}</b><span>рейтинг ${modelPts.toFixed(1)} / 100 · среднее ${(avg * 100).toFixed(1)} / 100</span></div>
                        ${metrics.map(([key, label]) => {
                            const raw = Number(r.score[key] || 0);
                            const pct = Math.max(4, Math.min(100, raw * 100));
                            return `<div class="score-line"><span>${label}</span><i style="--w:${pct}%"></i><b>${(raw * 100).toFixed(0)}</b></div>`;
                        }).join('')}
                        <div class="score-line score-line--avg"><span>Среднее</span><i style="--w:${Math.max(4, Math.min(100, avg * 100))}%"></i><b>${(avg * 100).toFixed(1)}</b></div>
                    </div>`;
                }).join('')}
            </div>`;
    }

    function methodologyHtml() {
        return `
            <div class="section-title"><i class="ti ti-calculator"></i> Методика расчёта рейтинга</div>
            <div class="methodology-grid">
                <div class="method-card"><b>Логистика</b><span>Учитываются расстояние до трассы, ж/д доступ и близость поставщиков сырья.</span></div>
                <div class="method-card"><b>Инженерные сети</b><span>Проверяются свободная мощность, газ, подстанция и стоимость подключения.</span></div>
                <div class="method-card"><b>Экономика</b><span>Сравниваются льготы, тарифы, зарплаты, стоимость участка и сетей.</span></div>
                <div class="method-card"><b>Социальная среда</b><span>Оцениваются жильё, детсады, колледжи, спорт и удержание персонала.</span></div>
                <div class="method-card"><b>Ограничения инвестора</b><span>Площадка получает штрафы, если нарушает бюджет, трассу, ж/д или социальный пакет.</span></div>
                <div class="method-card"><b>Качество данных</b><span>Каждое поле имеет статус: источник, статистика, расчёт или ручная проверка.</span></div>
            </div>
            <div class="formula-card"><b>Итоговый балл</b><span>формируется как взвешенная сумма логистики, сетей, экономики, социальной среды и соответствия параметрам инвестора.</span></div>`;
    }

    function verificationHistoryHtml() {
        const v = state.verificationStatus || {};
        const rows = (v.results || []).slice(0, 8).map(item => `
            <tr><td>${item.name}</td><td>${formatVerificationStatus(item.status)}</td><td>${item.verified_fields || 0}</td><td>${item.needs_review_fields || 0}</td></tr>
        `).join('');
        return `
            <div class="section-title"><i class="ti ti-history"></i> История проверок данных</div>
            <div class="data-quality ok">
                <div class="data-quality__title">Последняя проверка: ${v.last_update || 'ещё не запускалась'}</div>
                <div class="data-quality__note">Режим: ${v.verification_mode || v.mode || 'не указан'} · площадок: ${v.total || 0} · автоматически сверено: ${v.data_confirmed || 0}.</div>
            </div>
            <div class="table-wrap"><table class="quality-table"><thead><tr><th>Площадка</th><th>Статус</th><th>Сверено</th><th>Проверить</th></tr></thead><tbody>${rows || '<tr><td colspan="4">История появится после запуска проверки.</td></tr>'}</tbody></table></div>`;
    }

    function defenseModeHtml(region, ranked, brief, inp) {
        const risks = riskItems(region, ranked, inp);
        return `
            <div class="defense-board">
                <div class="defense-hero">
                    <p class="eyebrow"><i class="ti ti-presentation"></i> Режим защиты</p>
                    <h2>Инвестподбор площадки: от параметров проекта до пакета документов</h2>
                    <p>Система выбирает подходящую промышленную площадку, объясняет выбор, показывает макет предприятия и формирует документы для руководителя/инвестора.</p>
                </div>
                <div class="defense-steps">
                    <div><b>1</b><span>Ввод параметров производства</span></div>
                    <div><b>2</b><span>Расчёт ТОП-3 площадок</span></div>
                    <div><b>3</b><span>Проверка данных и источников</span></div>
                    <div><b>4</b><span>Макет, 3D и рендеры</span></div>
                    <div><b>5</b><span>Паспорт, отчёт и пакет инвестора</span></div>
                </div>
                <div class="defense-result">
                    <div><span>Рекомендуемая площадка</span><b>${region.name}</b></div>
                    <div><span>Итоговый балл</span><b>${(ranked.score.final_score * 100).toFixed(1)} / 100</b></div>
                    <div><span>Участок/сети</span><b>${ranked.site_and_network_mln.toFixed(1)} млн ₽</b></div>
                    <div><span>Главный риск</span><b>${risks[0]?.[0] || 'стандартная проверка'}</b></div>
                </div>
            </div>`;
    }

    function renderReport(detail, ranked, budget) {
        const region = detail.region;
        const brief = detail.brief;
        const figure = (region.culture.historical_figures || [])[0];
        const selectedLayout = currentLayoutKey(region);

        const figureHtml = figure ? `
            <div class="figure-card">
                <div class="figure-card__icon"><i class="ti ti-history"></i></div>
                <div>
                    <div class="figure-card__name">${figure.name}</div>
                    <div class="figure-card__meta">${figure.role} · ${figure.era}</div>
                    <div class="figure-card__hint">${figure.design_hint}</div>
                </div>
            </div>` : '';

        const s = ranked.score;
        const e = ranked.estimate;
        const a = ranked.areas;

        const siteBudget = ranked.site_and_network_mln ?? e.infrastructure_mln + e.amenities_mln;
        const delta = budget - siteBudget;
        const inBudget = delta >= 0;

        const reasonHtml = ranked.selection_reason ? `
            <div class="reason-card">
                <div class="reason-card__icon"><i class="ti ti-bulb"></i></div>
                <div>
                    <div class="reason-card__label">Почему выбрана эта площадка</div>
                    <div class="reason-card__text">${ranked.selection_reason}</div>
                </div>
            </div>` : '';

        const pros = (ranked.pros || []).map(p =>
            `<li><i class="ti ti-circle-check-filled" style="color:var(--teal);"></i> ${p}</li>`
        ).join('');
        const cons = (ranked.cons || []).map(c =>
            `<li><i class="ti ti-alert-circle-filled" style="color:var(--brick);"></i> ${c}</li>`
        ).join('');

        const prosConsHtml = `
            <div class="proscons">
                <div class="proscons__col">
                    <div class="proscons__title proscons__title--pro">
                        <i class="ti ti-thumb-up-filled"></i> Плюсы площадки
                    </div>
                    <ul class="proscons__list">${pros || '<li class="proscons__empty">Существенных плюсов не обнаружено.</li>'}</ul>
                </div>
                <div class="proscons__col">
                    <div class="proscons__title proscons__title--con">
                        <i class="ti ti-thumb-down-filled"></i> Минусы площадки
                    </div>
                    <ul class="proscons__list">${cons || '<li class="proscons__empty">Существенных минусов не обнаружено.</li>'}</ul>
                </div>
            </div>`;

        const altSites = region.alternative_sites || [];
        const altCount = altSites.length;
        const altCards = altSites.map((alt, idx) => `
            <div class="alt-card">
                <div class="alt-card__head">
                    <div class="alt-card__num">${idx + 1}</div>
                    <div>
                        <div class="alt-card__name">${alt.name}</div>
                        <div class="alt-card__type"><i class="ti ti-map-pin"></i> ${alt.type}</div>
                    </div>
                </div>
                <div class="alt-card__desc">${alt.description}</div>
                <div class="alt-card__coords">
                    <i class="ti ti-pin"></i> ${alt.lat.toFixed(4)}, ${alt.lon.toFixed(4)}
                </div>
            </div>`).join('');

        const dataSources = region.data_sources || [];
        const quality = region.data_quality || {};
        const qualityRows = Object.entries(quality.quality_by_field || {}).map(([key, value]) => `
            <tr>
                <td>${qualityLabel(key)}</td>
                <td><span class="quality-pill quality-pill--${String(value).replaceAll('_','-')}">${qualityStatusLabel(value)}</span></td>
            </tr>
        `).join('');
        const sourcesHtml = `
            <div class="data-quality ${String(quality.status || '').includes('verified') ? 'ok' : 'warn'}">
                <div class="data-quality__title"><i class="ti ti-database-search"></i> Статус данных: ${qualityStatusLabel(quality.status || 'demo_estimate')}</div>
                <div class="data-quality__note">${quality.note || 'Для MVP данные используются как демонстрационная витрина и требуют сверки с первоисточниками.'}</div>
                ${quality.last_verified ? `<div class="data-quality__note"><b>Последняя сверка:</b> ${quality.last_verified}</div>` : ''}
            </div>
            <div class="section-title"><i class="ti ti-list-check"></i> Качество по показателям</div>
            <div class="table-wrap">
                <table class="quality-table">
                    <thead><tr><th>Показатель</th><th>Статус</th></tr></thead>
                    <tbody>${qualityRows || '<tr><td colspan="2">Статусы по показателям пока не заданы.</td></tr>'}</tbody>
                </table>
            </div>
            <div class="section-title"><i class="ti ti-link"></i> Источники сверки</div>
            <div class="source-grid">
                ${dataSources.map(src => `
                    <a class="source-card" href="${src.url}" target="_blank" rel="noopener">
                        <div class="source-card__group">${src.group}</div>
                        <div class="source-card__title">${src.title}</div>
                        <div class="source-card__comment">${src.comment || ''}</div>
                    </a>
                `).join('') || '<div class="prose"><p>Источники для этой площадки не указаны.</p></div>'}
            </div>`;

        $('#report').innerHTML = `
            <div class="report__head">
                <h1 class="report__name">${region.name}</h1>
                <div class="report__loc">
                    <i class="ti ti-map-pin"></i>
                    ${region.federal_subject || 'субъект РФ не указан'} · координаты ${region.center.lat.toFixed(3)}, ${region.center.lon.toFixed(3)}
                </div>
                <details class="report-actions" open>
                    <summary><i class="ti ti-menu-2"></i> Документы, паспорт и карты</summary>
                    <div class="map-links map-links--stacked">
                        ${(() => {
                            const links = coordLinks(region);
                            return `
                                <a href="${links.yandex}" target="_blank" rel="noopener" title="Открыть точку по координатам ${links.lat}, ${links.lon}"><i class="ti ti-external-link"></i> Яндекс.Карты · точка</a>
                                <a href="${links.dgis}" target="_blank" rel="noopener" title="Открыть поиск 2ГИС по координатам ${links.lat}, ${links.lon}"><i class="ti ti-external-link"></i> 2ГИС · координаты</a>
                            `;
                        })()}
                        <a href="/api/report/${region.id}.docx" target="_blank" rel="noopener" class="map-links__primary"><i class="ti ti-file-type-docx"></i> Скачать Word-отчёт</a>
                        <a href="/api/passport/${region.id}.docx" target="_blank" rel="noopener" class="map-links__primary map-links__primary--passport"><i class="ti ti-file-certificate"></i> Скачать официальный паспорт</a>
                        <a href="/api/presentation/${region.id}.pptx?layout=${selectedLayout}&v=${Date.now()}" data-layout-presentation="1" target="_blank" rel="noopener" class="map-links__primary"><i class="ti ti-presentation"></i> Скачать презентацию</a>
                        <a href="/api/investor-package/${region.id}.zip?layout=${selectedLayout}&v=${Date.now()}" target="_blank" rel="noopener" class="map-links__primary map-links__primary--package"><i class="ti ti-package-export"></i> Скачать пакет инвестора ZIP</a>
                    </div>
                </details>
            </div>

            ${reasonHtml}
            ${figureHtml}

            <div class="report__tabs">
                <button class="report__tab active" data-tab="overview">Обзор</button>
                <button class="report__tab" data-tab="proscons">Плюсы и минусы</button>
                <button class="report__tab" data-tab="methodology">Методика</button>
                <button class="report__tab" data-tab="alternatives">Альтернативы ${altCount ? `<span class="tab__count">${altCount}</span>` : ''}</button>
                <button class="report__tab" data-tab="estimate">Смета</button>
                <button class="report__tab" data-tab="layout">Макет</button>
                <button class="report__tab" data-tab="3d">3D-модель</button>
                <button class="report__tab" data-tab="design">Дизайн</button>
                <button class="report__tab" data-tab="renders">Рендеры</button>
                <button class="report__tab" data-tab="sources">Источники</button>
            </div>

            <div class="tab-panel active" data-panel="overview">
                <div class="section-title"><i class="ti ti-chart-radar"></i> Разбивка оценки</div>
                ${(() => {
                    const baseAvg = (Number(s.logistics || 0) + Number(s.infrastructure || 0) + Number(s.economy || 0) + Number(s.social || 0)) / 4;
                    const modelPts = Number(s.final_score || 0) * 100;
                    const basePts = baseAvg * 100;
                    const bonusDelta = modelPts - basePts;
                    return `
                    <div class="metrics metrics--score">
                        <div class="metric metric--model"><div class="metric__label">Рейтинг модели</div><div class="metric__value">${modelPts.toFixed(1)} / 100</div><div class="metric__hint">базовая оценка + ограниченные бонусы</div></div>
                        <div class="metric"><div class="metric__label">Средний балл критериев</div><div class="metric__value">${basePts.toFixed(1)} / 100</div><div class="metric__hint">логистика + сети + экономика + социальная инфраструктура</div></div>
                        <div class="metric"><div class="metric__label">Логистика</div><div class="metric__value">${(s.logistics * 100).toFixed(0)} / 100</div></div>
                        <div class="metric"><div class="metric__label">Экономика</div><div class="metric__value">${(s.economy * 100).toFixed(0)} / 100</div></div>
                        <div class="metric"><div class="metric__label">Сети</div><div class="metric__value">${(s.infrastructure * 100).toFixed(0)} / 100</div></div>
                        <div class="metric"><div class="metric__label">Социальная инфраструктура</div><div class="metric__value">${(s.social * 100).toFixed(0)} / 100</div></div>
                    </div>
                    <div class="score-explain">
                        <i class="ti ti-info-circle"></i>
                        <span><b>Как считается рейтинг?</b> Средний балл — это простое среднее четырёх критериев. Рейтинг модели дополнительно учитывает бюджет, требования инвестора, ОЭЗ/ТОР, страховые льготы и сценарные корректировки. Бонусы ограничены, поэтому рейтинг больше не должен превращаться в искусственные 1.000. Текущая корректировка: ${bonusDelta >= 0 ? '+' : ''}${bonusDelta.toFixed(1)} балла.</span>
                    </div>`;
                })()}

                ${comparisonChartHtml()}

                <div class="narrative">${brief.intro_narrative}</div>

                <div class="section-title"><i class="ti ti-sparkles"></i> ИИ-анализ конкретного объекта</div>
                <div class="ai-box"><p>${brief.site_specific_analysis || ranked.ai_object_analysis}</p></div>

                <div class="section-title"><i class="ti ti-building-arch"></i> Архитектурный концепт</div>
                <div class="prose"><p>${brief.design_concept}</p></div>

                <div class="section-title"><i class="ti ti-users"></i> Удержание персонала</div>
                <div class="prose"><p>${brief.hr_retention_tips}</p></div>

                ${collapsibleHtml('Социальный паспорт', brief.social_passport)}
                ${collapsibleHtml('Экономика', brief.economy_summary)}
                ${collapsibleHtml('Сетевая инфраструктура', brief.infrastructure_summary)}
                ${collapsibleHtml('Логистика сырья', brief.logistics_summary)}
            </div>

            <div class="tab-panel" data-panel="proscons">
                <div class="section-title"><i class="ti ti-scale"></i> Что хорошо и что плохо</div>
                ${prosConsHtml}
            </div>
<div class="tab-panel" data-panel="methodology">
                ${methodologyHtml()}
            </div>
<div class="tab-panel" data-panel="alternatives">
                <div class="section-title"><i class="ti ti-map-pins"></i> Альтернативные точки в городе</div>
                <div class="prose"><p>Кроме основной координаты площадки, в этом городе доступны ${altCount} альтернативные локации. Каждая со своим профилем плюсов и минусов — пригодится если основная по какой-то причине не подойдёт.</p></div>
                <div class="alt-grid">${altCards}</div>
            </div>

            <div class="tab-panel" data-panel="sources">
                <div class="section-title"><i class="ti ti-database-search"></i> Источники и качество данных</div>
                ${verificationHistoryHtml()}
                ${sourcesHtml}
            </div>

            <div class="tab-panel" data-panel="estimate">
                <div class="section-title"><i class="ti ti-ruler-measure"></i> Площади</div>
                <div class="metrics">
                    <div class="metric"><div class="metric__label">Цех</div><div class="metric__value">${a.workshop_m2.toFixed(0)}</div><div class="metric__sub">м²</div></div>
                    <div class="metric"><div class="metric__label">Склад</div><div class="metric__value">${a.warehouse_m2.toFixed(0)}</div><div class="metric__sub">м²</div></div>
                    <div class="metric"><div class="metric__label">АБК</div><div class="metric__value">${a.office_m2.toFixed(0)}</div><div class="metric__sub">м²</div></div>
                    <div class="metric"><div class="metric__label">Парковка</div><div class="metric__value">${a.parking_m2.toFixed(0)}</div><div class="metric__sub">м²</div></div>
                    <div class="metric"><div class="metric__label">Дороги</div><div class="metric__value">${a.roads_m2.toFixed(0)}</div><div class="metric__sub">м²</div></div>
                    <div class="metric"><div class="metric__label">Жильё</div><div class="metric__value">${a.housing_m2.toFixed(0)}</div><div class="metric__sub">м²</div></div>
                    <div class="metric"><div class="metric__label">Детсад</div><div class="metric__value">${a.kindergarten_m2.toFixed(0)}</div><div class="metric__sub">м²</div></div>
                    <div class="metric"><div class="metric__label">Столовая</div><div class="metric__value">${a.canteen_m2.toFixed(0)}</div><div class="metric__sub">м²</div></div>
                    <div class="metric"><div class="metric__label">Медпункт</div><div class="metric__value">${a.medical_m2.toFixed(0)}</div><div class="metric__sub">м²</div></div>
                    <div class="metric" style="background:var(--ink);color:var(--ink-on-dark);border-color:var(--ink);">
                        <div class="metric__label" style="color:var(--ink-on-dark);opacity:0.6;">Итого</div>
                        <div class="metric__value" style="color:var(--ink-on-dark);">${a.total_m2.toFixed(0)}</div>
                        <div class="metric__sub" style="color:var(--ink-on-dark);opacity:0.7;">м²</div>
                    </div>
                </div>

                <div class="section-title"><i class="ti ti-coins"></i> Капитальные затраты, млн ₽</div>
                <div class="metrics">
                    <div class="metric"><div class="metric__label">Стройка</div><div class="metric__value">${e.construction_mln.toFixed(1)}</div></div>
                    <div class="metric"><div class="metric__label">Жильё</div><div class="metric__value">${e.housing_mln.toFixed(1)}</div></div>
                    <div class="metric"><div class="metric__label">Социальная инфраструктура</div><div class="metric__value">${e.social_mln.toFixed(1)}</div></div>
                    <div class="metric"><div class="metric__label">Инфра</div><div class="metric__value">${e.infrastructure_mln.toFixed(1)}</div></div>
                    <div class="metric"><div class="metric__label">Благ.+спорт</div><div class="metric__value">${e.amenities_mln.toFixed(1)}</div></div>
                </div>

                <div class="budget-line ${inBudget ? 'ok' : 'warn'}">
                    <i class="ti ti-${inBudget ? 'circle-check-filled' : 'alert-triangle'}"></i>
                    ${inBudget ? 'Бюджет участка и сетей выдержан' : 'Бюджет участка и сетей превышен'} ·
                    участок/сети ${siteBudget.toFixed(1)} млн ₽ из ${budget} млн ₽ (${delta >= 0 ? '+' : ''}${delta.toFixed(1)} млн).
                    Полная укрупнённая смета строительства: ${e.total_mln.toFixed(1)} млн ₽.
                </div>
            </div>

            <div class="tab-panel" data-panel="layout">
                <div class="section-title"><i class="ti ti-layout-dashboard"></i> Макет предприятия</div>
                <div class="prose"><p>${brief.layout_concept || ranked.layout_concept}</p></div>
                <div class="prose"><p>Текущий план участка синхронизирован с выбранной схемой 3D-модели: <b data-layout-label="1">${layoutLabel(selectedLayout)}</b>.</p></div>
                <div class="concept-board-preview">
                    <a href="/api/renders/${region.id}/site_plan.png?layout=${selectedLayout}&v=${Date.now()}" data-layout-plan-link="1" target="_blank" rel="noopener">
                        <img src="/api/renders/${region.id}/site_plan.png?layout=${selectedLayout}&v=${Date.now()}" data-layout-plan-img="1" alt="План участка ${region.name}" loading="lazy">
                    </a>
                </div>
            </div>

            <div class="tab-panel" data-panel="3d">
                <div class="section-title"><i class="ti ti-view-3d"></i> 3D-модель предприятия</div>
                <div class="prose"><p>Ниже показана интерактивная параметрическая 3D-сцена. Она собирается автоматически: размеры зависят от расчётных площадей, а облик — от архитектурного приоритета, социальный пакета, спорта и благоустройства.</p></div>
                <div class="viewer3d" id="site3d-root"></div>
            </div>

            <div class="tab-panel" data-panel="design">
                <div class="section-title"><i class="ti ti-palette"></i> Дизайн-код региона</div>
                <div class="prose"><p>Во вкладке собраны палитра, материалы и стилистические ориентиры, которые используются для оформления АБК, навигации и благоустройства.</p></div>

                <div class="section-title" style="margin-top:2.5rem;"><i class="ti ti-palette"></i> Палитра региона</div>
                <div class="palette">
                    ${region.culture.color_palette.map(c => `
                        <div class="swatch" style="background:${c}">
                            <div class="swatch__code">${c}</div>
                        </div>`).join('')}
                </div>

                <div class="section-title" style="margin-top:2.5rem;"><i class="ti ti-building"></i> Традиционные материалы</div>
                <div class="tags">
                    ${region.culture.traditional_materials.map(m => `<span class="tag">${m}</span>`).join('')}
                </div>

                <div class="section-title"><i class="ti ti-brush"></i> Доминирующие стили</div>
                <div class="tags">
                    ${region.culture.dominant_styles.map(s => `<span class="tag">${s}</span>`).join('')}
                </div>

                <div class="section-title"><i class="ti ti-building-arch"></i> Архитектурный концепт</div>
                <div class="prose"><p>${brief.design_concept || ranked.design_summary}</p></div>
                <div class="design-warning"><i class="ti ti-info-circle"></i> Концепт специально сделан спокойным: региональный образ применён в АБК, навигации и благоустройстве, а не превращает весь цех в декоративный объект.</div>
            </div>

            <div class="tab-panel" data-panel="renders">
                <div class="section-title"><i class="ti ti-photo-ai"></i> 4 визуальных рендера и презентация</div>
                <div class="prose"><p>Рендеры строятся на основе того же параметрического 3D-макета, что и во вкладке «3D-модель». Сейчас выбрана схема: <b data-layout-label="1">${layoutLabel(selectedLayout)}</b>. Для каждой стороны формируется отдельный вид: общественный вход, производственный тыл, социальная зона и грузовой контур.</p></div>
                <div class="map-links" style="margin-bottom:1rem;">
                    <a href="/api/presentation/${region.id}.pptx?layout=${selectedLayout}&v=${Date.now()}" data-layout-presentation="1" target="_blank" rel="noopener" class="map-links__primary"><i class="ti ti-presentation"></i> Скачать презентацию PPTX</a>
                </div>
                <div class="render-grid render-grid--images">
                    ${(['south','north','west','east']).map((key, idx) => `
                        <div class="render-card">
                            <a href="/api/renders/${region.id}/${key}.png?layout=${selectedLayout}&v=${Date.now()}" data-layout-render-link="1" data-render-name="${key}" target="_blank" rel="noopener" class="render-card__image-link">
                                <img src="/api/renders/${region.id}/${key}.png?layout=${selectedLayout}&v=${Date.now()}" data-layout-render-img="1" data-render-shot="1" data-render-name="${key}" alt="${['Южный','Северный','Западный','Восточный'][idx]} рендер площадки ${region.name}" loading="lazy">
                                <span>${['Юг','Север','Запад','Восток'][idx]}</span>
                            </a>
                            <div class="render-card__prompt">${['Вход и общественная зона', 'Производственный тыл', 'Зелёная социальная зона', 'Грузовой контур'][idx]}</div>
                        </div>`).join('')}
                </div>
            </div>
        `;

        // Биндим табы
        $$('.report__tab').forEach(t => {
            t.addEventListener('click', () => {
                $$('.report__tab').forEach(x => x.classList.toggle('active', x === t));
                $$('.tab-panel').forEach(p => p.classList.toggle('active', p.dataset.panel === t.dataset.tab));
                if (t.dataset.tab === '3d' && window.Site3D) {
                    window.Site3D.render(document.getElementById('site3d-root'), ranked, region, state.rankResponse.input_echo, {
                        layoutKey: currentLayoutKey(region),
                        onLayoutChange: (layoutKey) => {
                            state.selectedLayouts[region.id] = layoutKey;
                            refreshLayoutBoundAssets(region);
                        }
                    });
                }
            });
        });

        // Биндим коллапсиблы
        $$('.collapsible__head').forEach(h => {
            h.addEventListener('click', () => h.parentElement.classList.toggle('open'));
        });
        refreshLayoutBoundAssets(region);
        bindPresentationLinks(region);
        populate3DRenderShots(region);
    }


    function qualityLabel(key) {
        const map = {
            site_identity: 'Идентичность площадки', coordinates: 'Координаты', oez_tor_status: 'Статус ОЭЗ/ТОР',
            tax_benefits: 'Налоговые льготы', urban_env_index: 'Индекс городской среды', salary: 'Средняя зарплата',
            kindergarten: 'Детские сады', profile_college: 'Профильные колледжи', rent: 'Аренда жилья',
            gas: 'Газ в промзоне', free_power_kva: 'Свободная мощность', substation_distance: 'Расстояние до подстанции',
            connection_fee: 'Техприсоединение', steel_supplier_distance: 'Поставщик стали', insulation_supplier_distance: 'Поставщик утеплителя',
            railway_available: 'Ж/д ветка', railway: 'Ж/д ветка', federal_highway_km: 'Расстояние до трассы', energy_tariff: 'Энерготариф'
        };
        return map[key] || key;
    }

    function qualityStatusLabel(value) {
        const map = {
            official_verified: 'Подтверждено источником',
            official_stat: 'Официальная статистика',
            imported_official: 'Импортировано из официальной выгрузки',
            registry_verified: 'Сверено с реестром',
            calculated_from_verified: 'Рассчитано автоматически',
            tariff_estimate: 'Тарифная оценка',
            market_stat_estimate: 'Рыночная оценка',
            data_confirmed: 'Автоматически сверено',
            real_object: 'Объект найден',
            official_name_demo_metrics: 'Объект найден, метрики оценочные',
            demo_estimate: 'Оценка MVP',
            needs_review: 'Нужна ручная проверка',
            partially_verified: 'Частично сверено',
            official_stat_avg_2023_2025: 'Официальная статистика, среднее за 2023–2025',
            official_stat_or_municipal_estimate: 'Официальная/муниципальная оценка',
            market_stat_estimate_2023_2025: 'Рыночная оценка, 2023–2025',
            regional_tariff_estimate_2023_2025: 'Региональная тарифная оценка, 2023–2025',
            manual_review_required: 'Нужна ручная проверка',
            source_confirmed: 'Подтверждено источником',
            registry_confirmed: 'Сверено с реестром',
            auto_calculated: 'Рассчитано автоматически',
        };
        if (map[value]) return map[value];
        if (!value) return 'Не указано';
        return String(value)
            .replace(/_/g, ' ')
            .replace('official stat avg 2023 2025', 'Официальная статистика, среднее за 2023–2025')
            .replace('market stat estimate 2023 2025', 'Рыночная оценка, 2023–2025')
            .replace('regional tariff estimate 2023 2025', 'Региональная тарифная оценка, 2023–2025')
            .replace('official stat or municipal estimate', 'Официальная/муниципальная оценка');
    }

    async function renderDataPanel() {
        const body = $('#data-panel-content');
        try {
            state.dataStatus = await api('/data/status');
            state.verificationStatus = await api('/verification/status');
            state.discoveryStatus = await api('/discovery/status');
        } catch (e) {
            body.innerHTML = `<div class="data-panel__error">${e.message}</div>`;
            return;
        }
        const s = state.dataStatus;
        const v = state.verificationStatus || {};
        body.innerHTML = `
            <div class="data-hero">
                <div>
                    <div class="data-hero__label">Автоматическая верификация данных</div>
                    <h3>Максимальная автоматическая верификация</h3>
                    <p>Система автоматически сверяет большинство полей через реестры, официальную статистику, региональные источники и расчёты от координат. Статус «подтверждено источником» используется только для полей, где найден конкретный источник.</p>
                </div>
                <div class="data-actions">
                    <button class="btn btn--primary" id="run-fast-verification"><i class="ti ti-bolt"></i> Быстрая проверка</button>
                    <button class="btn btn--ghost" id="run-full-verification"><i class="ti ti-world-search"></i> Полная проверка</button>
                    <button class="btn btn--ghost" id="run-verification-llm"><i class="ti ti-sparkles"></i> Полная + ИИ extractor</button>
                    <div class="data-actions__hint">Выберите быстрый или полный режим проверки. Старый сценарий обновления статусов отключён.</div>
                </div>
            </div>

            <div id="data-update-result" class="data-update-result data-update-result--top"></div>

            <div class="results-summary data-summary">
                <div class="summary-card summary-card--accent"><div class="summary-card__label">Площадок</div><div class="summary-card__value">${s.regions_count}</div><div class="summary-card__sub">локальная база</div></div>
                <div class="summary-card"><div class="summary-card__label">Подтверждённые поля</div><div class="summary-card__value">${s.official_verified_count}</div><div class="summary-card__sub">official / registry / calculated</div></div>
                <div class="summary-card"><div class="summary-card__label">Объект найден</div><div class="summary-card__value">${v.real_object || 0}</div><div class="summary-card__sub">найден в источниках</div></div>
                <div class="summary-card"><div class="summary-card__label">Автоматически сверено</div><div class="summary-card__value">${v.data_confirmed || 0}</div><div class="summary-card__sub">поля сверены автоматически</div></div>
            </div>

            <div class="data-note"><i class="ti ti-info-circle"></i> ${v.message || s.message}</div>
            ${v.last_update ? `<div class="data-note"><i class="ti ti-clock"></i> Последняя верификация: ${v.last_update}</div>` : ''}
            ${(v.warnings || []).length ? `<div class="data-note data-note--warn"><i class="ti ti-alert-triangle"></i> ${(v.warnings || []).slice(0, 3).join('<br>')}</div>` : ''}

            <div class="section-title"><i class="ti ti-list-check"></i> Последний результат проверки</div>
            <div class="verification-list">
                ${(v.results || []).length ? (v.results || []).map(item => `
                    <div class="verification-row">
                        <div>
                            <b>${item.name}</b>
                            <small>${item.region_id}</small>
                        </div>
                        <span class="verification-badge verification-badge--${item.status}">${formatVerificationStatus(item.status)}</span>
                        <span>${item.verified_fields || 0} подтверждено</span>
                        <span>${item.needs_review_fields || 0} требует проверки</span>
                    </div>
                `).join('') : `<div class="data-note">Верификация ещё не запускалась. Нажмите «Быстрая проверка» или «Полная проверка».</div>`}
            </div>

            <div class="section-title"><i class="ti ti-link"></i> Подключённые источники</div>
            <div class="source-grid">
                ${(s.sources || []).map(src => `
                    <a class="source-card" href="${src.url}" target="_blank" rel="noopener">
                        <div class="source-card__group">${src.group}</div>
                        <div class="source-card__title">${src.title}</div>
                        <div class="source-card__comment">${src.comment || ''}</div>
                    </a>
                `).join('')}
            </div>


            <div class="section-title"><i class="ti ti-world-search"></i> Автопоиск новых площадок</div>
            <div class="discovery-panel">
                <div class="discovery-panel__text">
                    <b>Пополнение базы из интернета</b>
                    <p>Система без ИИ-ключа обходит открытые инвестиционные порталы, ищет новые промплощадки и складывает их в очередь кандидатов. После добавления площадка участвует в рейтинге, и для неё доступны макет, отчёты, рендеры и пакет инвестора.</p>
                    <div class="discovery-panel__stats">
                        <span><b>${state.discoveryStatus?.candidates_count || 0}</b> кандидатов в очереди</span>
                        <span>${state.discoveryStatus?.last_discovery?.message || 'Поиск ещё не запускался'}</span>
                    </div>
                </div>
                <div class="data-actions discovery-actions">
                    <button class="btn btn--primary" id="discover-fast"><i class="ti ti-radar"></i> Найти новые площадки</button>
                    <button class="btn btn--ghost" id="discover-full"><i class="ti ti-sitemap"></i> Глубокий поиск</button>
                    <button class="btn btn--ghost" id="import-candidates"><i class="ti ti-database-plus"></i> Добавить кандидатов в базу</button>
                </div>
            </div>
            <div id="discovery-result"></div>
            <div class="candidate-list">
                ${(state.discoveryStatus?.candidates || []).length ? state.discoveryStatus.candidates.slice(0, 10).map(c => `
                    <div class="candidate-card">
                        <div>
                            <b>${c.name}</b>
                            <small>${c.federal_subject || ''} · ${c.source_title || 'источник'} · уверенность ${Math.round((c.confidence || 0) * 100)}%</small>
                        </div>
                        <a href="${c.source_url}" target="_blank" rel="noopener">Источник</a>
                    </div>
                `).join('') : `<div class="data-note"><i class="ti ti-info-circle"></i> Новых кандидатов пока нет. Нажмите «Найти новые площадки».</div>`}
            </div>

            <details class="data-import data-import--collapsed">
                <summary><i class="ti ti-file-import"></i> Резервный импорт CSV</summary>
                <p>CSV оставлен только как резервный путь. Основной сценарий — быстрая или полная автоматическая проверка.</p>
                <textarea id="csv-import-text" placeholder="id;name;federal_subject;lat;lon;site_type;railway_available;..."></textarea>
                <div class="data-import__actions">
                    <a class="btn btn--ghost" href="/api/data/template" download="sites_import_template.csv"><i class="ti ti-download"></i> CSV-шаблон</a>
                    <button class="btn btn--primary" id="import-csv"><i class="ti ti-upload"></i> Импортировать CSV</button>
                </div>
            </details>
        `;
        $('#import-csv').addEventListener('click', importCsvData);
        const fastBtn = $('#run-fast-verification');
        const fullBtn = $('#run-full-verification');
        const llmBtn = $('#run-verification-llm');
        fastBtn?.addEventListener('click', (e) => { e.preventDefault(); runVerification(false, 'fast'); });
        fullBtn?.addEventListener('click', (e) => { e.preventDefault(); runVerification(false, 'full'); });
        llmBtn?.addEventListener('click', (e) => { e.preventDefault(); runVerification(true, 'full'); });
        $('#discover-fast')?.addEventListener('click', (e) => { e.preventDefault(); runDiscovery('fast'); });
        $('#discover-full')?.addEventListener('click', (e) => { e.preventDefault(); runDiscovery('full'); });
        $('#import-candidates')?.addEventListener('click', (e) => { e.preventDefault(); importCandidates(); });
    }

    function formatVerificationStatus(status) {
        const map = {
            data_confirmed: 'Автоматически сверено',
            real_object: 'Объект найден',
            needs_review: 'Нужна ручная проверка',
            partially_verified: 'Частично сверено',
            official_verified: 'Подтверждено источником',
            registry_verified: 'Сверено с реестром',
            official_stat: 'Официальная статистика',
            imported_official: 'Импортировано из официального источника',
            calculated_from_verified: 'Рассчитано автоматически',
            tariff_estimate: 'Тарифная оценка',
            market_stat_estimate: 'Рыночная оценка',
            demo_estimate: 'Оценка MVP',
            demo: 'Оценка MVP',
            official_name_demo_metrics: 'Объект найден, метрики оценочные',
            official_stat_avg_2023_2025: 'Официальная статистика, среднее за 2023–2025',
            official_stat_or_municipal_estimate: 'Официальная/муниципальная оценка',
            market_stat_estimate_2023_2025: 'Рыночная оценка, 2023–2025',
            regional_tariff_estimate_2023_2025: 'Региональная тарифная оценка, 2023–2025',
            manual_review_required: 'Нужна ручная проверка',
            source_confirmed: 'Подтверждено источником',
            registry_confirmed: 'Сверено с реестром',
            auto_calculated: 'Рассчитано автоматически',
        };
        if (map[status]) return map[status];
        if (!status) return 'Не проверено';
        return String(status)
            .replace(/_/g, ' ')
            .replace('official stat avg 2023 2025', 'Официальная статистика, среднее за 2023–2025')
            .replace('market stat estimate 2023 2025', 'Рыночная оценка, 2023–2025')
            .replace('regional tariff estimate 2023 2025', 'Региональная тарифная оценка, 2023–2025')
            .replace('official stat or municipal estimate', 'Официальная/муниципальная оценка');
    }


    async function runDiscovery(mode = 'fast') {
        const box = $('#discovery-result');
        if (!box) return;
        const isFull = mode === 'full';
        box.innerHTML = `
            <div class="verification-loader">
                <div class="verification-loader__ring"><i class="ti ti-radar"></i></div>
                <div class="verification-loader__content">
                    <div class="verification-loader__title">${isFull ? 'Глубокий поиск площадок' : 'Поиск новых площадок'}</div>
                    <div class="verification-loader__sub">${isFull ? 'Обходим больше источников и внутренних ссылок.' : 'Проверяем основные региональные источники.'}</div>
                    <div class="verification-loader__bar"><span></span></div>
                    <div class="verification-loader__steps">
                        <span class="is-active">Обход источников</span><span>Извлечение названий</span><span>Проверка дублей</span><span>Очередь кандидатов</span>
                    </div>
                </div>
            </div>`;
        try {
            const res = await api(`/discovery/run?mode=${mode}`, { method: 'POST' });
            box.innerHTML = `<div class="data-note"><i class="ti ti-check"></i> ${res.message}</div>`;
            await loadAllRegions();
            setTimeout(renderDataPanel, 400);
        } catch (e) {
            box.innerHTML = `<div class="data-panel__error">${e.message}</div>`;
        }
    }

    async function importCandidates() {
        const box = $('#discovery-result');
        if (!box) return;
        box.innerHTML = `<div class="data-note"><i class="ti ti-loader-2"></i> Добавляю найденные площадки в базу...</div>`;
        try {
            const res = await api('/discovery/import?limit=10', {
                method: 'POST',
                body: JSON.stringify({}),
                headers: { 'Content-Type': 'application/json' }
            });
            box.innerHTML = `<div class="data-note"><i class="ti ti-database-plus"></i> ${res.message}</div>`;
            await loadAllRegions();
            setTimeout(renderDataPanel, 500);
        } catch (e) {
            box.innerHTML = `<div class="data-panel__error">${e.message}</div>`;
        }
    }

    async function runVerification(useLlm, mode = 'fast') {
        const resultBox = $('#data-update-result');
        if (!resultBox) {
            console.error('[Verification] Не найден #data-update-result');
            return;
        }

        const buttons = ['#run-fast-verification', '#run-full-verification', '#run-verification-llm']
            .map(sel => $(sel))
            .filter(Boolean);
        buttons.forEach(btn => { btn.disabled = true; btn.classList.add('is-loading'); });

        if (state.verificationAbort) {
            try { state.verificationAbort.abort(); } catch (e) {}
        }
        state.verificationAbort = new AbortController();
        state.dataPanelClosed = false;

        const isFull = mode === 'full';
        const steps = isFull
            ? ['Поиск карточек', 'Обход сайтов', 'Сверка полей', 'Обновление статусов']
            : ['Проверка базы', 'Сверка координат', 'Расчёт статусов'];
        const timeLabel = isFull ? 'обычно 1–5 минут' : 'обычно 5–20 секунд';

        resultBox.innerHTML = `
            <div class="verification-loader">
                <div class="verification-loader__ring">
                    <i class="ti ${isFull ? 'ti-world-search' : 'ti-bolt'}"></i>
                </div>
                <div class="verification-loader__content">
                    <div class="verification-loader__title">${isFull ? 'Полная проверка источников' : 'Быстрая проверка данных'}</div>
                    <div class="verification-loader__sub">Окно можно закрыть крестиком или клавишей Esc. Ориентир: ${timeLabel}.</div>
                    <div class="verification-loader__bar"><span></span></div>
                    <div class="verification-loader__steps">
                        ${steps.map((s, i) => `<span class="${i === 0 ? 'is-active' : ''}">${s}</span>`).join('')}
                    </div>
                </div>
            </div>`;
        resultBox.scrollIntoView({ block: 'nearest', behavior: 'smooth' });

        try {
            const res = await api(`/verification/run?use_llm=${useLlm ? 'true' : 'false'}&mode=${mode}`, {
                method: 'POST',
                signal: state.verificationAbort.signal
            });

            state.verificationAbort = null;
            buttons.forEach(btn => { btn.disabled = false; btn.classList.remove('is-loading'); });
            if (state.dataPanelClosed || $('#data-panel')?.hidden) return;

            resultBox.innerHTML = `
                <div class="data-note">
                    <i class="ti ti-shield-check"></i>
                    ${res.message}<br>
                    Объект найден: ${res.real_object || 0};
                    автоматически сверено: ${res.data_confirmed || 0};
                    нужна ручная проверка: ${res.needs_review || 0}.
                </div>`;
            await loadAllRegions();
            if (!state.dataPanelClosed && !$('#data-panel')?.hidden) {
                setTimeout(() => {
                    if (!state.dataPanelClosed && !$('#data-panel')?.hidden) renderDataPanel();
                }, 350);
            }
        } catch (e) {
            state.verificationAbort = null;
            buttons.forEach(btn => { btn.disabled = false; btn.classList.remove('is-loading'); });
            if (e.name === 'AbortError') return;
            if (state.dataPanelClosed || $('#data-panel')?.hidden) return;
            resultBox.innerHTML = `<div class="data-panel__error">${e.message}</div>`;
        }
    }

    async function importCsvData() {
        const csv = $('#csv-import-text').value.trim();
        const result = $('#data-update-result');
        if (!csv) { result.innerHTML = `<div class="data-panel__error">Вставьте CSV-данные для импорта.</div>`; return; }
        result.innerHTML = `<div class="loading-box"><span class="loader"></span> Импортирую CSV…</div>`;
        try {
            const r = await api('/data/import-csv', { method: 'POST', body: csv });
            result.innerHTML = dataResultHtml(r);
            await checkHealth();
            await loadAllRegions();
        } catch (e) {
            result.innerHTML = `<div class="data-panel__error">${e.message}</div>`;
        }
    }

    function dataResultHtml(r) {
        return `
            <div class="data-result">
                <div class="data-result__title"><i class="ti ti-circle-check"></i> ${r.message || 'Готово'}</div>
                <div class="metrics">
                    <div class="metric"><div class="metric__label">Добавлено</div><div class="metric__value">${r.added}</div></div>
                    <div class="metric"><div class="metric__label">Обновлено</div><div class="metric__value">${r.updated}</div></div>
                    <div class="metric"><div class="metric__label">Без изменений</div><div class="metric__value">${r.unchanged}</div></div>
                    <div class="metric"><div class="metric__label">Проверить</div><div class="metric__value">${r.needs_review}</div></div>
                </div>
                ${(r.warnings || []).map(w => `<div class="data-warning"><i class="ti ti-alert-triangle"></i> ${w}</div>`).join('')}
            </div>
        `;
    }

    function layoutSketchHtml(ranked) {
        const a = ranked.areas;
        return `
            <div class="site-sketch" aria-label="Схематичный макет участка">
                <div class="site-sketch__zone site-sketch__zone--workshop">Цех<br><small>${a.workshop_m2.toFixed(0)} м²</small></div>
                <div class="site-sketch__zone site-sketch__zone--warehouse">Склад<br><small>${a.warehouse_m2.toFixed(0)} м²</small></div>
                <div class="site-sketch__zone site-sketch__zone--office">АБК / КПП</div>
                <div class="site-sketch__zone site-sketch__zone--parking">Парковка</div>
                <div class="site-sketch__zone site-sketch__zone--social">Соц. блок</div>
                <div class="site-sketch__road site-sketch__road--main">грузовой проезд</div>
                <div class="site-sketch__green">озеленение / благоустройство</div>
            </div>
        `;
    }

    function collapsibleHtml(title, body) {
        return `
            <div class="collapsible">
                <div class="collapsible__head">
                    <span>${title}</span>
                    <i class="ti ti-chevron-down collapsible__chev"></i>
                </div>
                <div class="collapsible__body"><p>${body}</p></div>
            </div>`;
    }

    // ============================================================
    //  Инициализация
    // ============================================================
    function init() {
        bindCheckables();
        bindHousingLock();
        bindPresets();
        const form = $('#investor-form');
        form.addEventListener('submit', onSubmit);
        form.addEventListener('input', scheduleAutoRank);
        form.addEventListener('change', scheduleAutoRank);
        checkHealth();
        loadAllRegions();

        // Надёжная привязка кнопки «База данных».
        // Нужна, чтобы кнопка работала независимо от внешнего Nav-скрипта в шаблоне.
        document.querySelectorAll('[data-nav="database"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                openDataPanel();
            });
        });

        // Надёжное закрытие модального окна базы данных, даже если идёт fetch.
        document.querySelectorAll('[data-close-data-panel]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                closeDataPanel();
            });
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeDataPanel();
        });
    }

    document.addEventListener('DOMContentLoaded', init);

    return { openForm, closeForm, selectRegion, applyPreset, openDataPanel, closeDataPanel };
})();

window.App = App;
