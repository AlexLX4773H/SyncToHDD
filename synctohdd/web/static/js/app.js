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
    } catch (err) {
      console.error("Failed to parse status event", err);
    }
  });

  evtSource.addEventListener("progress", (e) => {
    try {
      const data = JSON.parse(e.data);
      updateGlobalStatus({ is_running: data.status === "syncing" || data.status === "scanning", latest_event: data });
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

  if (!dot || !text) return;

  if (data.is_running) {
    dot.className = "pulse-dot syncing";
    const pairName = data.latest_event ? data.latest_event.pair_name : "Active";
    text.textContent = `Syncing: ${pairName}`;
  } else {
    dot.className = "pulse-dot";
    text.textContent = "Engine Idle";
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
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.innerText = str;
  return div.innerHTML;
}

// API Triggers
async function triggerSync(pairId, dryRun = false) {
  try {
    const res = await fetch(`/api/sync/${pairId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run: dryRun }),
    });

    if (res.status === 409) {
      const err = await res.json();
      showToast(err.detail || "A sync is already running", "warning");
      return;
    }

    if (!res.ok) {
      showToast("Failed to initiate sync", "danger");
      return;
    }

    const data = await res.json();
    showToast(`${dryRun ? "Dry run" : "Sync"} started for ${data.pair_name}`, "success");
    window.location.href = "/active";
  } catch (err) {
    showToast("Error communicating with server", "danger");
  }
}

async function triggerSyncAll(dryRun = false) {
  if (!confirm(`Are you sure you want to run ${dryRun ? "dry run for" : "sync on"} ALL pairs?`)) {
    return;
  }

  try {
    const res = await fetch("/api/sync/all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run: dryRun }),
    });

    if (!res.ok) {
      const err = await res.json();
      showToast(err.detail || "Failed to start sync all", "danger");
      return;
    }

    showToast("All sync jobs queued", "success");
    window.location.href = "/active";
  } catch (err) {
    showToast("Error starting batch sync", "danger");
  }
}

async function cancelActiveSync() {
  if (!confirm("Are you sure you want to cancel the currently active sync run?")) {
    return;
  }

  try {
    const res = await fetch("/api/sync/active", { method: "DELETE" });
    if (res.ok) {
      showToast("Cancellation requested", "warning");
    } else {
      const err = await res.json();
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

// Auto-initialize SSE on page load
document.addEventListener("DOMContentLoaded", () => {
  initSSE();
});
