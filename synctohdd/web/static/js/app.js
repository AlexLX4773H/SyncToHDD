/**
 * SyncToHDD — Client JavaScript
 * Handles SSE subscriptions, live progress updates, and API interactions.
 */

// Global Toast System
function showToast(message, type = "info") {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span>${message}</span>
    <button style="background:none; border:none; color:#94a3b8; cursor:pointer;" onclick="this.parentElement.remove()">&times;</button>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transition = "opacity 0.4s ease";
    setTimeout(() => toast.remove(), 400);
  }, 4500);
}

// SSE Live Sync Updates
let evtSource = null;

function initSSE() {
  if (evtSource) return;

  evtSource = new EventSource("/api/events");

  evtSource.addEventListener("status", (e) => {
    try {
      const data = JSON.parse(e.data);
      updateGlobalStatus(data);
      updateQueueUI(data.queue || []);
    } catch (err) {
      console.error("Failed to parse status event", err);
    }
  });

  evtSource.addEventListener("progress", (e) => {
    try {
      const data = JSON.parse(e.data);
      updateGlobalStatus({
        is_running: data.status === "syncing" || data.status === "scanning",
        latest_event: data,
        queue_length: data.queue_length !== undefined ? data.queue_length : window.__syncQueueLength,
      });
      handleLiveProgress(data);
    } catch (err) {
      console.error("Failed to parse progress event", err);
    }
  });

  evtSource.onerror = (err) => {
    console.warn("SSE connection interrupted, retrying...", err);
  };
}

function updateGlobalStatus(data) {
  const dot = document.getElementById("global-status-dot");
  const text = document.getElementById("global-status-text");
  const mobileDot = document.getElementById("mobile-status-dot");
  const cancelBtn = document.getElementById("btn-cancel-sync");

  if (data.queue_length !== undefined) {
    window.__syncQueueLength = Number(data.queue_length);
  } else if (data.queue && Array.isArray(data.queue)) {
    window.__syncQueueLength = data.queue.length;
  }

  const qLen = window.__syncQueueLength || 0;
  const isRunning = Boolean(data.is_running || qLen > 0);
  window.__isSyncRunning = isRunning;

  if (cancelBtn) {
    cancelBtn.style.display = (isRunning || qLen > 0) ? "inline-flex" : "none";
  }

  if (dot) {
    if (isRunning) {
      dot.className = "pulse-dot syncing";
    } else {
      dot.className = "pulse-dot";
    }
  }

  if (text) {
    if (isRunning) {
      const pairName = data.latest_event ? data.latest_event.pair_name : (data.active_pair_name || "Active");
      if (qLen > 0) {
        text.textContent = `Syncing: ${pairName} (${qLen} queued)`;
      } else {
        text.textContent = `Syncing: ${pairName}`;
      }
    } else if (qLen > 0) {
      text.textContent = `Queued: ${qLen} job${qLen !== 1 ? 's' : ''}`;
    } else {
      text.textContent = "Engine Idle";
    }
  }

  if (mobileDot) {
    if (isRunning) {
      mobileDot.classList.add("syncing");
    } else {
      mobileDot.classList.remove("syncing");
    }
  }
}

function handleLiveProgress(event) {
  // Update progress bar
  const progressBar = document.getElementById("active-progress-bar");
  const progressText = document.getElementById("active-progress-percent");
  if (progressBar) {
    progressBar.style.width = `${event.percent}%`;
  }
  if (progressText) {
    progressText.textContent = `${event.percent.toFixed(1)}%`;
  }

  // Update counters
  const setEl = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };

  setEl("live-added-count", event.files_added || 0);
  setEl("live-modified-count", event.files_modified || 0);
  setEl("live-deleted-count", event.files_deleted || 0);
  setEl("live-unchanged-count", event.files_unchanged || 0);

  const curFileEl = document.getElementById("live-current-file");
  if (curFileEl) {
    curFileEl.textContent = event.current_file ? event.current_file : (event.message || "Idle");
  }

  // Append to terminal log
  const terminal = document.getElementById("live-terminal");
  if (terminal && event.message) {
    const time = new Date().toLocaleTimeString();
    const line = document.createElement("div");
    line.className = "log-entry";
    line.innerHTML = `<span class="log-time">[${time}]</span> ${escapeHtml(event.message)}`;
    terminal.appendChild(line);
    terminal.scrollTop = terminal.scrollHeight;
  }

  // Update status badge on active run page
  const statusBadge = document.getElementById("active-run-status-badge");
  if (statusBadge) {
    statusBadge.textContent = event.status;
    statusBadge.className = `badge badge-${event.status}`;
  }

  // Update active run title if pair changes during batch sync
  const titleEl = document.getElementById("active-run-title");
  if (titleEl && event.pair_name) {
    titleEl.textContent = event.pair_name;
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.innerText = str;
  return div.innerHTML;
}

