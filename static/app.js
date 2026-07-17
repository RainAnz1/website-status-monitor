const API_BASE = "";
const DEFAULT_REFRESH_SECONDS = 60;
const REFRESH_STORAGE_KEY = "site-monitor-refresh-seconds";

const state = {
    mode: document.body.dataset.page || "display",
    sites: [],
    loading: false,
    query: "",
    filter: "all",
    sort: "priority",
    refreshSeconds: readRefreshSeconds(),
    refreshIn: readRefreshSeconds(),
    pendingChecks: new Set(),
    pendingDelete: new Set(),
    checkingAll: false,
    lastFocusedElement: null
};

const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", () => {
    bindCommonControls();
    bindAdminControls();
    loadSites();
    window.setInterval(tickRefresh, 1000);
});

function bindCommonControls() {
    $("refreshButton")?.addEventListener("click", () => loadSites());
    $("searchInput")?.addEventListener("input", (event) => {
        state.query = event.target.value.trim().toLowerCase();
        render();
    });
    $("statusFilter")?.addEventListener("change", (event) => {
        state.filter = event.target.value;
        render();
    });
    $("sortSelect")?.addEventListener("change", (event) => {
        state.sort = event.target.value;
        render();
    });
    $("saveRefreshButton")?.addEventListener("click", saveRefreshSetting);
    $("refreshInterval")?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            saveRefreshSetting();
        }
    });
    $("closeHistoryButton")?.addEventListener("click", closeHistory);
    $("historyModal")?.addEventListener("click", (event) => {
        if (event.target.id === "historyModal") closeHistory();
    });
    $("sitesContainer")?.addEventListener("click", handleSiteAction);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && $("historyModal")?.classList.contains("open")) {
            closeHistory();
        }
    });

    const refreshInput = $("refreshInterval");
    if (refreshInput) {
        refreshInput.value = String(state.refreshSeconds);
        refreshInput.addEventListener("change", saveRefreshSetting);
    }
    updateRefreshState();
}

function bindAdminControls() {
    if (state.mode !== "admin") return;

    $("addForm")?.addEventListener("submit", addSite);
    $("checkAllButton")?.addEventListener("click", checkAllSites);
}

async function loadSites(options = {}) {
    const silent = Boolean(options.silent);
    state.loading = true;
    setButtonLoading("refreshButton", true, "刷新中");
    if (!silent) renderLoading();

    try {
        const response = await fetch(`${API_BASE}/api/sites`);
        if (!response.ok) throw new Error(`加载失败：${response.status}`);
        state.sites = await response.json();
        resetRefreshCountdown();
        render();
    } catch (error) {
        renderError(error.message || "加载失败");
        toast(error.message || "加载失败", "error");
    } finally {
        state.loading = false;
        setButtonLoading("refreshButton", false, "刷新数据");
        updateRefreshState();
        updateAdminButtonState();
    }
}

function renderLoading() {
    const container = $("sitesContainer");
    if (!container) return;
    container.innerHTML = `
        <div class="loading">
            <div>
                <div class="spinner"></div>
                <div>正在加载监控数据...</div>
            </div>
        </div>
    `;
}

function renderError(message) {
    const container = $("sitesContainer");
    if (!container) return;
    container.innerHTML = `
        <div class="error-state">
            <div>
                <strong>数据加载失败</strong>
                <div class="state-detail">${escapeHtml(message)}</div>
            </div>
        </div>
    `;
}

function render() {
    updateSummary();
    updateAdminButtonState();

    const container = $("sitesContainer");
    if (!container) return;

    const sites = getVisibleSites();
    if (state.sites.length === 0) {
        const emptyText = state.mode === "admin"
            ? "添加第一个网站后，会立即执行一次检测。"
            : "当前还没有展示内容，请进入后台添加监控站点。";
        container.innerHTML = `
            <div class="empty">
                <div>
                    <strong>还没有监控站点</strong>
                    <div class="state-detail">${emptyText}</div>
                </div>
            </div>
        `;
        return;
    }

    if (sites.length === 0) {
        container.innerHTML = `
            <div class="empty">
                <div>
                    <strong>没有匹配的站点</strong>
                    <div class="state-detail">试试调整搜索关键词或筛选条件。</div>
                </div>
            </div>
        `;
        return;
    }

    container.innerHTML = `<div class="sites-grid">${sites.map(renderSite).join("")}</div>`;
}

