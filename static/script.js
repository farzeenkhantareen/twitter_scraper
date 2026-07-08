/**
 * script.js
 * =========
 * Frontend controller for the X Scraper dashboard.
 *
 * Responsibilities:
 *   - Form validation (username input)
 *   - Button state management (disable all during active requests)
 *   - Fetch API calls to all backend endpoints
 *   - Live progress polling while scraping is active
 *   - Activity log feed (append-only, timestamped entries)
 *   - Toast notification system (success, error, warning, info)
 *   - Dashboard metric updates
 *   - Reset confirmation modal
 *   - Auto-refresh idle status every 10 seconds
 *
 * No external libraries are used — vanilla JS throughout.
 */

"use strict";

// ============================================================================
// DOM References
// ============================================================================

const usernameInput   = document.getElementById("username-input");
const inputError      = document.getElementById("input-error");

const btnStart        = document.getElementById("btn-start");
const btnNext         = document.getElementById("btn-next");
const btnDownload     = document.getElementById("btn-download");
const btnReset        = document.getElementById("btn-reset");
const btnClearLog     = document.getElementById("btn-clear-log");

const statusBadge     = document.getElementById("status-badge");
const statusBadgeText = document.getElementById("status-badge-text");

const lblUsername     = document.getElementById("lbl-username");
const lblBatch        = document.getElementById("lbl-batch");
const lblTotal        = document.getElementById("lbl-total");
const lblLastFile     = document.getElementById("lbl-last-file");

const loaderBar       = document.getElementById("loader-bar");
const loaderStatus    = document.getElementById("loader-status");
const progressText    = document.getElementById("progress-text");

const activityLog     = document.getElementById("activity-log");
const toastContainer  = document.getElementById("toast-container");

const authWarning     = document.getElementById("auth-warning");

const resetModal      = document.getElementById("reset-modal");
const modalCancel     = document.getElementById("modal-cancel");
const modalConfirm    = document.getElementById("modal-confirm");

// AI Mode DOM Elements
const btnAiMode          = document.getElementById("btn-ai-mode");
const btnBackDashboard   = document.getElementById("btn-back-dashboard");
const btnClearChat       = document.getElementById("btn-clear-chat");
const btnSaveChat        = document.getElementById("btn-save-chat");
const panelDashboard     = document.getElementById("panel-dashboard");
const panelAi            = document.getElementById("panel-ai");
const aiChatInput        = document.getElementById("ai-chat-input");
const btnAiSend          = document.getElementById("btn-ai-send");
const aiChatMessages     = document.getElementById("ai-chat-messages");
const aiContextText      = document.getElementById("ai-context-text");

// Latest / Oldest Post Preview DOM Elements
const btnLatest       = document.getElementById("btn-latest");
const btnDownloadLatest = document.getElementById("btn-download-latest");
const previewSection  = document.getElementById("preview-section");
const previewTypeBadge = document.getElementById("preview-type-badge");
const tweetAvatar     = document.getElementById("tweet-avatar");
const tweetDisplayName = document.getElementById("tweet-display-name");
const tweetHandle     = document.getElementById("tweet-handle");
const tweetText       = document.getElementById("tweet-text");
const tweetDate       = document.getElementById("tweet-date");
const tweetReplies    = document.getElementById("tweet-replies");
const tweetReposts    = document.getElementById("tweet-reposts");
const tweetLikes      = document.getElementById("tweet-likes");
const tweetViews      = document.getElementById("tweet-views");

// ============================================================================
// Application State
// ============================================================================

/** Whether a scraping request is currently in flight. */
let isScraping = false;

/** Polling interval ID during active scrape (for progress updates). */
let pollingInterval = null;

/** Auto-refresh interval ID during idle (light-weight status sync). */
let idleRefreshInterval = null;