// Queue UI & Modal Manager
let pendingQueueTarget = null;

function openQueueModal(target) {
  pendingQueueTarget = target;
  const modal = document.getElementById("queue-confirm-modal");
  const modalBody = document.getElementById("queue-modal-body");
  const confirmBtn = document.getElementById("queue-modal-confirm-btn");

  if (!modal || !modalBody || !confirmBtn) {
    // Native fallback if modal element is not in DOM
    const label = target.isAll ? "ALL configured pairs" : `"${target.pairName || target.pairId}"`;
    const mode = target.dryRun ? "Dry Run" : "Live Sync";
    if (confirm(`A sync is already in progress.\n\nWould you like to queue ${label} (${mode}) to run automatically when current sync finishes?`)) {
      if (target.isAll) {
        executeSyncAll(target.dryRun, true);
      } else {
        executeSync(target.pairId, target.dryRun, true, target.pairName);
      }
    }
    return;
  }

  if (target.isAll) {
    modalBody.innerHTML = `
      A sync job is currently in progress.<br><br>
      Would you like to <strong>queue ALL configured sync pairs</strong> (${target.dryRun ? '<span class="badge badge-mode">Dry Run</span>' : '<span class="badge badge-syncing">Live Sync</span>'}) to run sequentially after the current sync finishes?
    `;
    confirmBtn.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="9 11 12 14 22 4"></polyline>
        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
      </svg>
      Queue All Pairs
    `;
  } else {
    modalBody.innerHTML = `
      A sync job is currently in progress.<br><br>
      Would you like to add <strong>${escapeHtml(target.pairName || target.pairId)}</strong> (${target.dryRun ? '<span class="badge badge-mode">Dry Run</span>' : '<span class="badge badge-syncing">Live Sync</span>'}) to the execution queue? It will run automatically without running in parallel.
    `;
    confirmBtn.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="9 11 12 14 22 4"></polyline>
        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
      </svg>
      Add to Queue
    `;
  }

  modal.classList.add("active");
}

function closeQueueModal() {
  const modal = document.getElementById("queue-confirm-modal");
  if (modal) modal.classList.remove("active");
  pendingQueueTarget = null;
}

function confirmQueueAction() {
  if (!pendingQueueTarget) return;
  const target = pendingQueueTarget;
  closeQueueModal();

  if (target.isAll) {
    fetch(`/api/sync/all/queue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run: target.dryRun, queue: true }),
    })
      .then((res) => res.json())
      .then((data) => {
        showToast(data.message || "All pairs queued to run sequentially", "success");
        fetchSyncStatus();
      })
      .catch(() => {
        showToast("Error queueing sync jobs", "danger");
      });
  } else {
    fetch(`/api/sync/${target.pairId}/queue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run: target.dryRun, queue: true }),
    })
      .then((res) => res.json())
      .then((data) => {
        showToast(data.message || `Job for ${target.pairName || target.pairId} queued at position #${data.queue_position}`, "success");
        fetchSyncStatus();
      })
      .catch(() => {
        showToast("Error queueing sync job", "danger");
      });
  }
}