function getVisibleSites() {
    const rank = { down: 0, unknown: 1, up: 2 };
    return state.sites
        .filter((site) => {
            const text = `${site.name} ${site.url}`.toLowerCase();
            const queryMatch = !state.query || text.includes(state.query);
            let filterMatch = true;
            if (state.filter === "ssl-risk") {
                filterMatch = site.ssl_days_left !== null && site.ssl_days_left <= 14;
            } else if (state.filter !== "all") {
                filterMatch = site.status === state.filter;
            }
            return queryMatch && filterMatch;
        })
        .sort((a, b) => {
            if (state.sort === "name") return a.name.localeCompare(b.name, "zh-CN");
            if (state.sort === "response") return nullableNumber(a.response_time) - nullableNumber(b.response_time);
            if (state.sort === "latest") return parseTime(b.checked_at) - parseTime(a.checked_at);
            return (rank[a.status] ?? 3) - (rank[b.status] ?? 3) || parseTime(b.checked_at) - parseTime(a.checked_at);
        });
}

function renderSite(site) {
    const statusClass = getStatusClass(site.status);
    const statusText = getStatusText(site.status);
    const responseClass = getResponseClass(site.response_time);
    const sslClass = getSslClass(site.ssl_days_left);
    const uptimeClass = site.uptime === null ? "" : site.uptime >= 99 ? "good" : site.uptime >= 95 ? "warn" : "bad";
    const isChecking = state.pendingChecks.has(site.id);
    const isDeleting = state.pendingDelete.has(site.id);
    const errorHtml = site.error_msg ? `<div class="message error">${escapeHtml(site.error_msg)}</div>` : "";
    const sslWarning = site.ssl_days_left !== null && site.ssl_days_left <= 14
        ? `<div class="message warn">SSL 证书将在 ${site.ssl_days_left} 天内到期，请提前续签。</div>`
        : "";
    const actionsHtml = state.mode === "admin" ? `
        <div class="card-actions">
            <button class="button small-button" type="button" data-site-action="history" data-site-id="${site.id}">历史</button>
            <button class="button small-button" type="button" data-site-action="check" data-site-id="${site.id}" ${isChecking ? "disabled" : ""}>${isChecking ? "检测中" : "检测"}</button>
            <button class="button small-button danger" type="button" data-site-action="delete" data-site-id="${site.id}" ${isDeleting ? "disabled" : ""}>${isDeleting ? "删除中" : "删除"}</button>
        </div>
    ` : "";
    const idHtml = state.mode === "admin" ? `<div>站点 ID：${site.id}</div>` : "";

    return `
        <article class="site-card ${statusClass}">
            <div class="site-header">
                <div class="site-title">
                    <h3 class="site-name">${escapeHtml(site.name)}</h3>
                    <a class="site-url" href="${escapeAttr(site.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(site.url)}</a>
                </div>
                <span class="status-pill ${statusClass}">${statusText}</span>
            </div>

            <div class="metric-grid">
                <div class="metric">
                    <div class="metric-label">响应时间</div>
                    <div class="metric-value ${responseClass}">${formatResponse(site.response_time)}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">HTTP 状态</div>
                    <div class="metric-value">${site.status_code ?? "-"}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">SSL 剩余</div>
                    <div class="metric-value ${sslClass}">${formatSsl(site.ssl_days_left)}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">最近可用率</div>
                    <div class="metric-value ${uptimeClass}">${site.uptime === null ? "-" : `${site.uptime}%`}</div>
                </div>
            </div>

            ${sslWarning}
            ${errorHtml}
            ${renderOutages(site.outages || [])}

            <div class="site-footer">
                <div class="last-check">
                    <div>最后检查：${formatTime(site.checked_at)}</div>
                    ${idHtml}
                </div>
                ${actionsHtml}
            </div>
        </article>
    `;
}

function handleSiteAction(event) {
    if (!(event.target instanceof Element)) return;

    const button = event.target.closest("[data-site-action]");
    if (!button || !event.currentTarget.contains(button)) return;

    const siteId = Number(button.dataset.siteId);
    if (!Number.isInteger(siteId) || siteId <= 0) return;

    if (button.dataset.siteAction === "history") openHistory(siteId);
    if (button.dataset.siteAction === "check") recheckSite(siteId);
    if (button.dataset.siteAction === "delete") removeSite(siteId);
}

function renderOutages(outages) {
    if (!outages.length) return "";

    return `
        <div class="outage-list" aria-label="最近宕机记录">
            ${outages.slice(0, 2).map((outage) => `
                <div class="outage-item">
                    <span>${formatTime(outage.started_at)}</span>
                    <strong>${outage.duration_seconds === null ? "进行中" : formatDuration(outage.duration_seconds)}</strong>
                </div>
            `).join("")}
        </div>
    `;
}

async function addSite(event) {
    event.preventDefault();
    const nameInput = $("siteName");
    const urlInput = $("siteUrl");
    const name = nameInput.value.trim();
    const url = urlInput.value.trim();

    if (!name || !url) {
        toast("请填写网站名称和地址", "error");
        return;
    }

    setButtonLoading("addButton", true, "添加中");
    try {
        const response = await fetch(`${API_BASE}/api/sites`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, url })
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "添加失败");

        nameInput.value = "";
        urlInput.value = "";
        toast("站点已添加并完成首次检测");
        await loadSites({ silent: true });
    } catch (error) {
        toast(error.message || "添加失败", "error");
    } finally {
        setButtonLoading("addButton", false, "添加站点");
    }
}

