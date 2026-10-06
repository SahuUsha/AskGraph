/**
 * SQL AI Agent — Frontend Application
 * Multi-DB Intelligence Platform
 */

(() => {
    'use strict';

    // ===== CONFIG =====
    // Resolve against the page path so the app works at "/" or mounted at "/askgraph/".
    const API_BASE = new URL('.', window.location.href).href.replace(/\/$/, '');
    const TOAST_DURATION = 4000;
    // Expanded server-side from SAMPLE_DB_URL; see utils.resolve_db_url.
    const SAMPLE_DB_URL = 'preset:sample';

    // ===== STATE =====
    const state = {
        dbUrl: '',
        connected: false,
        safeMode: true,
        dialect: '',
        schemas: [],
        queryHistory: [],
        currentPage: 'connect',
        sidebarCollapsed: false,
        currentTable: null,
        dashboardCharts: [],
        healthFindings: [],
        healthSeverity: 'all',
        pagination: {
            page: 1,
            limit: 20,
            total: 0,
            totalPages: 1
        }
    };

    // ===== DOM REFS =====
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const dom = {
        sidebar: $('#sidebar'),
        sidebarToggle: $('#sidebarToggle'),
        toggleIcon: $('#toggleIcon'),
        mobileMenuBtn: $('#mobileMenuBtn'),
        mobileOverlay: $('#mobileOverlay'),
        headerTitle: $('#headerTitle'),
        statusChip: $('#statusChip'),
        statusText: $('#statusText'),
        dialectBadge: $('#dialectBadge'),
        safeModeToggle: $('#safeModeToggle'),
        themeToggle: $('#themeToggle'),

        // Connect
        dbUrlInput: $('#dbUrlInput'),
        dbSelect: $('#dbSelect'),
        connectBtn: $('#connectBtn'),
        sampleDbBtn: $('#sampleDbBtn'),
        connectingAnim: $('#connectingAnim'),

        // Schema
        schemaEmpty: $('#schemaEmpty'),
        schemaGrid: $('#schemaGrid'),
        schemaSkeleton: $('#schemaSkeleton'),
        schemaTablesList: $('#schemaTablesList'),
        schemaDetailView: $('#schemaDetailView'),

        // AI Query
        aiQueryInput: $('#aiQueryInput'),
        aiSendBtn: $('#aiSendBtn'),
        aiThinking: $('#aiThinking'),
        retryIndicator: $('#retryIndicator'),
        resultsArea: $('#resultsArea'),
        sqlOutput: $('#sqlOutput'),
        copySqlBtn: $('#copySqlBtn'),
        dataTable: $('#dataTable'),
        chartsGrid: $('#chartsGrid'),
        chartsEmpty: $('#chartsEmpty'),
        csvPreview: $('#csvPreview'),
        csvInfo: $('#csvInfo'),
        downloadCsvBtn: $('#downloadCsvBtn'),
        responseMessage: $('#responseMessage'),
        responseMessageText: $('#responseMessageText'),
        historyList: $('#historyList'),

        // Dashboard
        genDashboardBtn: $('#genDashboardBtn'),
        downloadAllBtn: $('#downloadAllBtn'),
        dashboardEmpty: $('#dashboardEmpty'),
        dashboardSkeleton: $('#dashboardSkeleton'),
        dashboardGrid: $('#dashboardGrid'),

        // Health
        runHealthBtn: $('#runHealthBtn'),
        healthEmpty: $('#healthEmpty'),
        healthSkeleton: $('#healthSkeleton'),
        healthResults: $('#healthResults'),
        healthScore: $('#healthScore'),
        healthScoreFill: $('#healthScoreFill'),
        healthVerdict: $('#healthVerdict'),
        healthSummary: $('#healthSummary'),
        healthFilters: $('#healthFilters'),
        healthList: $('#healthList'),
        healthSkipped: $('#healthSkipped'),

        // Optimizer
        optimizerInput: $('#optimizerInput'),
        optimizeBtn: $('#optimizeBtn'),
        optimizerResults: $('#optimizerResults'),
        optimizerSkeleton: $('#optimizerSkeleton'),
        perfScoreValue: $('#perfScoreValue'),
        perfScoreFill: $('#perfScoreFill'),
        origQueryDisplay: $('#origQueryDisplay'),
        optQueryDisplay: $('#optQueryDisplay'),
        copyOptimizedBtn: $('#copyOptimizedBtn'),
        explanationContent: $('#explanationContent'),

        // Modal
        chartModal: $('#chartModal'),
        chartModalTitle: $('#chartModalTitle'),
        chartModalClose: $('#chartModalClose'),
        chartModalImg: $('#chartModalImg'),
        chartNewTabBtn: $('#chartNewTabBtn'),

        // Toast
        toastContainer: $('#toastContainer'),
    };

    // ===== TOAST SYSTEM =====
    function showToast(message, type = 'info') {
        const icons = { success: '\u2713', error: '\u2715', warning: '!', info: '\u00b7' };
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
      <span class="toast-icon">${icons[type]}</span>
      <span>${escapeHtml(message)}</span>
    `;
        toast.addEventListener('click', () => removeToast(toast));
        dom.toastContainer.appendChild(toast);
        setTimeout(() => removeToast(toast), TOAST_DURATION);
    }

    function removeToast(toast) {
        if (!toast.parentNode) return;
        toast.classList.add('toast-out');
        setTimeout(() => toast.remove(), 200);
    }

    // ===== UTILITY =====
    // NULL is absence, not a value — render it as a token, not as data.
    function cell(v) {
        return v == null ? '<span class="null">NULL</span>' : escapeHtml(String(v));
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function detectDialect(url) {
        if (url.includes('postgres')) return 'postgres';
        if (url.includes('mysql')) return 'mysql';
        if (url.includes('oracle')) return 'oracle';
        return '';
    }

    function copyToClipboard(text) {
        navigator.clipboard.writeText(text).then(() => {
            showToast('Copied', 'success');
        }).catch(() => {
            showToast("Couldn't copy — copy it by hand", 'error');
        });
    }

    function formatTime(date) {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    async function apiCall(endpoint, body) {
        const res = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Request failed' }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        return res.json();
    }

    // ===== NAVIGATION =====
    const pageTitles = {
        connect: 'Connect a database',
        schema: 'Schema explorer',
        query: 'Ask',
        dashboard: 'Dashboard',
        health: 'Data health',
        optimizer: 'Optimizer',
    };

    function navigateTo(page) {
        state.currentPage = page;

        // Update nav items
        $$('.nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.page === page);
        });

        // Update pages
        $$('.page').forEach(p => {
            p.classList.toggle('active', p.id === `page-${page}`);
        });

        // Update header title
        dom.headerTitle.textContent = pageTitles[page] || page;

        // Close mobile sidebar
        dom.sidebar.classList.remove('mobile-open');
        dom.mobileOverlay.classList.remove('show');
    }

    // ===== SIDEBAR =====
    function toggleSidebar() {
        state.sidebarCollapsed = !state.sidebarCollapsed;
        dom.sidebar.classList.toggle('collapsed', state.sidebarCollapsed);
        dom.toggleIcon.textContent = state.sidebarCollapsed ? '▶' : '◀';
    }

    // ===== THEME =====
    function toggleTheme() {
        const html = document.documentElement;
        const current = html.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        html.setAttribute('data-theme', next);
        dom.themeToggle.textContent = next === 'dark' ? 'DARK' : 'LIGHT';
        localStorage.setItem('theme', next);
    }

    function loadTheme() {
        const saved = localStorage.getItem('theme') || 'dark';
        document.documentElement.setAttribute('data-theme', saved);
        dom.themeToggle.textContent = saved === 'dark' ? 'DARK' : 'LIGHT';
    }

    // ===== SAFE MODE =====
    function toggleSafeMode() {
        state.safeMode = !state.safeMode;
        dom.safeModeToggle.classList.toggle('active', state.safeMode);
        dom.safeModeToggle.setAttribute('aria-checked', state.safeMode);
        showToast(state.safeMode ? 'Safe mode on — SELECT only' : 'Safe mode off — every statement runs', state.safeMode ? 'success' : 'warning');
    }

    // ===== CONNECTION STATUS =====
    function updateConnectionStatus(connected, dialect) {
        state.connected = connected;
        state.dialect = dialect;

        dom.statusChip.className = `status-chip ${connected ? 'connected' : 'disconnected'}`;
        dom.statusText.textContent = connected ? 'Connected' : 'Disconnected';

        if (dialect) {
            dom.dialectBadge.textContent = dialect.toUpperCase();
            dom.dialectBadge.className = `dialect-badge ${dialect}`;
            dom.dialectBadge.classList.remove('hidden');
        } else {
            dom.dialectBadge.classList.add('hidden');
        }
    }

    // ===== CONNECT PAGE =====
    async function handleConnect() {
        const url = dom.dbUrlInput.value.trim();
        if (!url) {
            showToast('Enter a connection URL first', 'warning');
            dom.dbUrlInput.focus();
            return;
        }

        state.dbUrl = url;
        const dialect = detectDialect(url);

        // Show loading
        dom.connectBtn.disabled = true;
        dom.connectingAnim.classList.add('show');

        try {
            const data = await apiCall('/schemas', { db_url: url });
            state.schemas = data.tables || [];

            updateConnectionStatus(true, dialect);
            showToast(`Connected. ${state.schemas.length} tables.`, 'success');

            // Load schema page
            dom.connectingAnim.classList.remove('show');
            dom.connectBtn.disabled = false;
            loadSchemaList();
            navigateTo('schema');
        } catch (err) {
            dom.connectingAnim.classList.remove('show');
            dom.connectBtn.disabled = false;
            updateConnectionStatus(false, '');
            showToast(`Connection failed: ${err.message}`, 'error');
        }
    }

    // ===== SCHEMA EXPLORER =====
    function loadSchemaList() {
        if (!state.schemas.length) {
            dom.schemaEmpty.classList.remove('hidden');
            dom.schemaGrid.classList.add('hidden');
            return;
        }

        dom.schemaEmpty.classList.add('hidden');
        dom.schemaGrid.classList.remove('hidden');

        dom.schemaTablesList.innerHTML = state.schemas.map(table => `
      <div class="schema-table-item" data-table="${escapeHtml(table)}" tabindex="0" role="button" aria-label="View table ${escapeHtml(table)}">
        <span class="table-icon"></span>
        <span>${escapeHtml(table)}</span>
      </div>
    `).join('');

        // Reset detail view
        dom.schemaDetailView.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon"></div>
        <h3>Select a table</h3>
        <p>Pick a table from the list to see its columns and rows.</p>
      </div>
    `;
    }

    async function loadTableDetails(tableName) {
        state.currentTable = tableName;
        state.pagination.page = 1;

        // Mark active
        $$('.schema-table-item').forEach(item => {
            item.classList.toggle('active', item.dataset.table === tableName);
        });

        // Show skeleton
        dom.schemaDetailView.innerHTML = `
          <div class="skeleton skeleton-text" style="width:50%;margin-bottom:16px"></div>
          <div class="skeleton-row"><div class="skeleton"></div><div class="skeleton"></div></div>
          <div class="skeleton skeleton-block"></div>
        `;

        try {
            // Parallel fetch: Metadata + First Page Data
            const [metaData, pageData] = await Promise.all([
                apiCall(`/schemas/${encodeURIComponent(tableName)}`, { db_url: state.dbUrl }),
                apiCall(`/schemas/${encodeURIComponent(tableName)}/data`, {
                    db_url: state.dbUrl,
                    page: 1,
                    limit: state.pagination.limit
                })
            ]);

            state.pagination.total = pageData.total_rows;
            state.pagination.totalPages = pageData.total_pages;

            renderTableDetails(metaData, pageData.data);
        } catch (err) {
            dom.schemaDetailView.innerHTML = `
            <div class="empty-state">
              <div class="empty-icon"></div>
              <h3>Couldn't load that table</h3>
              <p>${escapeHtml(err.message)}</p>
            </div>
          `;
            showToast(`Failed to load table: ${err.message}`, 'error');
        }
    }

    async function loadTablePage(page) {
        if (!state.currentTable) return;
        state.pagination.page = page;

        // Show loading overlay on table
        const tableContainer = dom.schemaDetailView.querySelector('.data-table-wrapper');
        if (tableContainer) tableContainer.style.opacity = '0.5';

        try {
            const data = await apiCall(`/schemas/${encodeURIComponent(state.currentTable)}/data`, {
                db_url: state.dbUrl,
                page: page,
                limit: state.pagination.limit
            });

            state.pagination.total = data.total_rows;
            state.pagination.totalPages = data.total_pages;

            // Re-render just the data section
            updateTableData(data.data);
        } catch (err) {
            showToast(`Failed to load page ${page}: ${err.message}`, 'error');
            if (tableContainer) tableContainer.style.opacity = '1';
        }
    }

    function renderTableDetails(metaData, rows) {
        const columnsHtml = metaData.columns.map(col => `<span class="meta-chip"><code style="font-family:var(--font-mono);font-size:12px;">${escapeHtml(col)}</code></span>`).join('');

        dom.schemaDetailView.innerHTML = `
          <div class="schema-detail-header">
            <h3>${escapeHtml(metaData.table_name)}</h3>
          </div>
          <div class="schema-meta">
            <span class="meta-chip">Rows: <span class="meta-value" id="totalRowsCount">${state.pagination.total.toLocaleString()}</span></span>
            <span class="meta-chip">Columns: <span class="meta-value">${metaData.columns.length}</span></span>
          </div>
          <div class="schema-section">
            <h4>Columns</h4>
            <div style="display:flex;flex-wrap:wrap;gap:6px;max-height:100px;overflow-y:auto;padding-bottom:10px;">${columnsHtml}</div>
          </div>
          <div class="schema-section">
            <div class="flex items-center justify-between mb-sm">
                <h4>Rows</h4>
                <div class="pagination-controls">
                    <button class="btn btn-sm btn-ghost" id="prevPageBtn" disabled>Prev</button>
                    <span class="text-secondary" style="font-size:12px;">Page <span id="curPageDisplay">1</span> of <span id="totalPagesDisplay">${state.pagination.totalPages}</span></span>
                    <button class="btn btn-sm btn-ghost" id="nextPageBtn" ${state.pagination.totalPages <= 1 ? 'disabled' : ''}>Next</button>
                </div>
            </div>
            <div id="tableContainer">
                ${renderTableHTML(rows, metaData.columns)}
            </div>
          </div>
        `;

        // Animate in
        dom.schemaDetailView.style.animation = 'none';
        dom.schemaDetailView.offsetHeight; // trigger reflow
        dom.schemaDetailView.style.animation = 'pageIn var(--duration-slow) var(--ease-default)';

        bindPaginationEvents();
    }

    function renderTableHTML(rows, explicitColumns = null) {
        if (!rows || !rows.length) return `<div class="empty-state" style="padding:20px;"><p class="text-secondary">No rows</p></div>`;

        const cols = explicitColumns || Object.keys(rows[0]);
        return `
            <div class="data-table-wrapper" style="max-height:400px;overflow:auto;">
              <table class="data-table">
                <thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>
                <tbody>${rows.map(r => `<tr>${cols.map(c => `<td title="${escapeHtml(String(r[c] ?? ''))}">${cell(r[c])}</td>`).join('')}</tr>`).join('')}</tbody>
              </table>
            </div>
        `;
    }

    function updateTableData(rows) {
        // We need columns from somewhere. Since we are updating, we assume the table structure is known.
        // We can get columns from the first row if available, or we might need to store columns in state.
        // For now, let's try to infer from data or use the existing header if possible.
        // Better: store columns in state.

        // Actually, let's just grab the headers from the DOM to be safe if 'rows' is empty? 
        // No, if rows is empty we can't infer.
        // Let's modify renderTableDetails to store columns in a closure or state if needed.
        // Simpler: Just render with keys of first row. If empty, the specific message is shown.

        let cols = null;
        const existingThs = dom.schemaDetailView.querySelectorAll('.data-table th');
        if (existingThs.length) {
            cols = Array.from(existingThs).map(th => th.textContent);
        }

        const container = document.getElementById('tableContainer');
        if (container) {
            container.innerHTML = renderTableHTML(rows, cols);
            container.style.opacity = '1';
        }

        // Update controls
        document.getElementById('curPageDisplay').textContent = state.pagination.page;
        document.getElementById('totalPagesDisplay').textContent = state.pagination.totalPages;
        document.getElementById('totalRowsCount').textContent = state.pagination.total.toLocaleString();

        document.getElementById('prevPageBtn').disabled = state.pagination.page <= 1;
        document.getElementById('nextPageBtn').disabled = state.pagination.page >= state.pagination.totalPages;
    }

    function bindPaginationEvents() {
        const prevBtn = document.getElementById('prevPageBtn');
        const nextBtn = document.getElementById('nextPageBtn');

        if (prevBtn) {
            prevBtn.addEventListener('click', () => {
                if (state.pagination.page > 1) loadTablePage(state.pagination.page - 1);
            });
        }

        if (nextBtn) {
            nextBtn.addEventListener('click', () => {
                if (state.pagination.page < state.pagination.totalPages) loadTablePage(state.pagination.page + 1);
            });
        }
    }

    // ===== AI QUERY =====
    async function handleAIQuery() {
        const query = dom.aiQueryInput.value.trim();
        if (!query) {
            showToast('Type a question first', 'warning');
            dom.aiQueryInput.focus();
            return;
        }
        if (!state.dbUrl) {
            showToast('Connect a database first', 'warning');
            return;
        }

        // Show thinking
        dom.aiSendBtn.disabled = true;
        dom.aiThinking.classList.add('show');
        dom.resultsArea.classList.add('hidden');
        dom.responseMessage.classList.add('hidden');
        dom.retryIndicator.classList.add('hidden');

        try {
            const data = await apiCall('/generate', {
                db_url: state.dbUrl,
                query: query,
                safe_mode: state.safeMode,
            });

            dom.aiThinking.classList.remove('show');
            dom.aiSendBtn.disabled = false;

            if (data.error) {
                showToast(`Error: ${data.error}`, 'error');
                if (data.sql_query) {
                    renderQueryResults(data);
                }
                return;
            }

            // Check for self-healing
            if (data.message && data.message.includes('auto-correction')) {
                dom.retryIndicator.classList.remove('hidden');
            }

            renderQueryResults(data);
            addToHistory(query);

            if (data.message) {
                dom.responseMessage.classList.remove('hidden');
                dom.responseMessageText.textContent = data.message;
            }

            showToast('Query ran', 'success');
        } catch (err) {
            dom.aiThinking.classList.remove('show');
            dom.aiSendBtn.disabled = false;
            showToast(`Query failed: ${err.message}`, 'error');
        }
    }

    function renderQueryResults(data) {
        dom.resultsArea.classList.remove('hidden');

        // SQL Output with typewriter effect
        typewriterEffect(dom.sqlOutput, data.sql_query || 'No SQL generated');

        // Data Table
        if (data.data_preview && data.data_preview.length) {
            const cols = Object.keys(data.data_preview[0]);
            let tableHtml = `
        <thead><tr>${cols.map(c => `<th data-col="${escapeHtml(c)}">${escapeHtml(c)} <span class="sort-icon">↕</span></th>`).join('')}</tr></thead>
        <tbody>${data.data_preview.map(row => `<tr>${cols.map(c => `<td title="${escapeHtml(String(row[c] ?? ''))}">${cell(row[c])}</td>`).join('')}</tr>`).join('')}</tbody>
      `;
            dom.dataTable.innerHTML = tableHtml;
            dom.dataTable.dataset.rows = JSON.stringify(data.data_preview);
        } else {
            dom.dataTable.innerHTML = '<tbody><tr><td style="text-align:center;padding:24px;color:var(--text-tertiary);">No rows</td></tr></tbody>';
        }

        // Charts
        if (data.graphs_base64 && data.graphs_base64.length) {
            dom.chartsGrid.innerHTML = data.graphs_base64.map((img, i) => `
        <div class="card chart-card" style="animation-delay:${i * 100}ms;" data-img="${img}" role="button" aria-label="View chart fullscreen">
          <img src="data:image/png;base64,${img}" alt="Chart ${i + 1}">
        </div>
      `).join('');
            dom.chartsEmpty.classList.add('hidden');
            dom.chartsGrid.classList.remove('hidden');
        } else {
            dom.chartsGrid.innerHTML = '';
            dom.chartsGrid.classList.add('hidden');
            dom.chartsEmpty.classList.remove('hidden');
        }

        // CSV
        if (data.csv_base64) {
            const csvText = atob(data.csv_base64);
            const lines = csvText.split('\n');
            dom.csvPreview.textContent = lines.slice(0, 20).join('\n') + (lines.length > 20 ? '\n...' : '');
            dom.csvInfo.textContent = `${lines.length - 1} rows`;
            dom.downloadCsvBtn.onclick = () => downloadCSV(csvText, 'query_results.csv');
        } else {
            dom.csvPreview.textContent = 'No CSV for this result';
            dom.csvInfo.textContent = '';
        }

        // Reset to table tab
        switchTab('table-tab');
    }

    function typewriterEffect(element, text) {
        element.textContent = '';
        element.classList.add('typewriter');
        let i = 0;
        const speed = Math.max(5, Math.min(30, 1500 / text.length));
        function type() {
            if (i < text.length) {
                element.textContent += text.charAt(i);
                i++;
                setTimeout(type, speed);
            } else {
                element.classList.remove('typewriter');
            }
        }
        type();
    }

    /**
     * Save a blob to disk. The anchor is put in the document and the object URL
     * is revoked on a timeout — revoking it in the same tick can cancel the
     * download before the browser has read the blob, and Safari ignores a click
     * on an anchor that was never in the DOM.
     */
    function downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
            a.remove();
            URL.revokeObjectURL(url);
        }, 1000);
    }

    function downloadCSV(csvText, filename) {
        downloadBlob(new Blob([csvText], { type: 'text/csv' }), filename);
        showToast('CSV downloaded', 'success');
    }

    function base64ToBlob(base64, type) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        return new Blob([bytes], { type });
    }

    /** Posts the charts back to be zipped — the browser has no zip of its own. */
    async function downloadAllCharts() {
        // Failed panels leave holes in the array; the server numbers what it gets.
        const charts = state.dashboardCharts.filter(Boolean).map(c => ({
            title: c.title,
            description: c.description,
            graph_base64: c.graph_base64,
        }));
        if (!charts.length) {
            showToast('No charts to download yet', 'warning');
            return;
        }

        dom.downloadAllBtn.disabled = true;
        const original = dom.downloadAllBtn.textContent;
        dom.downloadAllBtn.textContent = 'Zipping…';

        try {
            const res = await fetch(`${API_BASE}/dashboard/export`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ charts }),
            });
            if (!res.ok) {
                const detail = await res.json().catch(() => ({}));
                throw new Error(detail.detail || `HTTP ${res.status}`);
            }
            downloadBlob(await res.blob(), 'askgraph-dashboard.zip');
            showToast(`Downloaded ${charts.length} chart${charts.length === 1 ? '' : 's'} as a zip`, 'success');
        } catch (err) {
            showToast(`Download failed: ${err.message}`, 'error');
        } finally {
            dom.downloadAllBtn.textContent = original;
            dom.downloadAllBtn.disabled = false;
        }
    }

    // "Revenue peaked in Q3" -> "revenue-peaked-in-q3"
    function slugify(text) {
        // Trim after the length cap too — slicing mid-word can leave a
        // trailing dash on the filename.
        const slug = (text || '').toLowerCase().replace(/[^a-z0-9]+/g, '-')
            .slice(0, 60).replace(/^-+|-+$/g, '');
        return slug || 'chart';
    }

    /** Saves the panel as a .png plus a .txt holding its name and description. */
    function downloadChart(title, description, imgBase64) {
        if (!imgBase64) {
            showToast('That panel has no image to download', 'warning');
            return;
        }
        const name = slugify(title);
        const notes = `${title || 'Chart'}\n\n${description || 'No description.'}\n`;

        downloadBlob(base64ToBlob(imgBase64, 'image/png'), `${name}.png`);
        // Two saves from one click; the second is delayed so the browser treats
        // it as part of the same user gesture rather than dropping it.
        setTimeout(() => {
            downloadBlob(new Blob([notes], { type: 'text/plain' }), `${name}.txt`);
            showToast(`Downloaded ${name}.png and ${name}.txt`, 'success');
        }, 150);
    }

    // Table sorting
    function sortTable(colIdx, ascending) {
        const rows = JSON.parse(dom.dataTable.dataset.rows || '[]');
        if (!rows.length) return;
        const keys = Object.keys(rows[0]);
        const key = keys[colIdx];
        rows.sort((a, b) => {
            const va = a[key], vb = b[key];
            if (va == null) return 1;
            if (vb == null) return -1;
            if (typeof va === 'number') return ascending ? va - vb : vb - va;
            return ascending ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
        });
        dom.dataTable.dataset.rows = JSON.stringify(rows);
        const cols = keys;
        const tbody = dom.dataTable.querySelector('tbody');
        tbody.innerHTML = rows.map(row => `<tr>${cols.map(c => `<td title="${escapeHtml(String(row[c] ?? ''))}">${cell(row[c])}</td>`).join('')}</tr>`).join('');
    }

    // ===== TABS =====
    function switchTab(tabId) {
        $$('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabId);
            btn.setAttribute('aria-selected', btn.dataset.tab === tabId);
        });
        $$('.tab-content').forEach(c => {
            c.classList.toggle('active', c.id === tabId);
        });
    }

    // ===== QUERY HISTORY =====
    function addToHistory(query) {
        state.queryHistory.unshift({ query, time: new Date() });
        if (state.queryHistory.length > 20) state.queryHistory.pop();
        renderHistory();
    }

    function renderHistory() {
        if (!state.queryHistory.length) return;
        dom.historyList.innerHTML = state.queryHistory.map((item, i) => `
      <div class="history-item" data-idx="${i}" tabindex="0" role="button" aria-label="Re-run query: ${escapeHtml(item.query.substring(0, 50))}">
        <span class="history-query">${escapeHtml(item.query)}</span>
        <span class="history-time">${formatTime(item.time)}</span>
      </div>
    `).join('');
    }

    // ===== DASHBOARD =====
    async function handleGenDashboard() {
        if (!state.dbUrl) {
            showToast('Connect a database first', 'warning');
            return;
        }

        dom.genDashboardBtn.disabled = true;
        dom.dashboardEmpty.classList.add('hidden');
        dom.dashboardGrid.classList.add('hidden');
        dom.dashboardGrid.innerHTML = '';
        state.dashboardCharts = [];
        dom.downloadAllBtn.disabled = true;
        // The static skeleton covers the planning call, before any panel exists.
        dom.dashboardSkeleton.classList.remove('hidden');

        let built = 0, failed = 0, planned = 0;

        try {
            const res = await fetch(`${API_BASE}/gen-dashboard/stream`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ db_url: state.dbUrl }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            let streamError = null;

            await readNdjson(res, (frame) => {
                if (frame.type === 'plan') {
                    planned = frame.panels.length;
                    dom.dashboardSkeleton.classList.add('hidden');
                    renderDashboardPlaceholders(frame.panels);
                } else if (frame.type === 'chart') {
                    built++;
                    state.dashboardCharts[frame.index] = frame.chart;
                    dom.downloadAllBtn.disabled = false;
                    fillDashboardCard(frame.index, frame.chart);
                } else if (frame.type === 'failed') {
                    failed++;
                    failDashboardCard(frame.index, frame.failed);
                } else if (frame.type === 'error') {
                    streamError = frame.error;
                }
            });

            dom.dashboardSkeleton.classList.add('hidden');
            dom.genDashboardBtn.disabled = false;

            if (streamError) {
                dom.dashboardEmpty.classList.remove('hidden');
                showToast(`Dashboard error: ${streamError}`, 'error');
                return;
            }
            if (!planned) {
                dom.dashboardEmpty.classList.remove('hidden');
                showToast('No insights came back for this schema', 'warning');
                return;
            }

            showToast(
                failed ? `Dashboard ready — ${built} of ${planned} panels built`
                       : `Dashboard ready — ${built} insight${built === 1 ? '' : 's'}`,
                built ? 'success' : 'error');
        } catch (err) {
            dom.dashboardSkeleton.classList.add('hidden');
            dom.genDashboardBtn.disabled = false;
            if (!built) dom.dashboardEmpty.classList.remove('hidden');
            showToast(`Dashboard failed: ${err.message}`, 'error');
        }
    }

    /**
     * Read an NDJSON response, calling onFrame once per complete line.
     * A chunk can split a line anywhere, so the tail is held back until the
     * next chunk completes it.
     */
    async function readNdjson(res, onFrame) {
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop();   // last element is a partial line, or ''
            for (const line of lines) {
                if (line.trim()) onFrame(JSON.parse(line));
            }
        }
        if (buffer.trim()) onFrame(JSON.parse(buffer));
    }

    function dashboardCard(i) {
        return dom.dashboardGrid.querySelector(`[data-index="${i}"]`);
    }

    // One card per planned panel, in planned order, each waiting for its chart.
    // Panels arrive out of order, so the slots have to exist up front.
    function renderDashboardPlaceholders(panels) {
        dom.dashboardGrid.classList.remove('hidden');
        dom.dashboardGrid.innerHTML = panels.map((p, i) => `
      <div class="card dashboard-card dashboard-card-pending animate-in" data-index="${i}"
           style="animation-delay:${i * 60}ms;">
        <div class="card-content">
          <h4>${escapeHtml(p.title)}</h4>
          <p>${escapeHtml(p.description)}</p>
          <div class="skeleton skeleton-block"></div>
        </div>
      </div>
    `).join('');
    }

    function fillDashboardCard(i, chart) {
        const card = dashboardCard(i);
        if (!card) return;
        card.classList.remove('dashboard-card-pending');
        card.dataset.img = chart.graph_base64;
        card.dataset.title = chart.title;
        card.dataset.description = chart.description || '';
        card.innerHTML = `
      <div class="card-actions">
        <button class="fullscreen-hint" type="button"
                aria-label="View ${escapeHtml(chart.title)} full size">Expand</button>
        <button class="chart-download-btn" type="button"
                aria-label="Download ${escapeHtml(chart.title)} as PNG and TXT">Download</button>
      </div>
      <div class="card-content">
        <h4>${escapeHtml(chart.title)}</h4>
        <p>${escapeHtml(chart.description)}</p>
        <img src="data:image/png;base64,${chart.graph_base64}" alt="${escapeHtml(chart.title)}">
      </div>`;
    }

    // Failures used to be returned and never shown. The placeholder is already
    // on screen, so say what happened to it instead of leaving it spinning.
    function failDashboardCard(i, failure) {
        const card = dashboardCard(i);
        if (!card) return;
        card.classList.remove('dashboard-card-pending');
        card.classList.add('dashboard-card-failed');
        card.innerHTML = `
      <div class="card-content">
        <h4>${escapeHtml(failure.title)}</h4>
        <p class="dashboard-fail-reason">${escapeHtml(failure.reason)}</p>
      </div>`;
    }

    // ===== DATA HEALTH =====
    async function handleHealthCheck() {
        if (!state.dbUrl) {
            showToast('Connect a database first', 'warning');
            return;
        }

        dom.runHealthBtn.disabled = true;
        dom.healthEmpty.classList.add('hidden');
        dom.healthResults.classList.add('hidden');
        dom.healthSkeleton.classList.remove('hidden');

        try {
            const data = await apiCall('/data-health', { db_url: state.dbUrl });

            dom.healthSkeleton.classList.add('hidden');
            dom.runHealthBtn.disabled = false;

            if (data.error) {
                dom.healthEmpty.classList.remove('hidden');
                showToast(`Health check failed: ${data.error}`, 'error');
                return;
            }

            state.healthFindings = data.findings || [];
            state.healthSeverity = 'all';
            renderHealth(data);

            const n = state.healthFindings.length;
            showToast(n ? `${n} issue${n === 1 ? '' : 's'} found` : 'No issues found', n ? 'warning' : 'success');
        } catch (err) {
            dom.healthSkeleton.classList.add('hidden');
            dom.runHealthBtn.disabled = false;
            dom.healthEmpty.classList.remove('hidden');
            showToast(`Health check failed: ${err.message}`, 'error');
        }
    }

    function renderHealth(data) {
        dom.healthResults.classList.remove('hidden');

        const findings = state.healthFindings;
        const counts = { high: 0, medium: 0, low: 0 };
        findings.forEach(f => { counts[f.severity] = (counts[f.severity] || 0) + 1; });

        dom.healthScore.textContent = data.score;
        dom.healthScore.dataset.band = data.score >= 85 ? 'good' : data.score >= 50 ? 'warn' : 'bad';
        dom.healthScoreFill.style.width = `${data.score}%`;
        dom.healthScoreFill.dataset.band = dom.healthScore.dataset.band;

        const tables = `${data.tables_checked} table${data.tables_checked === 1 ? '' : 's'}`;
        dom.healthVerdict.textContent = findings.length
            ? `${findings.length} issue${findings.length === 1 ? '' : 's'} across ${tables}`
            : `Nothing wrong across ${tables}`;
        dom.healthSummary.textContent = findings.length
            ? `${counts.high} high, ${counts.medium} medium, ${counts.low} low.`
            : 'Every probe came back clean.';

        // Counts on the filter chips, so an empty severity is obvious before clicking.
        $$('#healthFilters .chip').forEach(chip => {
            const sev = chip.dataset.severity;
            const n = sev === 'all' ? findings.length : (counts[sev] || 0);
            chip.textContent = `${sev === 'all' ? 'All' : sev[0].toUpperCase() + sev.slice(1)} ${n}`;
            chip.classList.toggle('chip-active', sev === state.healthSeverity);
        });

        renderHealthList();

        const skipped = data.skipped || [];
        dom.healthSkipped.classList.toggle('hidden', !skipped.length);
        if (skipped.length) {
            dom.healthSkipped.innerHTML = `<h4>Not checked</h4>` + skipped.map(s => `
        <div class="health-skipped-item">
          <span class="mono">${escapeHtml(s.table)}</span>
          <span>${escapeHtml(s.reason)}</span>
        </div>`).join('');
        }
    }

    function renderHealthList() {
        const shown = state.healthSeverity === 'all'
            ? state.healthFindings
            : state.healthFindings.filter(f => f.severity === state.healthSeverity);

        if (!shown.length) {
            dom.healthList.innerHTML = `<div class="empty-state"><h3>Nothing here</h3>
        <p>No ${escapeHtml(state.healthSeverity)} findings.</p></div>`;
            return;
        }

        dom.healthList.innerHTML = shown.map((f, i) => `
      <div class="health-item animate-in" style="animation-delay:${Math.min(i, 12) * 40}ms;">
        <span class="health-badge health-${escapeHtml(f.severity)}">${escapeHtml(f.severity)}</span>
        <div class="health-item-body">
          <h4>${escapeHtml(f.issue)}</h4>
          <p>${escapeHtml(f.detail)}</p>
          <span class="health-target mono">${escapeHtml(f.table)}${f.column ? '.' + escapeHtml(f.column) : ''}</span>
        </div>
      </div>
    `).join('');
    }

    // ===== SQL OPTIMIZER =====
    async function handleOptimize() {
        const sql = dom.optimizerInput.value.trim();
        if (!sql) {
            showToast('Paste a query first', 'warning');
            dom.optimizerInput.focus();
            return;
        }
        if (!state.dbUrl) {
            showToast('Connect a database first', 'warning');
            return;
        }

        dom.optimizeBtn.disabled = true;
        dom.optimizerResults.classList.add('hidden');
        dom.optimizerSkeleton.classList.remove('hidden');

        try {
            const data = await apiCall('/optimize', {
                db_url: state.dbUrl,
                query: sql,
            });

            dom.optimizerSkeleton.classList.add('hidden');
            dom.optimizeBtn.disabled = false;

            renderOptimizerResults(data);
            showToast('Query rewritten', 'success');
        } catch (err) {
            dom.optimizerSkeleton.classList.add('hidden');
            dom.optimizeBtn.disabled = false;
            showToast(`Optimization failed: ${err.message}`, 'error');
        }
    }

    function renderOptimizerResults(data) {
        dom.optimizerResults.classList.remove('hidden');

        // Performance score with animation
        const score = Math.min(100, Math.max(0, data.difference_score || 0));
        const scoreClass = score < 30 ? 'low' : score < 70 ? 'medium' : 'high';
        dom.perfScoreValue.textContent = `${score}%`;
        dom.perfScoreFill.className = `perf-score-fill ${scoreClass}`;
        setTimeout(() => {
            dom.perfScoreFill.style.width = `${score}%`;
        }, 100);

        // Original query
        dom.origQueryDisplay.textContent = data.original_query;

        // Optimized query
        dom.optQueryDisplay.textContent = data.optimized_query;

        // Explanation (render markdown-like content)
        dom.explanationContent.innerHTML = renderMarkdown(data.explanation);

        // Scroll into view
        dom.optimizerResults.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function renderMarkdown(text) {
        if (!text) return '<p>No explanation provided.</p>';
        // Simple markdown rendering
        return text
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/`(.+?)`/g, '<code style="background:var(--bg-tertiary);padding:2px 6px;border-radius:4px;font-family:var(--font-mono);font-size:12px;">$1</code>')
            .replace(/\n\n/g, '</p><p>')
            .replace(/\n- /g, '</p><li>')
            .replace(/\n/g, '<br>')
            .replace(/^/, '<p>')
            .replace(/$/, '</p>');
    }

    // ===== MODAL =====
    function openChartModal(imgBase64, title) {
        dom.chartModalImg.src = `data:image/png;base64,${imgBase64}`;
        dom.chartModalTitle.textContent = title || 'Chart';
        dom.chartModal.classList.add('open');
        dom.chartModal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
    }

    function closeChartModal() {
        dom.chartModal.classList.remove('open');
        dom.chartModal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
    }

    // ===== INIT DBs =====
    async function initDBs() {
        try {
            const res = await fetch(`${API_BASE}/databases`);
            const data = await res.json();
            if (data.databases && dom.dbSelect) {
                const selectList = data.databases.map(db => `<option value="${db}">${db}</option>`).join('');
                dom.dbSelect.innerHTML = `<option value="">Custom URL</option>` + selectList;
                
                dom.dbSelect.addEventListener('change', (e) => {
                    if (e.target.value) {
                        // Server-side alias. The connection string (and its
                        // password) stays on the server; see utils.resolve_db_url.
                        dom.dbUrlInput.value = "preset:" + e.target.value;
                    }
                });
            }
        } catch (e) {
            console.error("Failed to load databases", e);
        }
    }

    // ===== EVENT LISTENERS =====
    function initEvents() {
        // Navigation
        $$('.nav-item').forEach(item => {
            item.addEventListener('click', () => navigateTo(item.dataset.page));
            item.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    navigateTo(item.dataset.page);
                }
            });
        });

        // Sidebar toggle
        dom.sidebarToggle.addEventListener('click', toggleSidebar);

        // Mobile
        dom.mobileMenuBtn.addEventListener('click', () => {
            dom.sidebar.classList.toggle('mobile-open');
            dom.mobileOverlay.classList.toggle('show');
        });
        dom.mobileOverlay.addEventListener('click', () => {
            dom.sidebar.classList.remove('mobile-open');
            dom.mobileOverlay.classList.remove('show');
        });

        // Theme
        dom.themeToggle.addEventListener('click', toggleTheme);

        // Safe mode
        dom.safeModeToggle.addEventListener('click', toggleSafeMode);
        dom.safeModeToggle.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                toggleSafeMode();
            }
        });

        // Connect
        dom.connectBtn.addEventListener('click', handleConnect);
        dom.dbUrlInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') handleConnect();
        });

        // Presets
        $$('.preset-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                dom.dbUrlInput.value = btn.dataset.preset;
                dom.dbUrlInput.focus();
            });
        });

        dom.sampleDbBtn?.addEventListener('click', () => {
            dom.dbUrlInput.value = SAMPLE_DB_URL;
            handleConnect();
        });

        // Schema table clicks
        dom.schemaTablesList.addEventListener('click', (e) => {
            const item = e.target.closest('.schema-table-item');
            if (item) loadTableDetails(item.dataset.table);
        });

        // Data health
        dom.runHealthBtn.addEventListener('click', handleHealthCheck);
        dom.healthFilters.addEventListener('click', (e) => {
            const chip = e.target.closest('.chip');
            if (!chip) return;
            state.healthSeverity = chip.dataset.severity;
            $$('#healthFilters .chip').forEach(c => c.classList.toggle('chip-active', c === chip));
            renderHealthList();
        });

        // AI Query
        dom.aiSendBtn.addEventListener('click', handleAIQuery);
        dom.aiQueryInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleAIQuery();
            }
        });

        // Auto-resize textarea
        dom.aiQueryInput.addEventListener('input', () => {
            dom.aiQueryInput.style.height = 'auto';
            dom.aiQueryInput.style.height = Math.min(200, dom.aiQueryInput.scrollHeight) + 'px';
        });

        // Copy SQL
        dom.copySqlBtn.addEventListener('click', () => {
            copyToClipboard(dom.sqlOutput.textContent);
        });

        // Tabs
        $$('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => switchTab(btn.dataset.tab));
        });

        // Table sorting
        dom.dataTable.addEventListener('click', (e) => {
            const th = e.target.closest('th');
            if (!th) return;
            const idx = Array.from(th.parentNode.children).indexOf(th);
            const asc = th.dataset.sort !== 'asc';
            th.dataset.sort = asc ? 'asc' : 'desc';
            // Reset other headers
            th.parentNode.querySelectorAll('th').forEach(h => {
                if (h !== th) h.dataset.sort = '';
            });
            sortTable(idx, asc);
        });

        dom.downloadAllBtn.addEventListener('click', downloadAllCharts);

        // Dashboard panel downloads. Bound on the grid so it runs before the
        // document-level fullscreen handler below.
        dom.dashboardGrid.addEventListener('click', (e) => {
            const btn = e.target.closest('.chart-download-btn');
            if (!btn) return;
            e.stopPropagation();
            const card = btn.closest('.dashboard-card');
            downloadChart(card.dataset.title, card.dataset.description, card.dataset.img);
        });

        // Chart fullscreen clicks
        document.addEventListener('click', (e) => {
            const chartCard = e.target.closest('.chart-card, .dashboard-card');
            if (chartCard && chartCard.dataset.img) {
                openChartModal(chartCard.dataset.img, chartCard.dataset.title || 'Chart');
            }
        });

        // Modal actions
        dom.chartModalClose.addEventListener('click', closeChartModal);
        dom.chartNewTabBtn.addEventListener('click', () => {
            const win = window.open();
            win.document.write(`<iframe src="${dom.chartModalImg.src}" frameborder="0" style="border:0; top:0px; left:0px; bottom:0px; right:0px; width:100%; height:100%;" allowfullscreen></iframe>`);
        });
        dom.chartModal.addEventListener('click', (e) => {
            if (e.target === dom.chartModal) closeChartModal();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeChartModal();
        });

        // Dashboard
        dom.genDashboardBtn.addEventListener('click', handleGenDashboard);

        // Optimizer
        dom.optimizeBtn.addEventListener('click', handleOptimize);
        dom.copyOptimizedBtn.addEventListener('click', () => {
            copyToClipboard(dom.optQueryDisplay.textContent);
        });

        // History clicks
        dom.historyList.addEventListener('click', (e) => {
            const item = e.target.closest('.history-item');
            if (item) {
                const idx = parseInt(item.dataset.idx);
                if (state.queryHistory[idx]) {
                    dom.aiQueryInput.value = state.queryHistory[idx].query;
                    dom.aiQueryInput.dispatchEvent(new Event('input'));
                }
            }
        });
    }

    // ===== INIT =====
    function init() {
        loadTheme();
        initEvents();
        initDBs();
        navigateTo('connect');
    }

    // Go!
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