function updateQueueUI(queue) {
  const qList = Array.isArray(queue) ? queue : [];
  window.__syncQueueLength = qList.length;

  const countBadge = document.getElementById("queue-count-badge");
  if (countBadge) {
    countBadge.textContent = `${qList.length} waiting`;
  }

  const clearBtn = document.getElementById("btn-clear-queue");
  if (clearBtn) {
    clearBtn.style.display = qList.length > 0 ? "inline-flex" : "none";
  }

  const container = document.getElementById("queue-items-container");
  if (container) {
    if (qList.length === 0) {
      container.innerHTML = `
        <div class="queue-empty-message">
          No jobs currently waiting in the queue. Jobs queued while a sync is running will appear here.
        </div>
      `;
    } else {
      container.innerHTML = qList.map((job) => `
        <div class="queue-item" id="queue-item-${escapeHtml(job.job_id)}">
          <div class="queue-item-content">
            <span class="queue-pos-badge">#${job.position}</span>
            <strong class="queue-item-title">${escapeHtml(job.pair_name)}</strong>
            <span class="badge ${job.dry_run ? 'badge-mode' : 'badge-syncing'}">
              ${job.dry_run ? 'Dry Run' : 'Live Sync'}
            </span>
            <span class="queue-item-sep">&bull;</span>
            <div class="queue-item-paths" title="${escapeHtml(job.source)} &rarr; ${escapeHtml(job.destination)}">
              <span class="queue-path-text">${escapeHtml(job.source)}</span>
              <span class="queue-path-arrow">&rarr;</span>
              <span class="queue-path-text">${escapeHtml(job.destination)}</span>
            </div>
          </div>
          <div class="queue-item-actions">
            <button class="queue-remove-btn" onclick="removeQueuedJob('${escapeHtml(job.job_id)}', '${escapeHtml(job.pair_name)}')" title="Remove this job from queue">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
              <span>Remove</span>
            </button>
          </div>
        </div>
      `).join("");
    }
  }

  // Update Recent Sync Runs tables across views
  updateRecentRunsQueueRows(qList);
}

function updateRecentRunsQueueRows(qList) {
  const tbodies = [
    document.getElementById("recent-runs-tbody"),
    document.getElementById("runs-history-tbody")
  ].filter(Boolean);

  tbodies.forEach((tbody) => {
    const existingQueued = tbody.querySelectorAll(".queued-run-row");
    existingQueued.forEach(el => el.remove());

    if (qList.length === 0) return;

    const noRunsRow = tbody.querySelector("#no-runs-row");
    if (noRunsRow) noRunsRow.style.display = "none";

    const isRunsPage = tbody.id === "runs-history-tbody";

    const rowsHtml = qList.map(job => {
      let timeStr = "Waiting";
      if (job.enqueued_at) {
        try {
          const d = new Date(job.enqueued_at);
          timeStr = d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        } catch (e) {
          timeStr = String(job.enqueued_at).substring(0, 16).replace("T", " ");
        }
      }
      return `
        <tr class="queued-run-row" id="queued-run-row-${escapeHtml(job.job_id)}">
          <td>
            <span class="badge badge-queued">
              <span class="pulse-dot" style="width: 6px; height: 6px; background: #fbbf24; display: inline-block; border-radius: 50%;"></span>
              Queued #${job.position}
            </span>
          </td>
          <td>
            <strong style="color: #fff; font-size: ${isRunsPage ? '0.92rem' : '0.95rem'};">${escapeHtml(job.pair_name)}</strong>
            <div style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono); margin-top: 2px;">
              Waiting in queue (position #${job.position})
            </div>
          </td>
          <td style="color: var(--text-secondary); font-size: 0.85rem;">
            ${escapeHtml(timeStr)}
          </td>
          <td style="color: var(--text-muted); font-size: 0.85rem;">
            Waiting
          </td>
          <td style="color: var(--text-muted);">
            -
          </td>
          <td style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--text-muted);">
            -
          </td>
          <td>
            ${job.dry_run ? '<span class="badge badge-mode">Dry Run</span>' : '<span style="color: var(--text-muted); font-size: 0.8rem;">Live</span>'}
          </td>
          <td style="${isRunsPage ? 'text-align: right; white-space: nowrap;' : ''}">
            <button type="button" class="btn btn-secondary btn-sm" onclick="removeQueuedJob('${escapeHtml(job.job_id)}', '${escapeHtml(job.pair_name)}')" title="Remove this job from the queue">
              Remove
            </button>
          </td>
        </tr>
      `;
    }).join("");

    tbody.insertAdjacentHTML("afterbegin", rowsHtml);
  });
}

async function fetchSyncStatus() {
  try {
    const res = await fetch("/api/sync/status");
    if (res.ok) {
      const data = await res.json();
      updateGlobalStatus(data);
      updateQueueUI(data.queue || []);
    }
  } catch (err) {
    console.warn("Failed to fetch sync status", err);
  }
}

// API Triggers
async function triggerSync(pairId, dryRun = false, queue = true, pairName = "") {
  await executeSync(pairId, dryRun, queue, pairName);
}