async function recheckSite(id) {
    state.pendingChecks.add(id);
    render();
    try {
        const response = await fetch(`${API_BASE}/api/sites/${id}/check`, { method: "POST" });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "检测失败");
        toast("检测完成");
        await loadSites({ silent: true });
    } catch (error) {
        toast(error.message || "检测失败", "error");
    } finally {
        state.pendingChecks.delete(id);
        render();
    }
}

async function checkAllSites() {
    if (!state.sites.length) {
        toast("请先添加监控站点");
        return;
    }

    state.checkingAll = true;
    setButtonLoading("checkAllButton", true, "检测中");
    try {
        const response = await fetch(`${API_BASE}/api/check-all`, { method: "POST" });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "批量检测失败");
        toast(`检测完成：${payload.count || 0} 个站点`);
        await loadSites({ silent: true });
    } catch (error) {
        toast(error.message || "批量检测失败", "error");
    } finally {
        state.checkingAll = false;
        setButtonLoading("checkAllButton", false, "检测全部");
        updateAdminButtonState();
    }
}

async function removeSite(id) {
    const site = state.sites.find((item) => item.id === id);
    const name = site ? site.name : `ID ${id}`;
    if (!window.confirm(`确定删除「${name}」及其检测记录吗？`)) return;

    state.pendingDelete.add(id);
    render();
    try {
        const response = await fetch(`${API_BASE}/api/sites/${id}`, { method: "DELETE" });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "删除失败");
        toast("站点已删除");
        await loadSites({ silent: true });
    } catch (error) {
        toast(error.message || "删除失败", "error");
    } finally {
        state.pendingDelete.delete(id);
        render();
    }
}

async function openHistory(id) {
    const modal = $("historyModal");
    const body = $("historyBody");
    if (!modal || !body) return;

    state.lastFocusedElement = document.activeElement;
    const site = state.sites.find((item) => item.id === id);
    $("historyTitle").textContent = site ? `${site.name} 的检测历史` : "检测历史";
    body.innerHTML = `
        <div class="loading compact-state">
            <div>
                <div class="spinner"></div>
                <div>正在加载历史记录...</div>
            </div>
        </div>
    `;
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    $("closeHistoryButton")?.focus();

    try {
        const response = await fetch(`${API_BASE}/api/sites/${id}/checks`);
        const checks = await response.json();
        if (!response.ok) throw new Error(checks.detail || "历史记录加载失败");
        renderHistory(checks);
    } catch (error) {
        body.innerHTML = `<div class="message error">${escapeHtml(error.message || "历史记录加载失败")}</div>`;
    }
}

function renderHistory(checks) {
    const body = $("historyBody");
    if (!body) return;

    if (!checks.length) {
        body.innerHTML = `<div class="empty compact-state">暂无检测历史</div>`;
        return;
    }

    body.innerHTML = `
        <table class="history-table">
            <thead>
                <tr>
                    <th>时间</th>
                    <th>状态</th>
                    <th>响应</th>
                    <th>HTTP</th>
                    <th>SSL</th>
                    <th>错误信息</th>
                </tr>
            </thead>
            <tbody>
                ${checks.map((check) => `
                    <tr>
                        <td>${formatTime(check.checked_at)}</td>
                        <td>${getStatusText(check.status)}</td>
                        <td>${formatResponse(check.response_time)}</td>
                        <td>${check.status_code ?? "-"}</td>
                        <td>${formatSsl(check.ssl_days_left)}</td>
                        <td>${escapeHtml(check.error_msg || "-")}</td>
                    </tr>
                `).join("")}
            </tbody>
        </table>
    `;
}

function closeHistory() {
    const modal = $("historyModal");
    modal?.classList.remove("open");
    modal?.setAttribute("aria-hidden", "true");
    if (state.lastFocusedElement instanceof HTMLElement) {
        state.lastFocusedElement.focus();
    }
    state.lastFocusedElement = null;
}

function updateSummary() {
    if (!$("totalCount")) return;

    const total = state.sites.length;
    const up = state.sites.filter((site) => site.status === "up").length;
    const down = state.sites.filter((site) => site.status === "down").length;
    const sslRisk = state.sites.filter((site) => site.ssl_days_left !== null && site.ssl_days_left <= 14).length;
    const responseValues = state.sites.map((site) => site.response_time).filter((value) => typeof value === "number");
    const avg = responseValues.length
        ? Math.round(responseValues.reduce((sum, value) => sum + value, 0) / responseValues.length)
        : null;

    $("totalCount").textContent = total;
    $("upCount").textContent = up;
    $("downCount").textContent = down;
    $("sslRiskCount").textContent = sslRisk;
    $("avgResponse").textContent = avg === null ? "-" : `${avg}ms`;
    $("lastUpdated").textContent = total ? `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}` : "暂无站点";
}

