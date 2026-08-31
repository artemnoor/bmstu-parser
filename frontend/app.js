(() => {
  const STORAGE_KEY = 'bmstu-api-endpoint';
  const navigation = {
    overview: 'Операционный обзор',
    majors: 'Направления подготовки',
    programs: 'Образовательные программы',
    plans: 'Учебные планы',
    disciplines: 'Дисциплины',
    datasets: 'Каталог данных'
  };
  const state = {
    view: 'overview',
    query: '',
    loading: false,
    error: '',
    apiBase: localStorage.getItem(STORAGE_KEY) || defaultApiBase(),
    health: null,
    catalog: null,
    majors: [],
    programs: [],
    plans: [],
    disciplines: [],
    operation: null
  };

  const refs = {
    endpoint: document.getElementById('api-endpoint'),
    refresh: document.getElementById('refresh-button'),
    pageTitle: document.getElementById('page-title'),
    view: document.getElementById('app-view'),
    alert: document.getElementById('app-alert'),
    apiStatus: document.getElementById('api-status'),
    drawer: document.getElementById('detail-drawer'),
    drawerTitle: document.getElementById('drawer-title'),
    drawerBody: document.getElementById('drawer-body'),
    drawerClose: document.getElementById('drawer-close'),
    backdrop: document.getElementById('drawer-backdrop')
  };
  const apiClient = window.BmstuApiClient.create(() => state.apiBase);

  function defaultApiBase() {
    if (window.location.protocol === 'http:' || window.location.protocol === 'https:') {
      return window.location.port === '5173' ? 'http://127.0.0.1:8000' : window.location.origin;
    }
    return 'http://127.0.0.1:8000';
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
  }

  function display(value, fallback = '—') {
    if (value === null || value === undefined || value === '') return fallback;
    return escapeHtml(value);
  }

  function number(value) {
    return Number(value || 0).toLocaleString('ru-RU');
  }

  function tuition(value) {
    if (!value) return '';
    if (typeof value !== 'string') return value;
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        const values = [...new Set(parsed.map((item) => item?.value).filter(Boolean))];
        return values.join(' / ') || value;
      }
    } catch {
      // Keep the original value if a legacy dataset stores plain text.
    }
    return value;
  }

  function filtered(items) {
    const query = state.query.trim().toLocaleLowerCase('ru-RU');
    if (!query) return items;
    return items.filter((item) => JSON.stringify(item).toLocaleLowerCase('ru-RU').includes(query));
  }

  function apiUrl(path) {
    return `${state.apiBase.replace(/\/$/, '')}${path}`;
  }

  function setAlert(message = '') {
    state.error = message;
    refs.alert.textContent = message;
    refs.alert.hidden = !message;
  }

  function setApiStatus(online, label) {
    refs.apiStatus.className = `service-status ${online ? 'is-online' : 'is-muted'}`;
    refs.apiStatus.innerHTML = `<i></i><span>${escapeHtml(label)}</span>`;
  }

  function verification(report) {
    const checks = report?.verification || {};
    if (typeof checks.passed === 'boolean') return checks.passed;
    const values = Object.values(checks).filter((value) => typeof value === 'boolean');
    return values.length ? values.every(Boolean) : null;
  }

  function reportName(key) {
    return ({
      parse: 'Основной парсинг',
      study_plan_extraction: 'Извлечение таблиц',
      study_plan_semantics: 'Семантический слой',
      study_plan_resolution: 'study plan resolution'
    })[key] || key;
  }

  function emptyState(message = 'Нет данных для отображения') {
    return `<div class="empty-state"><span>⌁</span><p>${escapeHtml(message)}</p></div>`;
  }

  function table(headers, rows, emptyMessage) {
    if (!rows.length) return emptyState(emptyMessage);
    return `<div class="table-wrap"><table><thead><tr>${headers.map((header) => `<th>${header}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
  }

  function searchControl(placeholder = 'Поиск по данным') {
    return `<label class="search-control"><span>⌕</span><input id="view-search" type="search" value="${escapeHtml(state.query)}" placeholder="${placeholder}" aria-label="${placeholder}"></label>`;
  }

  function card(label, value, note, accent = '') {
    return `<article class="metric-card ${accent}"><span>${escapeHtml(label)}</span><strong>${value}</strong><small>${escapeHtml(note)}</small></article>`;
  }

  function renderOverview() {
    const quality = state.catalog?.quality || {};
    const reports = Object.entries(quality);
    const passed = reports.filter(([, report]) => verification(report) === true).length;
    const majorRows = filtered(state.majors).slice(0, 8).map((row) => `<tr>
      <td class="mono">${display(row.code)}</td>
      <td><button class="link-button" data-details-kind="major" data-details-id="${escapeHtml(row.slug || '')}">${display(row.name)}</button><small class="subline">${display(row.duration || row.study_duration, '')}</small></td>
      <td>${display(row.faculty_name || row.faculty || row.department_name)}</td>
      <td>${display(row.program_count || row.programs_count, '—')}</td>
      <td>${display(tuition(row.tuition || row.price || row.min_price), '—')}</td>
      <td><span class="status-pill is-ok">OK</span></td>
    </tr>`);
    const operation = state.operation;
    return `<div class="view-stack">
      <section class="hero-panel">
        <div><p class="eyebrow">CANONICAL DATA LAYER</p><h2>Единая точка наблюдения за образовательными данными</h2><p>Панель читает проверенные datasets из BMSTU API и показывает их состояние, структуру и связанные учебные планы.</p></div>
        <div class="hero-state ${state.health?.status === 'ok' ? 'is-online' : 'is-muted'}"><span></span>${state.health?.status === 'ok' ? 'API online' : 'API недоступен'}<small>${state.health ? `Обновлено ${new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}` : 'Ожидание подключения'}</small></div>
      </section>
      <section class="metrics-grid" aria-label="Ключевые показатели">
        ${card('Состояние API', state.health?.status === 'ok' ? 'ONLINE' : '—', state.health ? `API v1.0 · parser ${state.health.version}` : 'нет соединения', 'is-dark')}
        ${card('Направления', number(state.majors.length), 'карточек подготовки')}
        ${card('Программы', number(state.programs.length), 'реализуемых программ')}
        ${card('Учебные планы', number(state.plans.length), 'канонических документов')}
      </section>
      <div class="two-column">
        <section class="panel quality-panel"><div class="panel-head"><div><p class="eyebrow">QUALITY GATE</p><h2>Контроль качества</h2></div><span class="panel-count">${reports.length ? `${passed}/${reports.length} пройдено` : 'нет отчётов'}</span></div>
          ${reports.length ? `<div class="quality-list">${reports.map(([key, report]) => { const ok = verification(report); return `<div class="quality-row"><span class="quality-icon ${ok ? 'is-ok' : 'is-fail'}">${ok ? '✓' : '!'}</span><span><strong>${escapeHtml(reportName(key))}</strong><small>${ok ? 'проверка пройдена' : 'есть замечания'}</small></span><b class="${ok ? 'text-ok' : 'text-fail'}">${ok ? 'PASS' : 'CHECK'}</b></div>`; }).join('')}</div>` : emptyState('Отчёты качества пока недоступны.')}
        </section>
        ${operationPanel(operation)}
      </div>
      <section class="panel"><div class="panel-head"><div><p class="eyebrow">PROGRAM SNAPSHOT</p><h2>Направления подготовки</h2></div><button type="button" class="text-button" data-view="majors">Открыть все →</button></div>
        ${table(['Код', 'Направление', 'Факультет', 'Программы', 'Стоимость', 'Статус'], majorRows, 'Направления ещё не загружены')}
      </section>
    </div>`;
  }

  function operationPanel(operation) {
    return `<section class="panel operation-panel"><div class="panel-head"><div><p class="eyebrow">CONTROL PLANE</p><h2>Операции</h2></div><span class="panel-count">фоновые</span></div><p>Запуск изменяющих операций проходит через очередь сервиса. Для production может потребоваться API-ключ.</p><div class="operation-form"><label>Операция<select id="operation-name"><option value="refresh">Обновить данные с Mirror API</option><option value="extract_study_plans">Извлечь таблицы учебных планов</option><option value="extract_semantics">Построить семантический слой</option><option value="compact_study_plans">Уплотнить производные данные</option></select></label><label>X-API-Key <em>(если настроен)</em><input id="operation-key" type="password" autocomplete="off" placeholder="не требуется локально"></label><button id="operation-start" type="button" class="button button-primary">Запустить операцию</button></div><div id="operation-status" class="operation-status" role="status">${operation ? `${escapeHtml(operation.status)} · ${escapeHtml(operation.id)}` : 'Операции ещё не запускались.'}</div></section>`;
  }

  function renderMajors() {
    const rows = filtered(state.majors).map((row) => `<tr><td class="mono">${display(row.code)}</td><td><button class="link-button" data-details-kind="major" data-details-id="${escapeHtml(row.slug || '')}">${display(row.name)}</button><small class="subline">${display(row.duration || row.study_duration, '')}</small></td><td>${display(row.faculty_name || row.faculty || row.department_name)}</td><td>${display(row.program_count || row.programs_count, '—')}</td><td>${display(tuition(row.tuition || row.price || row.min_price), '—')}</td><td><span class="status-pill is-ok">OK</span></td></tr>`);
    return `<div class="view-stack"><section class="section-intro"><div><p class="eyebrow">DOMAIN / MAJORS</p><h2>Направления подготовки</h2><p>Коды, факультеты, стоимость, вступительные предметы и связанные программы.</p></div><strong>${number(filtered(state.majors).length)} из ${number(state.majors.length)}</strong></section><section class="panel">${searchControl('Поиск направления')}${table(['Код', 'Направление', 'Факультет', 'Программы', 'Стоимость', ''], rows, 'Направления не найдены')}</section></div>`;
  }

  function renderPrograms() {
    const rows = filtered(state.programs).map((row) => `<tr><td class="mono">${display(row.code)}</td><td><button class="link-button" data-details-kind="program" data-details-id="${escapeHtml(row.id || '')}">${display(row.name)}</button></td><td>${display(row.department_name || row.department || row.faculty_name)}</td><td class="mono">${display(row.major_code || row.major_id)}</td><td><span class="status-pill is-ok">OK</span></td></tr>`);
    return `<div class="view-stack"><section class="section-intro"><div><p class="eyebrow">PROGRAMS / CATALOG</p><h2>Образовательные программы</h2><p>Программы с сохранённым контекстом кафедры и связью с направлением.</p></div><strong>${number(filtered(state.programs).length)} записей</strong></section><section class="panel">${searchControl('Поиск программы, кафедры или кода')}${table(['Код', 'Программа', 'Кафедра', 'Направление', 'Статус'], rows, 'Программы не найдены')}</section></div>`;
  }

  function renderPlans() {
    const rows = filtered(state.plans).map((row) => `<tr><td class="mono">${display(row.document_id)}</td><td><button class="link-button" data-details-kind="document" data-details-id="${escapeHtml(row.document_id || '')}">${display((row.local_path || '').split(/[\\/]/).pop() || row.file_name || row.document_id)}</button><small class="subline">${display(row.kind, '')} · ${display(row.page_count, '')} стр.</small></td><td>${display(row.table_count, '—')}</td><td>${display(row.row_count, '—')}</td><td><span class="status-pill ${row.status === 'ok' ? 'is-ok' : 'is-warn'}">${display(row.status, 'unknown')}</span></td></tr>`);
    return `<div class="view-stack"><section class="section-intro"><div><p class="eyebrow">DOCUMENTS / STUDY PLANS</p><h2>Учебные планы</h2><p>Канонические документы, таблицы, строки, дисциплины и исходные файлы.</p></div><strong>${number(filtered(state.plans).length)} документов</strong></section><section class="panel">${searchControl('Поиск документа или программы')}${table(['ID документа', 'Файл', 'Таблицы', 'Строки', 'Статус'], rows, 'Учебные планы не найдены')}</section></div>`;
  }

  function renderDisciplines() {
    const rows = filtered(state.disciplines).map((row) => `<tr><td class="mono">${display(row.code || row.discipline_code)}</td><td>${display(row.name || row.discipline_name)}</td><td>${display(row.department || row.department_name)}</td><td>${display(row.credits || row.total_credits, '—')}</td><td>${display(row.total_hours || row.hours, '—')}</td><td>${display(row.document_id, '—')}</td></tr>`);
    return `<div class="view-stack"><section class="section-intro"><div><p class="eyebrow">SEMANTIC / DISCIPLINES</p><h2>Предметы</h2><p>Нормализованные дисциплины и общая трудоёмкость из семантического слоя.</p></div><strong>${number(filtered(state.disciplines).length)} записей</strong></section><section class="panel">${searchControl('Поиск предмета, кода или документа')}${table(['Код', 'Название', 'Кафедра', 'З.Е.', 'Часы', 'Документ'], rows, 'Дисциплины не найдены')}</section></div>`;
  }

  function renderDatasets() {
    const datasets = state.catalog?.datasets || [];
    const rows = filtered(datasets).map((row) => `<tr><td class="mono">${display(row.name)}</td><td><span class="format-tag">${display(row.format)}</span></td><td>${display(row.description)}</td><td>${row.available ? '<span class="status-pill is-ok">готов</span>' : '<span class="status-pill is-warn">нет файла</span>'}</td><td>${row.size_bytes ? `${number(Math.round(row.size_bytes / 1024))} KB` : '—'}</td></tr>`);
    return `<div class="view-stack"><section class="section-intro"><div><p class="eyebrow">DATASETS / CATALOG</p><h2>Каталог данных</h2><p>Allowlist datasets, которые API отдаёт постранично и без чтения файлов frontend-ом.</p></div><strong>${number(filtered(datasets).length)} datasets</strong></section><section class="panel">${searchControl('Поиск dataset')}${table(['Dataset', 'Формат', 'Описание', 'Доступность', 'Размер'], rows, 'Каталог пока недоступен')}</section></div>`;
  }

  function render() {
    refs.pageTitle.textContent = navigation[state.view];
    document.querySelectorAll('.nav-item').forEach((item) => item.classList.toggle('is-active', item.dataset.view === state.view));
    refs.endpoint.value = state.apiBase;
    if (state.loading && !state.health) {
      refs.view.innerHTML = `<div class="loading-state"><span class="spinner"></span><p>Подключение к BMSTU API…</p></div>`;
      return;
    }
    refs.view.innerHTML = ({ overview: renderOverview, majors: renderMajors, programs: renderPrograms, plans: renderPlans, disciplines: renderDisciplines, datasets: renderDatasets })[state.view]();
    const search = document.getElementById('view-search');
    if (search) search.addEventListener('input', (event) => { state.query = event.target.value; render(); });
  }

  async function load() {
    state.loading = true;
    setAlert('');
    render();
    try {
      const [health, catalog, majors, programs, plans, disciplines] = await Promise.all([
        apiClient.get('/health'),
        apiClient.get('/api/v1/catalog'),
        apiClient.get('/api/v1/majors?limit=500'),
        apiClient.get('/api/v1/programs?limit=500'),
        apiClient.get('/api/v1/study-plans/documents?limit=500'),
        apiClient.get('/api/v1/datasets/study_plan_disciplines/rows?limit=500')
      ]);
      state.health = health;
      state.catalog = catalog;
      state.majors = majors.items || [];
      state.programs = programs.items || [];
      state.plans = plans.items || [];
      state.disciplines = disciplines.items || [];
      setApiStatus(true, 'API online');
    } catch (error) {
      state.health = null;
      setApiStatus(false, 'API недоступен');
      setAlert(`${error.message || 'Не удалось подключиться к API'}. Проверьте адрес сервиса и CORS.`);
    } finally {
      state.loading = false;
      render();
    }
  }

  async function openDetails(kind, id) {
    refs.drawerTitle.textContent = 'Загрузка…';
    refs.drawerBody.innerHTML = '<div class="loading-state"><span class="spinner"></span></div>';
    refs.drawer.classList.add('is-open');
    refs.drawer.setAttribute('aria-hidden', 'false');
    refs.backdrop.hidden = false;
    const paths = { major: `/api/v1/majors/${encodeURIComponent(id)}`, program: `/api/v1/programs/${encodeURIComponent(id)}`, document: `/api/v1/study-plans/documents/${encodeURIComponent(id)}` };
    try {
      const data = await apiClient.get(paths[kind]);
      refs.drawerTitle.textContent = data.name || data.document_id || 'Детали';
      const file = kind === 'document' ? `<a class="button button-primary" href="${apiUrl(`/api/v1/study-plans/documents/${encodeURIComponent(id)}/file`)}" target="_blank" rel="noopener">Открыть исходный файл</a>` : '';
      refs.drawerBody.innerHTML = `${file}<dl class="detail-list">${Object.entries(data).filter(([key]) => !['ontology', 'provenance', 'source_references'].includes(key)).map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(typeof value === 'object' ? JSON.stringify(value, null, 2) : value)}</dd></div>`).join('')}</dl>`;
    } catch (error) {
      refs.drawerTitle.textContent = 'Ошибка';
      refs.drawerBody.innerHTML = `<div class="empty-state"><p>${escapeHtml(error.message)}</p></div>`;
    }
  }

  async function startOperation() {
    const button = document.getElementById('operation-start');
    if (!button) return;
    button.disabled = true;
    try {
      const operation = document.getElementById('operation-name').value;
      const apiKey = document.getElementById('operation-key').value.trim();
      state.operation = await apiClient.post('/api/v1/operations', { operation, strict: true, resume: true }, apiKey ? { apiKey } : {});
      render();
      pollOperation(state.operation.id);
    } catch (error) {
      setAlert(error.message);
      button.disabled = false;
    }
  }

  async function pollOperation(id) {
    try {
      const current = await apiClient.get(`/api/v1/operations/${encodeURIComponent(id)}`);
      state.operation = current;
      render();
      if (current.status === 'queued' || current.status === 'running') window.setTimeout(() => pollOperation(id), 1500);
    } catch (error) { setAlert(error.message); }
  }

  function closeDrawer() {
    refs.drawer.classList.remove('is-open');
    refs.drawer.setAttribute('aria-hidden', 'true');
    refs.backdrop.hidden = true;
  }

  document.addEventListener('click', (event) => {
    const viewButton = event.target.closest('[data-view]');
    if (viewButton) { event.preventDefault(); state.view = viewButton.dataset.view; state.query = ''; render(); return; }
    const detailButton = event.target.closest('[data-details-kind]');
    if (detailButton) { openDetails(detailButton.dataset.detailsKind, detailButton.dataset.detailsId); return; }
    if (event.target.closest('#refresh-button')) { state.apiBase = refs.endpoint.value.trim() || defaultApiBase(); localStorage.setItem(STORAGE_KEY, state.apiBase); load(); return; }
    if (event.target.closest('#operation-start')) { startOperation(); return; }
    if (event.target.closest('#drawer-close') || event.target === refs.backdrop) closeDrawer();
  });

  refs.endpoint.value = state.apiBase;
  refs.drawerClose.addEventListener('click', closeDrawer);
  refs.backdrop.addEventListener('click', closeDrawer);
  load();
})();