async function executeSync(pairId, dryRun = false, queue = true, pairName = "") {
  try {
    const qParam = queue ? "?queue=true" : "";
    const res = await fetch(`/api/sync/${pairId}${qParam}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run: dryRun, queue: queue }),
    });

    if (res.status === 409) {
      // If server returned conflict (e.g. queue was explicitly false), open option to queue
      openQueueModal({
        pairId: pairId,
        pairName: pairName || pairId,
        dryRun: dryRun,
        isAll: false,
      });
      return;
    }

    if (res.status === 400) {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || "Unable to queue job", "warning");
      return;
    }

    if (!res.ok) {
      showToast("Failed to initiate sync", "danger");
      return;
    }

    const data = await res.json();
    if (data.status === "queued") {
      showToast(data.message || `Job for ${data.pair_name || pairName || 'pair'} queued at position #${data.queue_position}`, "success");
      fetchSyncStatus();
    } else {
      showToast(`${dryRun ? "Dry run" : "Sync"} started for ${data.pair_name || pairName || 'pair'}`, "success");
      window.location.href = "/active";
    }
  } catch (err) {
    showToast("Error communicating with server", "danger");
  }
}

async function triggerSyncAll(dryRun = false, queue = true) {
  if (!confirm(`Are you sure you want to run ${dryRun ? "dry run for" : "sync on"} ALL pairs?`)) {
    return;
  }

  await executeSyncAll(dryRun, queue);
}