// ============================================================================
// Initialisation
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
    // Firefox form state persistence workaround: explicitly enable buttons on load
    [btnStart, btnLatest, btnReset].forEach(b => { if (b) b.disabled = false; });
    if (usernameInput) usernameInput.disabled = false;

    // Restore dashboard from persisted backend state.
    fetchStatus({ silent: true });

    // Start idle auto-refresh (every 10 s).
    startIdleRefresh();

    // Bind action buttons.
    btnStart.addEventListener("click",    handleStart);
    btnNext.addEventListener("click",     handleNext);
    btnLatest.addEventListener("click",   handleFetchLatest);
    btnDownloadLatest.addEventListener("click", handleDownloadLatest);
    btnDownload.addEventListener("click", handleDownload);
    btnReset.addEventListener("click",    showResetModal);
    btnClearLog.addEventListener("click", clearLog);

    if (btnAiMode) btnAiMode.addEventListener("click", enterAiMode);
    if (btnBackDashboard) btnBackDashboard.addEventListener("click", enterDashboardMode);
    if (btnClearChat) btnClearChat.addEventListener("click", handleClearChat);
    if (btnSaveChat) btnSaveChat.addEventListener("click", handleSaveChat);
    if (btnAiSend) btnAiSend.addEventListener("click", handleAiSend);
    if (aiChatInput) {
        aiChatInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleAiSend();
            }
        });
    }

    // Bind modal buttons.
    modalCancel.addEventListener("click",  hideResetModal);
    modalConfirm.addEventListener("click", handleReset);

    // Close modal on overlay click.
    resetModal.addEventListener("click", (e) => {
        if (e.target === resetModal) hideResetModal();
    });

    // Close modal on Escape key.
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !resetModal.hidden) hideResetModal();
    });

    // Strip leading @ from username input on blur.
    usernameInput.addEventListener("blur", () => {
        usernameInput.value = usernameInput.value.trim().replace(/^@+/, "");
    });

    // Clear validation error on input.
    usernameInput.addEventListener("input", () => {
        setInputError("");
    });
});

// ============================================================================
// Handlers
// ============================================================================

/**
 * Handle "Retrieve First 10 Posts" button.
 * Validates input, then calls POST /scrape/start.
 */
async function handleStart() {
    const username = sanitiseUsername();
    if (!username) return;

    setScrapingState(true, "Initialising session…", btnStart);
    hideAuthWarning();
    appendLog("info", `Starting retrieval for @${username} (Batch 1)…`);

    try {
        const res = await apiFetch("/scrape/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username }),
        });

        if (!res.ok) {
            const err = await extractError(res);
            throw new Error(err);
        }

        const data = await res.json();
        appendLog("success", `Batch 1 complete — ${data.count} posts saved to ${data.filename}`);
        showToast("success", `✓ Batch 1 saved: ${data.filename}`);
        await fetchStatus({ silent: true });

    } catch (err) {
        handleFetchError(err, "start scrape");
    } finally {
        setScrapingState(false);
    }
}

/**
 * Handle "Retrieve Next 10 Posts" button.
 * Calls POST /scrape/next using the active session state.
 */
async function handleNext() {
    setScrapingState(true, "Locating boundary post…", btnNext);
    appendLog("info", "Retrieving next batch…");

    try {
        const res = await apiFetch("/scrape/next", { method: "POST" });

        if (!res.ok) {
            const err = await extractError(res);
            throw new Error(err);
        }

        const data = await res.json();

        if (data.count === 0) {
            appendLog("warning", "Timeline exhausted — no more posts found.");
            showToast("warning", "⚠ Timeline exhausted. No additional posts available.");
        } else {
            appendLog("success", `Batch ${data.batch} complete — ${data.count} posts saved to ${data.filename}`);
            showToast("success", `✓ Batch ${data.batch} saved: ${data.filename}`);
        }

        await fetchStatus({ silent: true });

    } catch (err) {
        handleFetchError(err, "next batch");
    } finally {
        setScrapingState(false);
    }
}

/**
 * Handle "Download JSON" button.
 * Navigates to /download/latest which triggers a file download.
 */
function handleDownload() {
    appendLog("info", "Downloading latest batch file…");
    triggerDownload("/download/latest");
    showToast("success", "✓ Latest batch saved to downloaded_json/ folder!");
    appendLog("success", "Latest batch file saved to downloaded_json/ on server.");
}