function saveRefreshSetting() {
    const input = $("refreshInterval");
    if (!input) return;

    const rawValue = Number(input.value);
    if (!Number.isFinite(rawValue) || rawValue < 0) {
        toast("刷新间隔请输入 0 或正整数", "error");
        return;
    }

    let nextValue = Math.round(rawValue);
    if (nextValue > 0 && nextValue < 5) nextValue = 5;
    if (nextValue > 3600) nextValue = 3600;

    state.refreshSeconds = nextValue;
    state.refreshIn = nextValue;
    input.value = String(nextValue);
    writeRefreshSeconds(nextValue);
    updateRefreshState();
    toast(nextValue === 0 ? "已关闭自动刷新" : `自动刷新已设置为 ${nextValue} 秒`);
}

function tickRefresh() {
    if (state.refreshSeconds <= 0) {
        updateRefreshState();
        return;
    }

    if (!state.loading) {
        state.refreshIn -= 1;
        if (state.refreshIn <= 0) {
            state.refreshIn = state.refreshSeconds;
            loadSites({ silent: true });
        }
    }
    updateRefreshState();
}

function resetRefreshCountdown() {
    state.refreshIn = state.refreshSeconds;
}

function updateRefreshState() {
    const text = state.refreshSeconds <= 0
        ? "自动刷新：已关闭"
        : `自动刷新：${Math.max(state.refreshIn, 0)} 秒后`;

    $("refreshState") && ($("refreshState").textContent = text);
    $("refreshStatus") && ($("refreshStatus").textContent = text);
}

function updateAdminButtonState() {
    const button = $("checkAllButton");
    if (!button || state.checkingAll) return;
    button.disabled = state.sites.length === 0;
}

function setButtonLoading(id, isLoading, text) {
    const button = $(id);
    if (!button) return;
    button.disabled = isLoading;
    button.textContent = text;
}

function toast(message, type = "normal") {
    const container = $("toastContainer");
    if (!container) return;

    const item = document.createElement("div");
    item.className = `toast-item ${type === "error" ? "error" : ""}`;
    item.textContent = message;
    container.appendChild(item);
    window.setTimeout(() => item.remove(), 3400);
}

function readRefreshSeconds() {
    let savedRaw;
    try {
        savedRaw = localStorage.getItem(REFRESH_STORAGE_KEY);
    } catch {
        return DEFAULT_REFRESH_SECONDS;
    }
    if (savedRaw === null) return DEFAULT_REFRESH_SECONDS;

    const saved = Number(savedRaw);
    if (!Number.isFinite(saved) || saved < 0) return DEFAULT_REFRESH_SECONDS;
    return Math.round(saved);
}

function writeRefreshSeconds(value) {
    try {
        localStorage.setItem(REFRESH_STORAGE_KEY, String(value));
    } catch {
        // 浏览器禁用本地存储时，本次页面会话内的设置仍然有效。
    }
}

function getStatusClass(status) {
    if (status === "up") return "up";
    if (status === "down") return "down";
    return "unknown";
}

function getStatusText(status) {
    if (status === "up") return "在线";
    if (status === "down") return "异常";
    return "未知";
}

function getResponseClass(value) {
    if (typeof value !== "number") return "";
    if (value < 500) return "good";
    if (value < 1200) return "warn";
    return "bad";
}

function getSslClass(value) {
    if (value === null || value === undefined) return "";
    if (value > 30) return "good";
    if (value > 14) return "warn";
    return "bad";
}

function formatResponse(value) {
    return typeof value === "number" ? `${Math.round(value)}ms` : "-";
}

function formatSsl(value) {
    return value === null || value === undefined ? "-" : `${value} 天`;
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds} 秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时`;
    return `${Math.floor(seconds / 86400)} 天`;
}

function parseDate(value) {
    if (!value) return null;
    const normalized = String(value).replace(" ", "T");
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
}

function parseTime(value) {
    const date = parseDate(value);
    return date ? date.getTime() : 0;
}

function formatTime(value) {
    const date = parseDate(value);
    if (!date) return "从未检查";
    return date.toLocaleString("zh-CN", { hour12: false });
}

function nullableNumber(value) {
    return typeof value === "number" ? value : Number.POSITIVE_INFINITY;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text ?? "";
    return div.innerHTML;
}

function escapeAttr(text) {
    return escapeHtml(text).replace(/"/g, "&quot;");
}