async function executeSyncAll(dryRun = false, queue = true) {
  try {
    const qParam = queue ? "?queue=true" : "";
    const res = await fetch(`/api/sync/all${qParam}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run: dryRun, queue: queue }),
    });

    if (res.status === 409) {
      openQueueModal({
        isAll: true,
        dryRun: dryRun,
      });
      return;
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || "Failed to start sync all", "danger");
      return;
    }

    const data = await res.json();
    if (data.status === "queued") {
      showToast(data.message || "All pairs queued to run sequentially", "success");
      fetchSyncStatus();
    } else {
      showToast("All sync jobs queued", "success");
      window.location.href = "/active";
    }
  } catch (err) {
    showToast("Error starting batch sync", "danger");
  }
}

async function removeQueuedJob(jobId, pairName) {
  try {
    const res = await fetch(`/api/sync/queue/${jobId}`, { method: "DELETE" });
    if (res.ok) {
      const data = await res.json();
      showToast(data.message || `Removed "${pairName}" from queue`, "info");
      fetchSyncStatus();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || "Failed to remove job from queue", "danger");
    }
  } catch (err) {
    showToast("Error removing job from queue", "danger");
  }
}

async function clearQueue() {
  if (!confirm("Are you sure you want to remove all pending jobs from the sync queue?")) {
    return;
  }

  try {
    const res = await fetch("/api/sync/queue", { method: "DELETE" });
    if (res.ok) {
      const data = await res.json();
      showToast(data.message || "Sync queue cleared", "info");
      fetchSyncStatus();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || "Failed to clear sync queue", "danger");
    }
  } catch (err) {
    showToast("Error clearing sync queue", "danger");
  }
}

async function cancelActiveSync() {
  const isRunning = Boolean(window.__isSyncRunning);
  const qLen = Number(window.__syncQueueLength) || 0;

  if (!isRunning && qLen === 0) {
    showToast("No active or queued sync to cancel", "info");
    return;
  }

  let clearQueueFlag = false;

  if (qLen > 0) {
    const choice = confirm(
      `A sync is currently running, and there are ${qLen} job(s) waiting in the queue.\n\n` +
      `Click OK to cancel the active sync AND remove all pending jobs from queue.\n` +
      `Click Cancel to cancel ONLY the active sync (next queued job will start).`
    );
    if (choice) {
      clearQueueFlag = true;
    } else {
      const cancelOnlyActive = confirm("Cancel the currently active sync run only?");
      if (!cancelOnlyActive) return;
      clearQueueFlag = false;
    }
  } else {
    if (!confirm("Are you sure you want to cancel the currently active sync run?")) {
      return;
    }
  }

  try {
    const res = await fetch(`/api/sync/active?clear_queue=${clearQueueFlag}`, { method: "DELETE" });
    if (res.ok) {
      showToast(clearQueueFlag ? "Cancellation requested and queue cleared" : "Cancellation requested for active sync", "warning");
      fetchSyncStatus();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || "Failed to cancel sync", "danger");
    }
  } catch (err) {
    showToast("Error sending cancel request", "danger");
  }
}

async function deletePair(pairId, pairName) {
  if (!confirm(`Delete sync pair "${pairName}"? Configuration will be removed.`)) {
    return;
  }

  try {
    const res = await fetch(`/api/pairs/${pairId}`, { method: "DELETE" });
    if (res.ok) {
      showToast("Sync pair deleted", "success");
      setTimeout(() => window.location.reload(), 500);
    } else {
      showToast("Failed to delete sync pair", "danger");
    }
  } catch (err) {
    showToast("Error deleting sync pair", "danger");
  }
}

async function duplicatePairDirect(pairId) {
  try {
    const res = await fetch(`/api/pairs/${pairId}/duplicate`, { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      showToast(`Sync pair duplicated as "${data.name}"`, "success");
      setTimeout(() => window.location.reload(), 500);
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || "Failed to duplicate sync pair", "danger");
    }
  } catch (err) {
    showToast("Error duplicating sync pair", "danger");
  }
}

async function deleteRun(runId) {
  if (!confirm("Delete this run record and change history?")) {
    return;
  }

  try {
    const res = await fetch(`/api/runs/${runId}`, { method: "DELETE" });
    if (res.ok) {
      showToast("Run deleted", "success");
      setTimeout(() => window.location.href = "/runs", 500);
    } else {
      showToast("Failed to delete run", "danger");
    }
  } catch (err) {
    showToast("Error deleting run", "danger");
  }
}

async function clearAllRuns(pairId = "", status = "") {
  const isFiltered = Boolean(pairId || status);
  const confirmMsg = isFiltered
    ? "Are you sure you want to clear the filtered run history? This action cannot be undone."
    : "Are you sure you want to clear all sync run history? This action cannot be undone.";

  if (!confirm(confirmMsg)) {
    return;
  }

  try {
    let url = "/api/runs";
    const params = new URLSearchParams();
    if (pairId) params.append("pair_id", pairId);
    if (status) params.append("status", status);
    if (params.toString()) {
      url += `?${params.toString()}`;
    }

    const res = await fetch(url, { method: "DELETE" });
    if (res.ok) {
      const data = await res.json();
      showToast(data.message || "Run history cleared", "success");
      setTimeout(() => {
        if (window.location.pathname.startsWith("/runs/")) {
          window.location.href = "/runs";
        } else if (isFiltered) {
          window.location.href = `/runs?pair=${encodeURIComponent(pairId)}&status=${encodeURIComponent(status)}`;
        } else {
          window.location.reload();
        }
      }, 500);
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || "Failed to clear run history", "danger");
    }
  } catch (err) {
    showToast("Error clearing run history", "danger");
  }
}


async function testPairPaths(pairId) {
  try {
    showToast("Testing source and destination accessibility...", "info");
    const res = await fetch(`/api/pairs/${pairId}/test`, { method: "POST" });
    if (!res.ok) {
      showToast("Path check request failed", "danger");
      return;
    }
    const data = await res.json();

    const srcOk = data.source.exists && data.source.readable;
    const dstOk = data.destination.exists ? data.destination.writable : data.destination.writable;
    let msg = `Source: ${srcOk ? "Accessible (OK)" : "Inaccessible / Missing"}\n`;
    msg += `Destination: ${dstOk ? "Accessible & Writable (OK)" : "Inaccessible / Not Writable"}`;

    if (data.destination_disk) {
      const freeGb = (data.destination_disk.free_bytes / (1024 ** 3)).toFixed(1);
      msg += `\nDestination Free Disk: ${freeGb} GB (${data.destination_disk.percent_used}% used)`;
    }

    alert(msg);
  } catch (err) {
    showToast("Error checking paths", "danger");
  }
}

// Mobile Navigation Drawer Toggle
function toggleSidebar(forceState) {
  const sidebar = document.getElementById("sidebar-nav");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (!sidebar) return;

  const willOpen = typeof forceState === "boolean" 
    ? forceState 
    : !sidebar.classList.contains("open");

  if (willOpen) {
    sidebar.classList.add("open");
    if (backdrop) backdrop.classList.add("open");
    document.body.classList.add("sidebar-open");
  } else {
    sidebar.classList.remove("open");
    if (backdrop) backdrop.classList.remove("open");
    document.body.classList.remove("sidebar-open");
  }
}

window.toggleSidebar = toggleSidebar;

// Auto-initialize SSE and listeners on page load
document.addEventListener("DOMContentLoaded", () => {
  initSSE();
  fetchSyncStatus();

  // Close sidebar when pressing ESC
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      toggleSidebar(false);
    }
  });

  // Close sidebar on resize to desktop width
  window.addEventListener("resize", () => {
    if (window.innerWidth > 768) {
      toggleSidebar(false);
    }
  });
});