/**
 * Trigger a file download dynamically using a hidden anchor element.
 * Prevents navigation aborts and works reliably across Firefox and Chrome.
 *
 * @param {string} url
 */
function triggerDownload(url) {
    const a = document.createElement("a");
    a.href = url;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

/**
 * Show the reset confirmation modal.
 */
function showResetModal() {
    resetModal.hidden = false;
    modalConfirm.focus();
}

/**
 * Hide the reset confirmation modal.
 */
function hideResetModal() {
    resetModal.hidden = true;
}

/**
 * Handle confirmed reset — calls POST /reset.
 */
async function handleReset() {
    hideResetModal();
    appendLog("info", "Resetting session progress…");

    try {
        const res = await apiFetch("/reset", { method: "POST" });

        if (!res.ok) {
            const err = await extractError(res);
            throw new Error(err);
        }

        usernameInput.value = "";
        hideAuthWarning();
        appendLog("info", "Session reset. Ready for a new retrieval.");
        showToast("info", "ℹ Session reset successfully.");
        await fetchStatus({ silent: true });

    } catch (err) {
        appendLog("error", `Reset failed: ${err.message}`);
        showToast("error", `✗ Reset failed: ${err.message}`);
    }
}

// ============================================================================
// Status Fetching
// ============================================================================

/**
 * Fetch /status and update the dashboard.
 *
 * @param {Object} opts
 * @param {boolean} [opts.silent=false] — When true, fetch errors are not toasted.
 */
async function fetchStatus({ silent = false } = {}) {
    try {
        const res = await fetch("/status");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        updateDashboard(data);
        return data;
    } catch (err) {
        if (!silent) {
            showToast("error", "Could not connect to server.");
        }
        return null;
    }
}

/**
 * Poll /status every second during an active scrape for live progress messages.
 */
function startProgressPolling() {
    if (pollingInterval) return;
    pollingInterval = setInterval(async () => {
        const data = await fetchStatus({ silent: true });
        if (data && data.progress_message) {
            progressText.textContent = data.progress_message;
        }
    }, 1000);
}

/**
 * Stop progress polling.
 */
function stopProgressPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

/**
 * Start a light-weight status refresh every 10 s when idle.
 * Allows the dashboard to pick up any state changes (e.g. from a direct API call).
 */
function startIdleRefresh() {
    if (idleRefreshInterval) return;
    idleRefreshInterval = setInterval(() => {
        if (!isScraping) fetchStatus({ silent: true });
    }, 10_000);
}

// ============================================================================
// Dashboard Update
// ============================================================================

/**
 * Apply a /status response payload to all dashboard UI elements.
 *
 * @param {Object} data — StatusResponse JSON from the backend.
 */
function updateDashboard(data) {
    // Metrics
    lblUsername.textContent  = data.username  ? `@${data.username}` : "—";
    lblBatch.textContent     = data.batch     || "0";
    lblTotal.textContent     = data.total_scraped || "0";
    lblLastFile.textContent  = data.last_file || "—";

    // Status badge
    const status = (data.status || "Idle");
    const lower  = status.toLowerCase();

    statusBadgeText.textContent = status;
    statusBadge.className = "status-badge";

    if (lower.includes("idle")) {
        statusBadge.classList.add("badge-idle");
    } else if (lower.includes("scrap") || lower.includes("process")) {
        statusBadge.classList.add("badge-scraping");
    } else if (lower.includes("success") || lower.includes("complet")) {
        statusBadge.classList.add("badge-success");
    } else if (lower.includes("error") || lower.includes("failed") || lower.includes("crash")) {
        statusBadge.classList.add("badge-error");
    } else if (lower.includes("auth") || lower.includes("rate") || lower.includes("warn")) {
        statusBadge.classList.add("badge-warning");
    } else {
        statusBadge.classList.add("badge-idle");
    }

    // Authentication warning
    if (lower.includes("auth")) {
        showAuthWarning();
    }

    // Button states (only when no active request)
    if (!isScraping) {
        const hasSession = !!(data.username && data.total_scraped > 0);
        btnNext.disabled     = !hasSession;
        btnDownload.disabled = !data.last_file;
    }
}

// ============================================================================
// UI State Management
// ============================================================================

/**
 * Toggle the loading state of the entire UI.
 *
 * @param {boolean}  active  — True to enter loading state.
 * @param {string}   [msg]   — Initial progress text.
 */
function setScrapingState(active, msg = "Processing…", triggerButton = null) {
    isScraping = active;

    // Toggle loading classes on buttons
    if (!active) {
        [btnStart, btnNext, btnLatest, btnDownloadLatest].forEach(b => {
            if (b) b.classList.remove("loading");
        });
    } else if (triggerButton) {
        triggerButton.classList.add("loading");
    }

    // Disable / enable all action buttons.
    [btnStart, btnNext, btnReset, btnDownload, btnLatest, btnDownloadLatest].forEach(b => { if (b) b.disabled = active; });
    usernameInput.disabled = active;

    // Loader bar animation.
    loaderBar.classList.toggle("active", active);

    // Progress status row.
    loaderStatus.hidden = !active;
    if (active) {
        progressText.textContent = msg;
        startProgressPolling();
    } else {
        stopProgressPolling();
    }
}

// ============================================================================
// Input Validation
// ============================================================================

/**
 * Read, trim, and validate the username input.
 *
 * @returns {string} The cleaned username, or "" on validation failure.
 */
function sanitiseUsername() {
    const raw = usernameInput.value.trim().replace(/^@+/, "");
    if (!raw) {
        setInputError("Please enter a username.");
        usernameInput.focus();
        return "";
    }
    if (!/^[A-Za-z0-9_]{1,50}$/.test(raw)) {
        setInputError("Username can only contain letters, numbers, and underscores.");
        usernameInput.focus();
        return "";
    }
    usernameInput.value = raw;
    setInputError("");
    return raw;
}

/**
 * Display or clear the inline input validation error message.
 *
 * @param {string} msg — Error text to display. Empty string to clear.
 */
function setInputError(msg) {
    inputError.textContent = msg;
}

// ============================================================================
// Activity Log
// ============================================================================

const LOG_ICONS = {
    success: "✓",
    error:   "✗",
    info:    "→",
    warning: "⚠",
};

/**
 * Append a timestamped entry to the activity log feed.
 *
 * @param {"success"|"error"|"info"|"warning"} type
 * @param {string} msg — Human-readable description of the event.
 */
function appendLog(type, msg) {
    // Remove the empty placeholder on first entry.
    const empty = activityLog.querySelector(".log-empty");
    if (empty) empty.remove();

    const now = new Date();
    const time = now.toLocaleTimeString("en-GB", { hour12: false });

    const entry = document.createElement("div");
    entry.className = `log-entry log-${type}`;
    entry.innerHTML = `
        <span class="log-time">${time}</span>
        <span class="log-icon" aria-hidden="true">${LOG_ICONS[type] ?? "•"}</span>
        <span class="log-msg">${escapeHtml(msg)}</span>
    `;

    activityLog.appendChild(entry);
    // Scroll to the newest entry.
    activityLog.scrollTop = activityLog.scrollHeight;
}

/**
 * Clear all log entries and show the empty placeholder.
 */
function clearLog() {
    activityLog.innerHTML = '<div class="log-empty">No activity yet — start a retrieval session.</div>';
}

// ============================================================================
// Toast Notifications
// ============================================================================

/**
 * Show a self-dismissing toast notification.
 *
 * @param {"success"|"error"|"warning"|"info"} type
 * @param {string} message — Toast body text.
 * @param {number} [duration=4500] — Auto-dismiss delay in ms.
 */
function showToast(type, message, duration = 4500) {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.setAttribute("role", "status");
    toast.innerHTML = `
        <span class="toast-icon" aria-hidden="true">${LOG_ICONS[type] ?? "•"}</span>
        <span class="toast-msg">${escapeHtml(message)}</span>
    `;

    // Click to dismiss.
    toast.addEventListener("click", () => dismissToast(toast));

    toastContainer.appendChild(toast);

    // Auto-dismiss after duration.
    setTimeout(() => dismissToast(toast), duration);
}

/**
 * Animate and remove a toast element.
 *
 * @param {HTMLElement} toast
 */
function dismissToast(toast) {
    if (toast.classList.contains("hiding")) return;
    toast.classList.add("hiding");
    toast.addEventListener("transitionend", () => toast.remove(), { once: true });
}

// ============================================================================
// Auth Warning
// ============================================================================

function showAuthWarning() {
    authWarning.hidden = false;
}

function hideAuthWarning() {
    authWarning.hidden = true;
}

// ============================================================================
// Error Handling
// ============================================================================

/**
 * Extract the human-readable error detail from an HTTP error response.
 *
 * @param {Response} res
 * @returns {Promise<string>}
 */
async function extractError(res) {
    try {
        const body = await res.json();
        return body.detail || body.message || `Server error (HTTP ${res.status})`;
    } catch {
        return `Server error (HTTP ${res.status})`;
    }
}

/**
 * Handle a fetch/API error centrally: log it, toast it, and check for auth issues.
 *
 * @param {Error}  err
 * @param {string} context — Human-readable context (e.g. "start scrape").
 */
function handleFetchError(err, context) {
    const msg = err.message || "Unknown error";
    appendLog("error", `${context} failed: ${msg}`);
    showToast("error", `✗ ${msg}`);

    if (msg.toLowerCase().includes("auth") || msg.toLowerCase().includes("sessions/auth")) {
        showAuthWarning();
        appendLog("warning", "Authentication required. Regenerate sessions/auth.json.");
    }

    // Refresh status to reflect backend error state.
    fetchStatus({ silent: true });
}

// ============================================================================
// Fetch Wrapper
// ============================================================================

/**
 * Thin wrapper around window.fetch that adds a default timeout.
 *
 * @param {string}       url
 * @param {RequestInit}  [init]
 * @param {number}       [timeoutMs=120000] — 2-minute timeout for long scrapes.
 * @returns {Promise<Response>}
 */
async function apiFetch(url, init = {}, timeoutMs = 120_000) {
    const controller = new AbortController();
    const timeoutId  = setTimeout(() => controller.abort(), timeoutMs);

    try {
        return await fetch(url, { ...init, signal: controller.signal });
    } catch (err) {
        if (err.name === "AbortError") {
            throw new Error("Request timed out. The server took too long to respond.");
        }
        throw err;
    } finally {
        clearTimeout(timeoutId);
    }
}

// ============================================================================
// Utilities
// ============================================================================

/**
 * Escape a string for safe insertion into innerHTML.
 *
 * @param {string} str
 * @returns {string}
 */
function escapeHtml(str) {
    return String(str)
        .replace(/&/g,  "&amp;")
        .replace(/</g,  "&lt;")
        .replace(/>/g,  "&gt;")
        .replace(/"/g,  "&quot;")
        .replace(/'/g,  "&#039;");
}

// ============================================================================
// Single Post Retrieval & Rendering Handlers
// ============================================================================

/**
 * Handle "Retrieve Latest Post" button.
 */
async function handleFetchLatest() {
    const username = sanitiseUsername();
    if (!username) return;

    setScrapingState(true, "Fetching latest post…", btnLatest);
    hideAuthWarning();
    appendLog("info", `Fetching latest post for @${username}…`);
    hidePreview();

    try {
        const res = await apiFetch("/scrape/latest", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username }),
        });

        if (!res.ok) {
            const err = await extractError(res);
            throw new Error(err);
        }

        const data = await res.json();
        appendLog("success", `Latest post retrieved — saved to ${data.filename}`);
        showToast("success", `✓ Saved latest post: ${data.filename}`);
        renderPreview("LATEST POST", data.post);
        await fetchStatus({ silent: true });

    } catch (err) {
        handleFetchError(err, "fetch latest post");
    } finally {
        setScrapingState(false);
    }
}

/**
 * Handle "Download Latest Post" button.
 * Navigates to /download/latest-post which triggers a file download.
 */
function handleDownloadLatest() {
    appendLog("info", "Downloading latest post file…");
    triggerDownload("/download/latest-post");
    showToast("success", "✓ Latest post saved to downloaded_json/ folder!");
    appendLog("success", "Latest post file saved to downloaded_json/ on server.");
}

/**
 * Render a single Post object inside the Tweet Preview Card.
 */
function renderPreview(type, post) {
    if (!post) return;
    previewTypeBadge.textContent = type;
    
    // Avatar placeholder: first letter of display name
    tweetAvatar.textContent = (post.display_name || post.username || "X")[0];
    
    tweetDisplayName.textContent = post.display_name || post.username;
    tweetHandle.textContent = `@${post.username}`;
    tweetText.textContent = post.text || "";
    
    // Format timestamp: e.g. "12:00 PM · Jun 30, 2026"
    if (post.created_at) {
        try {
            const dateObj = new Date(post.created_at);
            const timeStr = dateObj.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
            const dateStr = dateObj.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
            tweetDate.textContent = `${timeStr} · ${dateStr}`;
        } catch {
            tweetDate.textContent = post.created_at;
        }
    } else {
        tweetDate.textContent = "Unknown date";
    }
    
    tweetReplies.textContent = formatStatNumber(post.reply_count);
    tweetReposts.textContent = formatStatNumber(post.repost_count);
    tweetLikes.textContent = formatStatNumber(post.like_count);
    tweetViews.textContent = formatStatNumber(post.view_count);
    
    previewSection.hidden = false;
    if (btnDownloadLatest) btnDownloadLatest.disabled = false;
    // Scroll smoothly to see the preview
    previewSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function hidePreview() {
    previewSection.hidden = true;
    if (btnDownloadLatest) btnDownloadLatest.disabled = true;
}

function formatStatNumber(num) {
    if (!num || isNaN(num)) return "0";
    if (num >= 1_000_000) return (num / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
    if (num >= 1_000) return (num / 1_000).toFixed(1).replace(/\.0$/, "") + "K";
    return num.toString();
}

// ============================================================================
// AI Analyst Mode Controllers
// ============================================================================

/** Chat history array for active session */
let aiChatHistory = [];

/**
 * Toggle view to AI Analyst Mode.
 */
function enterAiMode() {
    if (panelDashboard) panelDashboard.hidden = true;
    if (panelAi) panelAi.hidden = false;
    if (btnAiMode) btnAiMode.classList.add("active");
    
    // Clear preview card if open, to avoid visual clutter
    hidePreview();
    
    // Scan downloaded files context status
    scanAiContext();
    
    // Scroll chat to bottom
    if (aiChatMessages) aiChatMessages.scrollTop = aiChatMessages.scrollHeight;
    
    // Focus input
    if (aiChatInput) aiChatInput.focus();
    
    appendLog("info", "Switched to AI Analyst Mode.");
}

/**
 * Toggle view back to Scraper Dashboard.
 */
function enterDashboardMode() {
    if (panelAi) panelAi.hidden = true;
    if (panelDashboard) panelDashboard.hidden = false;
    if (btnAiMode) btnAiMode.classList.remove("active");
    
    appendLog("info", "Switched back to Scraper Dashboard.");
}

/**
 * Scan the downloaded_json directory and show how many posts/files are loaded.
 */
async function scanAiContext() {
    if (!aiContextText) return;
    aiContextText.textContent = "Scanning downloaded_json/ folder…";
    
    try {
        const res = await fetch("/ai/status");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        if (data.tweet_count === 0) {
            aiContextText.innerHTML = `⚠️ No scraped posts found in <code>downloaded_json/</code>. Scrape and download posts first!`;
        } else {
            aiContextText.innerHTML = `✓ AI Context Active: <strong>${data.file_count}</strong> JSON files loaded (<strong>${data.tweet_count}</strong> unique posts).`;
        }
    } catch (err) {
        aiContextText.innerHTML = `⚠️ Failed to load context status: ${err.message}`;
    }
}

/**
 * Handle sending user question to AI.
 */
async function handleAiSend() {
    if (!aiChatInput || !btnAiSend) return;
    
    const message = aiChatInput.value.trim();
    if (!message) return;
    
    // Clear input
    aiChatInput.value = "";
    
    // Disable inputs
    aiChatInput.disabled = true;
    btnAiSend.disabled = true;
    
    // Add user message
    addAiMessage("user", message);
    aiChatHistory.push({ role: "user", content: message });
    
    // Add loading bubble
    const loadingBubble = addAiMessage("loading", "");
    loadingBubble.innerHTML = `AI is thinking <div class="dots"><span></span><span></span><span></span></div>`;
    
    try {
        const res = await apiFetch("/ai/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message }),
        });
        
        // Remove loading bubble
        loadingBubble.remove();
        
        if (!res.ok) {
            const err = await extractError(res);
            throw new Error(err);
        }
        
        const data = await res.json();
        addAiMessage("assistant", data.response);
        aiChatHistory.push({ role: "assistant", content: data.response });
        
    } catch (err) {
        loadingBubble.remove();
        addAiMessage("error", `✗ Request failed: ${err.message}`);
    } finally {
        aiChatInput.disabled = false;
        btnAiSend.disabled = false;
        aiChatInput.focus();
    }
}

/**
 * Append a chat bubble message.
 */
function addAiMessage(role, content) {
    if (!aiChatMessages) return null;
    
    const msg = document.createElement("div");
    msg.className = `ai-message ${role}-msg`;
    
    if (role === "assistant") {
        msg.innerHTML = formatMarkdown(content);
    } else if (role === "user") {
        msg.textContent = content;
    }
    
    aiChatMessages.appendChild(msg);
    aiChatMessages.scrollTop = aiChatMessages.scrollHeight;
    return msg;
}

/**
 * A lightweight markdown formatter to render LLM responses.
 */
function formatMarkdown(text) {
    if (!text) return "";
    
    // Escape HTML first to prevent XSS
    let html = escapeHtml(text);
    
    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");
    
    // Code blocks (multiline)
    html = html.replace(/```([\s\S]*?)```/g, '<pre class="ai-code-block"><code>$1</code></pre>');
    
    // Inline code
    html = html.replace(/`(.*?)`/g, '<code class="inline-code">$1</code>');
    
    // List items (lines starting with - or *)
    html = html.replace(/^\s*[-*]\s+(.*?)$/gm, "<li>$1</li>");
    
    // Wrap consecutive list items in <ul>
    html = html.replace(/(<li>.*?<\/li>)/gs, "<ul>$1</ul>");
    html = html.replace(/<\/ul>\s*<ul>/g, ""); // Clean up consecutive wrappers
    
    // Newlines to break tags
    html = html.replace(/\n/g, "<br>");
    
    return html;
}

/**
 * Clear chat history from display and in-memory tracking.
 */
function handleClearChat() {
    if (!aiChatMessages) return;
    
    aiChatMessages.innerHTML = `
        <div class="ai-message system-msg">
            Hello! I am your AI Analyst. I can answer questions about the scraped tweets saved in your <code>downloaded_json</code> directory. Ask me anything!
        </div>
    `;
    
    aiChatHistory = [];
    showToast("info", "ℹ Chat history cleared.");
    appendLog("info", "AI Chat history cleared.");
}

/**
 * Save chat history to the server as a JSON file.
 */
async function handleSaveChat() {
    if (aiChatHistory.length === 0) {
        showToast("warning", "⚠ Chat history is empty. Send a prompt first!");
        return;
    }
    
    if (btnSaveChat) btnSaveChat.disabled = true;
    appendLog("info", "Saving chat history to server…");
    
    try {
        const res = await apiFetch("/ai/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ history: aiChatHistory }),
        });
        
        if (!res.ok) {
            const err = await extractError(res);
            throw new Error(err);
        }
        
        const data = await res.json();
        showToast("success", `✓ Chat saved: ai_saved_chat/${data.filename}`);
        appendLog("success", `Chat history saved to server as ai_saved_chat/${data.filename}`);
    } catch (err) {
        showToast("error", `✗ Save failed: ${err.message}`);
        appendLog("error", `Save failed: ${err.message}`);
    } finally {
        if (btnSaveChat) btnSaveChat.disabled = false;
    }
}
