const state = {
  mode: "auto",
  jobs: [],
  filter: "all",
  query: "",
  settings: {},
  torrentSource: "",
  torrentFiles: [],
  torrentResults: [],
  torrentPage: 1,
  torrentTotal: 0,
  torrentHasPrevious: false,
  torrentHasNext: false,
  torrentPageSize: 20,
  torrentLastQuery: "",
  activeTab: "downloads",
  expandedJobs: new Set(),
  renderedJobSignature: null,
  refreshingJobs: false,
  probeTimer: null,
  probeSequence: 0,
  batchManifest: null,
  batchSelected: new Set(),
  batchQuery: "",
  eventSource: null,
  fallbackPoll: null,
  confirmResolve: null,
  portableToolInstallAttempted: false,
  cookieBrowsers: [],
  updatableTools: [],
};

const terminalStatuses = new Set(["completed", "failed", "cancelled"]);
const activeStatuses = new Set(["queued", "downloading", "paused", "preparing"]);
let thumbnailObserver = null;
const modeHints = {
  auto: "Automatically detect the best download method.",
  youtube: "Download a supported video with yt-dlp.",
  audio: "Extract audio from a supported media URL.",
  torrent: "Download a magnet link or torrent URL with aria2.",
  direct: "Download a direct file URL with aria2.",
  gallery: "Save a gallery or manga and optionally create a PDF.",
  spotify: "Download a Spotify track, album, or playlist.",
};
const modeLabels = {
  auto: "Auto",
  youtube: "Video",
  audio: "Audio",
  torrent: "Torrent",
  direct: "Direct",
  gallery: "Gallery",
  spotify: "Spotify",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

document.addEventListener("DOMContentLoaded", async () => {
  initDesktopShell();
  initDialogs();
  bindInteractions();
  applySavedTheme();
  await Promise.all([loadSettings(), refreshJobs(), loadCookieBrowsers()]);
  await loadDependencyHealth();
  connectJobEvents();
});

function initDesktopShell() {
  const params = new URLSearchParams(window.location.search);
  const customChrome = params.get("desktop") === "1";
  document.body.classList.toggle("desktop-mode", customChrome);
  if (!customChrome) return;
  $("#desktopMinimizeButton")?.addEventListener("click", () => window.pywebview?.api?.minimize?.());
  $("#desktopCloseButton")?.addEventListener("click", () => window.pywebview?.api?.close?.());
}

function initDialogs() {
  $$("dialog").forEach((dialog) => {
    dialog.inert = true;
    dialog.addEventListener("close", () => {
      dialog.inert = true;
      dialog.classList.remove("closing");
    });
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeDialog(dialog);
    });
    dialog.addEventListener("keydown", trapDialogFocus);
  });
}

function bindInteractions() {
  $$(".primary-tab").forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.tab)));
  $$("[data-tab-target]").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    switchTab(link.dataset.tabTarget);
  }));

  $("#openDownloadDialog").addEventListener("click", openDownloadDialog);
  $$(".dialog-close").forEach((button) => button.addEventListener("click", () => closeDialog($("#downloadDialog"))));
  $$(".torrent-dialog-close").forEach((button) => button.addEventListener("click", () => closeDialog($("#torrentDialog"))));
  $$(".batch-dialog-close").forEach((button) => button.addEventListener("click", () => closeDialog($("#batchDialog"))));
  $("#downloadDialog").addEventListener("click", closeOnBackdrop);
  $("#torrentDialog").addEventListener("click", closeOnBackdrop);
  $("#batchDialog").addEventListener("click", closeOnBackdrop);
  $("#confirmDialog").addEventListener("click", closeOnBackdrop);
  $$(".confirm-cancel").forEach((button) => button.addEventListener("click", () => resolveConfirm(false)));
  $("#confirmActionButton").addEventListener("click", () => resolveConfirm(true));
  $("#downloadForm").addEventListener("submit", startDownload);
  $("#urlInput").addEventListener("input", () => {
    updateDownloadValidation();
    scheduleExtractorProbe();
  });
  $("#modeInput").addEventListener("change", (event) => {
    state.mode = event.target.value;
    updateContextOptions();
    updateDownloadValidation();
  });
  $("#resetDownloadOptions").addEventListener("click", resetDownloadOptions);

  $$("#historyTabs .filter-button").forEach((item) => {
    item.setAttribute("aria-pressed", String(item.classList.contains("active")));
  });
  $("#historyTabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-filter]");
    if (!button) return;
    state.filter = button.dataset.filter;
    $$("#historyTabs .filter-button").forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    renderJobs({ force: true });
  });
  $("#downloadSearchInput").addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    renderJobs({ force: true });
  });
  $("#searchAllDownloads").addEventListener("click", () => {
    state.filter = "all";
    $$("#historyTabs .filter-button").forEach((item) => {
      const active = item.dataset.filter === "all";
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    renderJobs({ force: true });
    $("#downloadSearchInput").focus();
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      switchTab("downloads");
      $("#downloadSearchInput").focus();
    }
    if (event.key === "Escape") {
      if ($("#downloadDialog").open) closeDialog($("#downloadDialog"));
      if ($("#torrentDialog").open) closeDialog($("#torrentDialog"));
      if ($("#batchDialog").open) closeDialog($("#batchDialog"));
      if ($("#confirmDialog").open) resolveConfirm(false);
    }
  });

  $("#downloadList").addEventListener("click", handleDownloadListClick);
  $("#clearHistoryButton").addEventListener("click", clearFinished);
  $("#settingsForm").addEventListener("submit", saveSettings);
  $("#themeToggle").addEventListener("click", toggleTheme);
  document.addEventListener("click", handleDocumentActions);

  $("#torrentSearchForm").addEventListener("submit", searchTorrents);
  ["torrentProviderInput", "torrentCategoryInput", "torrentSortInput", "torrentOrderInput"].forEach((id) => {
    $(`#${id}`).addEventListener("change", autoApplyTorrentSearch);
  });
  $("#torrentFirstButton").addEventListener("click", () => loadTorrentPage(1));
  $("#torrentPreviousButton").addEventListener("click", () => loadTorrentPage(state.torrentPage - 1));
  $("#torrentNextButton").addEventListener("click", () => loadTorrentPage(state.torrentPage + 1));
  $("#torrentLastButton").addEventListener("click", () => loadTorrentPage(torrentLastPage()));
  $("#torrentPageInput").addEventListener("change", () => loadTorrentPage(Number($("#torrentPageInput").value || 1)));
  $("#torrentFileInput").addEventListener("change", inspectUploadedTorrent);
  $("#torrentResults").addEventListener("click", handleTorrentResult);
  $("#selectAllTorrentFiles").addEventListener("click", selectAllTorrentFiles);
  $("#downloadSelectedTorrentFiles").addEventListener("click", downloadSelectedTorrentFiles);
  $("#torrentFileList").addEventListener("change", updateTorrentSelectionSummary);
  $("#batchSearchInput").addEventListener("input", (event) => {
    state.batchQuery = event.target.value.trim().toLowerCase();
    renderBatchItems();
  });
  $$(".batch-presets [data-batch-preset]").forEach((button) => button.addEventListener("click", () => applyBatchPreset(button.dataset.batchPreset)));
  $("#batchRangeForm").addEventListener("submit", selectBatchRange);
  $("#batchToggleVisible").addEventListener("change", toggleVisibleBatchItems);
  $("#batchItemList").addEventListener("change", handleBatchItemSelection);
  $("#startBatchButton").addEventListener("click", startSelectedBatch);
  $$(".settings-nav-button").forEach((button) => {
    button.addEventListener("click", () => setActiveSettingsSection(button.dataset.settingsSection));
  });
  $("#dependencyTestButton").addEventListener("click", () => loadDependencyHealth({ autoInstall: false }));
  $("#dependencyInstallButton").addEventListener("click", () => installMissingTools({ automatic: false }));
  $("#toolUpdateButton")?.addEventListener("click", updateTools);
  $("#cookieBrowserInput")?.addEventListener("change", renderCookieProfiles);
  $("#settingsCookiesFile")?.addEventListener("input", updateCookieFileHint);
  $("#cookieFetchButton")?.addEventListener("click", fetchBrowserCookies);
  $$("[data-tool-subtab]").forEach((button) => button.addEventListener("click", () => setActiveToolSubtab(button.dataset.toolSubtab)));
}

function handleDocumentActions(event) {
  const action = event.target.closest("[data-action]");
  if (!action) return;
  if (action.dataset.action === "open-cookie-settings") {
    event.preventDefault();
    closeDialog($("#downloadDialog"));
    switchTab("settings");
    setActiveSettingsSection("settingsYtdlp");
    window.setTimeout(() => $("#cookieBrowserInput")?.focus(), 260);
  }
}

function connectJobEvents() {
  if (!window.EventSource) return startFallbackPolling();
  const source = new EventSource("/api/events");
  state.eventSource = source;
  source.addEventListener("jobs", (event) => {
    try {
      state.jobs = JSON.parse(event.data).jobs || [];
      state.jobs.filter((job) => activeStatuses.has(job.status)).forEach((job) => state.expandedJobs.add(job.id));
      renderJobs();
    } catch (error) {
      console.error(error);
    }
  });
  source.onerror = () => {
    source.close();
    state.eventSource = null;
    startFallbackPolling();
  };
}

function startFallbackPolling() {
  if (state.fallbackPoll) return;
  state.fallbackPoll = window.setInterval(refreshJobs, 1800);
}

function switchTab(tab) {
  state.activeTab = tab;
  document.body.classList.toggle("torrent-tab-active", tab === "torrents");
  document.body.classList.toggle("settings-tab-active", tab === "settings");
  $$(".primary-tab").forEach((button) => {
    const selected = button.dataset.tab === tab;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
  });
  const panels = {
    downloads: $("#downloadsPanel"),
    torrents: $("#torrentsPanel"),
    settings: $("#settingsPanel"),
  };
  Object.entries(panels).forEach(([key, panel]) => {
    panel.hidden = key !== tab;
    panel.classList.toggle("active", key === tab);
  });
  if (tab === "torrents") window.setTimeout(() => $("#torrentSearchInput").focus(), 180);
  if (tab === "settings") window.setTimeout(() => setActiveSettingsSection(activeSettingsSection()), 120);
}

function setActiveSettingsSection(sectionId) {
  if (!sectionId) return;
  $$(".settings-nav-button").forEach((button) => {
    const active = button.dataset.settingsSection === sectionId;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  });
  $$("[data-settings-section-panel]").forEach((panel) => {
    const active = panel.dataset.settingsSectionPanel === sectionId;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
}

function setActiveToolSubtab(panelId) {
  $$("[data-tool-subtab]").forEach((button) => {
    const active = button.dataset.toolSubtab === panelId;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $$(".tool-subpanel").forEach((panel) => {
    const active = panel.id === panelId;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
}

function activeSettingsSection() {
  return $(".settings-nav-button.active")?.dataset.settingsSection || "settingsGeneral";
}

function openDownloadDialog() {
  resetDownloadOptions();
  updateDownloadValidation();
  openDialog($("#downloadDialog"));
  window.setTimeout(() => $("#urlInput").focus(), 100);
}

function openDialog(dialog) {
  dialog.inert = false;
  dialog.showModal();
}

function closeDialog(dialog) {
  if (!dialog?.open) return;
  if (dialog.classList.contains("closing")) return;
  dialog.classList.add("closing");
  window.setTimeout(() => {
    dialog.classList.remove("closing");
    if (dialog.open) dialog.close();
  }, 190);
}

function closeOnBackdrop(event) {
  if (event.target !== event.currentTarget) return;
  if (event.currentTarget.id === "confirmDialog") {
    resolveConfirm(false);
    return;
  }
  closeDialog(event.currentTarget);
}

function trapDialogFocus(event) {
  if (event.key !== "Tab") return;
  const dialog = event.currentTarget;
  const focusable = $$(
    'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
    dialog
  ).filter((element) => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  });
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function updateContextOptions() {
  const mode = state.mode;
  $("#modeHint").textContent = modeHints[mode];
  $("#modeBadge").textContent = modeLabels[mode];
  const visibility = {
    ".option-video": ["auto", "youtube"].includes(mode),
    ".option-audio": ["auto", "youtube", "audio", "spotify"].includes(mode),
    ".option-gallery": ["auto", "gallery"].includes(mode),
    ".option-playlist": ["auto", "youtube", "audio", "gallery", "spotify"].includes(mode),
  };
  Object.entries(visibility).forEach(([selector, visible]) => {
    $$(selector).forEach((element) => { element.hidden = !visible; });
  });
  if (mode === "audio") $("#qualityInput").value = "audio";
  scheduleExtractorProbe();
}

function parseDownloadUrls() {
  return $("#urlInput").value.split(/\n+/).map((value) => value.trim()).filter(Boolean);
}

function isPotentialDownloadSource(value) {
  return /^(https?:\/\/|magnet:)/i.test(value);
}

function updateDownloadValidation({ show = false } = {}) {
  const urls = parseDownloadUrls();
  const invalid = urls.filter((url) => !isPotentialDownloadSource(url));
  const error = $("#urlInputError");
  const input = $("#urlInput");
  const start = $("#startButton");
  let message = "";
  if (!urls.length) {
    message = show ? "Paste at least one URL, magnet link, or torrent URL before starting." : "";
  } else if (invalid.length) {
    message = `Check ${invalid.length} item${invalid.length === 1 ? "" : "s"}: links must start with http://, https://, or magnet:.`;
  }
  error.textContent = message;
  input.setAttribute("aria-invalid", String(Boolean(message)));
  input.closest(".field")?.classList.toggle("field-invalid", Boolean(message));
  start.disabled = !urls.length || Boolean(invalid.length);
  return !message && urls.length > 0;
}

function scheduleExtractorProbe() {
  window.clearTimeout(state.probeTimer);
  const sequence = ++state.probeSequence;
  const probe = $("#extractorProbe");
  const urls = parseDownloadUrls();
  if (!["auto", "youtube", "audio"].includes(state.mode) || urls.length !== 1 || !/^https?:\/\//i.test(urls[0])) {
    probe.className = "extractor-probe";
    probe.textContent = "";
    return;
  }
  probe.className = "extractor-probe checking";
  probe.innerHTML = '<i class="ti ti-loader-2 loading-icon"></i>Checking with yt-dlp…';
  state.probeTimer = window.setTimeout(() => probeExtractor(urls[0], sequence), 550);
}

async function probeExtractor(url, sequence) {
  const probe = $("#extractorProbe");
  try {
    const result = await api("/api/ytdlp/probe", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    if (sequence !== state.probeSequence) return;
    if (result.supported) {
      const label = result.extractor ? ` via ${result.extractor}` : "";
      const title = result.title ? ` · ${result.title}` : "";
      if (result.batch_candidate) $("#playlistInput").checked = true;
      probe.className = "extractor-probe supported";
      probe.innerHTML = result.batch_candidate
        ? `<i class="ti ti-list-check"></i>Multi-item page detected${escapeHtml(label)}${escapeHtml(title)} · Review will open before download.`
        : `<i class="ti ti-circle-check"></i>yt-dlp recognized this link${escapeHtml(label)}${escapeHtml(title)}`;
    } else if (result.requires_auth) {
      const label = result.extractor ? ` (${result.extractor})` : "";
      probe.className = "extractor-probe unsupported";
      probe.innerHTML = `<i class="ti ti-lock"></i><span>yt-dlp recognized this link${escapeHtml(label)}, but it requires browser cookies or sign-in.</span><button class="text-button inline-action" type="button" data-action="open-cookie-settings">Set up cookies</button>`;
    } else if (result.recognized) {
      const label = result.extractor ? ` (${result.extractor})` : "";
      probe.className = "extractor-probe unsupported";
      probe.innerHTML = `<i class="ti ti-alert-circle"></i>yt-dlp recognizes this site${escapeHtml(label)}, but could not extract downloadable media from this URL.`;
    } else {
      probe.className = "extractor-probe unsupported";
      probe.innerHTML = '<i class="ti ti-info-circle"></i>No yt-dlp media detected; Auto will try the other download methods.';
    }
  } catch (error) {
    if (sequence !== state.probeSequence) return;
    probe.className = "extractor-probe unsupported";
    probe.innerHTML = '<i class="ti ti-info-circle"></i>Could not check now; Auto detection will retry when started.';
  }
}

function resetDownloadOptions() {
  state.mode = "auto";
  $("#modeInput").value = "auto";
  $("#qualityInput").value = state.settings.default_video_quality || "best";
  $("#audioFormatInput").value = state.settings.default_audio_format || "mp3";
  $("#convertPdfInput").checked = Boolean(state.settings.manga_auto_convert_pdf);
  $("#playlistInput").checked = false;
  updateContextOptions();
  updateDownloadValidation();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

async function startDownload(event) {
  event.preventDefault();
  if (!updateDownloadValidation({ show: true })) {
    $("#urlInput").focus();
    return;
  }
  const urls = parseDownloadUrls();
  const button = $("#startButton");
  let playlist = $("#playlistInput").checked;
  setButtonLoading(button, true, $("#playlistInput").checked ? "Inspecting…" : "Starting…");
  const requests = urls.map((url) => ({
    url,
    type: state.mode,
    quality: $("#qualityInput").value,
    audio_format: $("#audioFormatInput").value,
    convert_to_pdf: $("#convertPdfInput").checked,
    playlist,
  }));
  try {
    if (!playlist && requests.length === 1 && ["auto", "youtube", "audio"].includes(state.mode) && /^https?:\/\//i.test(requests[0].url)) {
      setButtonLoading(button, true, "Checking…");
      try {
        const probe = await api("/api/ytdlp/probe", {
          method: "POST",
          body: JSON.stringify({ url: requests[0].url }),
        });
        if (probe.batch_candidate) {
          playlist = true;
          $("#playlistInput").checked = true;
          requests[0].playlist = true;
        }
      } catch (error) {
        // Auto detection can still fall back to the regular request path.
      }
      setButtonLoading(button, true, playlist ? "Inspecting…" : "Starting…");
    }
    if (requests.length === 1 && requests[0].playlist) {
      await inspectBatch(requests[0]);
      return;
    }
    await startRequests(requests);
    $("#urlInput").value = "";
    closeDialog($("#downloadDialog"));
    switchTab("downloads");
    toast(`${requests.length} download${requests.length === 1 ? "" : "s"} queued`);
    await refreshJobs();
  } catch (error) {
    toast(error.message, true);
  } finally {
    setButtonLoading(button, false, "Start download");
  }
}

async function inspectBatch(request) {
  const data = await api("/api/batches/inspect", {
    method: "POST",
    body: JSON.stringify({ url: request.url }),
  });
  state.batchManifest = data.manifest;
  state.batchQuery = "";
  $("#batchSearchInput").value = "";
  const defaultCount = data.manifest.item_count > 20 ? 20 : data.manifest.item_count;
  state.batchSelected = new Set(data.manifest.items.slice(0, defaultCount).map((item) => item.index));
  $("#batchDialogTitle").textContent = data.manifest.title;
  $("#batchDialogSubtitle").textContent = `${data.manifest.provider} · Review before anything is queued.`;
  $("#batchRangeFrom").value = 1;
  $("#batchRangeTo").value = defaultCount;
  $("#batchRangeFrom").max = data.manifest.item_count;
  $("#batchRangeTo").max = data.manifest.item_count;
  $("#batchContinueInput").checked = true;
  renderBatchItems();
  closeDialog($("#downloadDialog"));
  window.setTimeout(() => openDialog($("#batchDialog")), 140);
}

function renderBatchItems() {
  const manifest = state.batchManifest;
  if (!manifest) return;
  const items = visibleBatchItems();
  $("#batchItemList").innerHTML = items.length
    ? items.map((item) => `
      <label class="batch-item">
        <input type="checkbox" value="${item.index}" ${state.batchSelected.has(item.index) ? "checked" : ""}>
        <span>#${item.index}</span>
        ${batchThumbnail(item)}
        <span class="batch-item-copy"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.url)}</small></span>
        <span>${formatDuration(item.duration_seconds)}</span>
        <span>${item.size_bytes ? formatBytes(item.size_bytes) : "Unknown"}</span>
      </label>`).join("")
    : emptyState("No matching items", "Clear the search to see the full batch.");
  hydrateBatchThumbnails($("#batchItemList"));
  const visibleIndexes = items.map((item) => item.index);
  $("#batchToggleVisible").checked = Boolean(
    visibleIndexes.length && visibleIndexes.every((index) => state.batchSelected.has(index))
  );
  updateBatchSummary();
}

function visibleBatchItems() {
  const items = state.batchManifest?.items || [];
  if (!state.batchQuery) return items;
  return items.filter((item) => `${item.title} ${item.url}`.toLowerCase().includes(state.batchQuery));
}

function applyBatchPreset(preset) {
  const items = state.batchManifest?.items || [];
  if (preset === "none") state.batchSelected.clear();
  else if (preset === "all") state.batchSelected = new Set(items.map((item) => item.index));
  else state.batchSelected = new Set(items.slice(0, Number(preset)).map((item) => item.index));
  renderBatchItems();
}

function selectBatchRange(event) {
  event.preventDefault();
  const total = state.batchManifest?.item_count || 0;
  const from = Math.max(1, Math.min(total, Number($("#batchRangeFrom").value || 1)));
  const to = Math.max(from, Math.min(total, Number($("#batchRangeTo").value || total)));
  state.batchSelected = new Set(
    (state.batchManifest?.items || [])
      .filter((item) => item.index >= from && item.index <= to)
      .map((item) => item.index)
  );
  renderBatchItems();
}

function toggleVisibleBatchItems(event) {
  visibleBatchItems().forEach((item) => {
    if (event.target.checked) state.batchSelected.add(item.index);
    else state.batchSelected.delete(item.index);
  });
  renderBatchItems();
}

function handleBatchItemSelection(event) {
  const checkbox = event.target.closest('input[type="checkbox"]');
  if (!checkbox) return;
  const index = Number(checkbox.value);
  checkbox.checked ? state.batchSelected.add(index) : state.batchSelected.delete(index);
  updateBatchSummary();
}

function updateBatchSummary() {
  const manifest = state.batchManifest;
  if (!manifest) return;
  const selected = manifest.items.filter((item) => state.batchSelected.has(item.index));
  const estimated = selected.reduce((sum, item) => sum + Number(item.size_bytes || 0), 0);
  $("#batchTotalCount").textContent = manifest.item_count;
  $("#batchSelectedCount").textContent = selected.length;
  $("#batchEstimatedSize").textContent = estimated ? formatBytes(estimated) : "Unknown";
  $("#batchFreeSpace").textContent = manifest.free_bytes ? formatBytes(manifest.free_bytes) : "Unknown";
  const warning = $("#batchWarning");
  const allSelected = selected.length === manifest.item_count && manifest.item_count > 20;
  const diskRisk = Boolean(estimated && manifest.free_bytes && estimated > manifest.free_bytes);
  warning.hidden = !(allSelected || diskRisk);
  warning.textContent = diskRisk
    ? "The selected estimate exceeds currently available disk space."
    : `You selected all ${manifest.item_count} items. Sequential processing may take a long time.`;
  $("#startBatchButton").disabled = selected.length === 0 || diskRisk;
  $("#startBatchButton span").textContent = `Start ${selected.length} selected`;
}

async function startSelectedBatch() {
  const manifest = state.batchManifest;
  if (!manifest || !state.batchSelected.size) return;
  const button = $("#startBatchButton");
  setButtonLoading(button, true, "Queuing batch…");
  try {
    await api(`/api/batches/${manifest.id}/start`, {
      method: "POST",
      body: JSON.stringify({
        indexes: [...state.batchSelected].sort((a, b) => a - b),
        quality: $("#qualityInput").value,
        audio_format: $("#audioFormatInput").value,
        continue_on_error: $("#batchContinueInput").checked,
      }),
    });
    $("#urlInput").value = "";
    closeDialog($("#batchDialog"));
    switchTab("downloads");
    toast(`${state.batchSelected.size} batch items queued`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    setButtonLoading(button, false, "Start selected");
    updateBatchSummary();
  }
}

function setButtonLoading(button, loading, text, icon = "download") {
  button.disabled = loading;
  button.innerHTML = `<i class="ti ti-${loading ? "loader-2 loading-icon" : icon}"></i><span>${text}</span>`;
}

async function refreshJobs() {
  if (state.refreshingJobs) return;
  state.refreshingJobs = true;
  try {
    state.jobs = (await api("/api/downloads")).jobs;
    state.jobs.filter((job) => activeStatuses.has(job.status)).forEach((job) => state.expandedJobs.add(job.id));
    renderJobs();
  } catch (error) {
    console.error(error);
  } finally {
    state.refreshingJobs = false;
  }
}

function renderJobs({ force = false } = {}) {
  const counts = {
    all: state.jobs.length,
    active: state.jobs.filter((job) => !terminalStatuses.has(job.status)).length,
    completed: state.jobs.filter((job) => job.status === "completed").length,
    failed: state.jobs.filter((job) => job.status === "failed").length,
    cancelled: state.jobs.filter((job) => job.status === "cancelled").length,
  };
  Object.entries(counts).forEach(([key, value]) => $(`#${key}Count`).textContent = value);
  const active = state.jobs.filter((job) => !terminalStatuses.has(job.status));
  $("#overallSpeed").textContent = active.length
    ? `Overall speed · ${formatBytes(active.reduce((sum, job) => sum + job.speed_bytes, 0))}/s`
    : "Overall speed · 0 B/s";
  $("#downloadsHeading").textContent = state.filter === "all"
    ? "All downloads"
    : `${state.filter[0].toUpperCase()}${state.filter.slice(1)} downloads`;

  const jobs = getVisibleJobs();
  updateDownloadSearchNotice(jobs);
  const signature = jobs.map((job) => `${job.id}:${job.status}`).join("|");
  const canPatch = !force
    && signature === state.renderedJobSignature
    && jobs.every((job) => findRenderedJob(job.id));

  if (canPatch) {
    patchDownloadRows(jobs);
  } else {
    $("#downloadList").innerHTML = jobs.length
      ? jobs.map(downloadRow).join("")
      : emptyState("No downloads found", state.query ? "Try a different search." : "Start a new download to see it here.");
    state.renderedJobSignature = signature;
  }
  hydrateBatchThumbnails($("#downloadList"));

  $("#recentCount").textContent = `Showing ${jobs.length} of ${state.jobs.length} download${state.jobs.length === 1 ? "" : "s"}`;
}

function updateDownloadSearchNotice(visibleJobs) {
  const notice = $("#downloadSearchNotice");
  const noticeText = $("#downloadSearchNoticeText");
  if (!state.query || state.filter === "all" || visibleJobs.length) {
    notice.hidden = true;
    noticeText.textContent = "";
    return;
  }
  const allMatches = getVisibleJobs({ filter: "all" }).length;
  if (!allMatches) {
    notice.hidden = true;
    noticeText.textContent = "";
    return;
  }
  notice.hidden = false;
  noticeText.textContent = `${allMatches} matching download${allMatches === 1 ? "" : "s"} exist outside the ${state.filter} filter.`;
}

function getVisibleJobs({ filter = state.filter, query = state.query } = {}) {
  return state.jobs.filter((job) => {
    const statusMatch = filter === "all"
      || (filter === "active" && !terminalStatuses.has(job.status))
      || job.status === filter;
    const haystack = `${job.title} ${job.request?.url || ""} ${job.provider} ${job.error || ""}`.toLowerCase();
    return statusMatch && (!query || haystack.includes(query));
  });
}

function findRenderedJob(id) {
  return $$(".download-row").find((row) => row.dataset.id === String(id));
}

function patchDownloadRows(jobs) {
  jobs.forEach((job) => {
    const row = findRenderedJob(job.id);
    if (!row) return;
    const active = !terminalStatuses.has(job.status);
    const title = $("[data-job-title]", row);
    const detail = $("[data-job-detail]", row);
    const size = $("[data-job-size]", row);
    const stateCell = $("[data-job-state]", row);
    if (title && title.textContent !== job.title) title.textContent = job.title;
    if (detail) {
      detail.textContent = active
        ? `${formatBytes(job.downloaded_bytes)} / ${job.total_bytes ? formatBytes(job.total_bytes) : "—"} · ${formatBytes(job.speed_bytes)}/s`
        : sourceLabel(job);
    }
    if (size) size.textContent = formatBytes(job.total_bytes || job.downloaded_bytes);
    if (stateCell && active) {
      const status = $(".status", stateCell);
      if (status) {
        status.className = `status ${job.status}`;
        status.textContent = job.status;
      }
    }
    const progress = $(".progress-fill", row);
    if (progress) progress.style.width = `${clamp(job.percent)}%`;
    const summary = $("[data-progress-summary]", row);
    if (summary) {
      summary.textContent = job.metadata?.batch
        ? batchProgressText(job)
        : `${formatBytes(job.downloaded_bytes)} / ${job.total_bytes ? formatBytes(job.total_bytes) : "—"} · ${formatBytes(job.speed_bytes)}/s · ${formatEta(job.eta_seconds)} remaining · ${Math.round(job.percent)}%`;
    }
    const children = $("[data-batch-children]", row);
    const itemsSignature = batchItemsSignature(job);
    if (children && children.dataset.itemsSignature !== itemsSignature) {
      children.innerHTML = batchChildren(job);
      children.dataset.itemsSignature = itemsSignature;
      hydrateBatchThumbnails(children);
    }
  });
}

function downloadRow(job, index) {
  const expanded = state.expandedJobs.has(job.id);
  const active = !terminalStatuses.has(job.status);
  const icon = sourceIcon(job.provider, job.request.type);
  const iconClass = sourceIconClass(job.provider, job.request.type);
  const detail = active
    ? `${formatBytes(job.downloaded_bytes)} / ${job.total_bytes ? formatBytes(job.total_bytes) : "—"} · ${formatBytes(job.speed_bytes)}/s`
    : sourceLabel(job);
  return `<article class="download-row${expanded ? " expanded" : ""}" data-id="${escapeHtml(job.id)}" style="animation-delay:${Math.min(index * 24, 180)}ms">
    <button class="download-summary" type="button" data-expand="${escapeHtml(job.id)}" aria-expanded="${expanded}" aria-label="Toggle details for ${escapeHtml(job.title)}">
      <span class="download-identity">
        <span class="source-icon ${iconClass}"><i class="${icon}"></i></span>
        <span class="download-copy">
          <strong data-job-title>${escapeHtml(job.title)}</strong>
          <small data-job-detail>${escapeHtml(detail)}</small>
        </span>
      </span>
      <span class="download-meta" data-job-size>${formatBytes(job.total_bytes || job.downloaded_bytes)}</span>
      <span class="download-meta" data-job-state>${active ? `<span class="status ${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>` : formatDate(job.completed_at)}</span>
      <i class="ti ti-chevron-down row-chevron"></i>
    </button>
    <div class="download-details">
      <div class="download-details-inner">
        <div class="download-progress-panel">
          ${active ? activeJobDetails(job) : finishedJobDetails(job)}
        </div>
      </div>
    </div>
  </article>`;
}

function activeJobDetails(job) {
  const paused = job.status === "paused";
  if (job.metadata?.batch) {
    if (job.metadata?.interrupted_by_restart) {
      return `<div class="progress-track"><div class="progress-fill" style="width:${clamp(job.percent)}%"></div></div>
        <div class="progress-meta">
          <span class="batch-progress-summary" data-progress-summary>${escapeHtml(batchProgressText(job))} · interrupted by app restart</span>
          <span class="progress-actions">
            <button class="job-action resume-batch-button" type="button" data-id="${job.id}">
              <i class="ti ti-player-play"></i>Resume remaining
            </button>
          </span>
        </div>
        <div class="batch-children" data-batch-children data-items-signature="${escapeHtml(batchItemsSignature(job))}">${batchChildren(job)}</div>`;
    }
    return `<div class="progress-track"><div class="progress-fill" style="width:${clamp(job.percent)}%"></div></div>
      <div class="progress-meta">
        <span class="batch-progress-summary" data-progress-summary>${escapeHtml(batchProgressText(job))}</span>
        <span class="progress-actions">
          <button class="job-action" type="button" data-id="${job.id}" data-action="${paused ? "resume" : "pause"}">
            <i class="ti ti-${paused ? "player-play" : "clock-pause"}"></i>${paused ? "Resume batch" : "Pause after current"}
          </button>
          <button class="job-action" type="button" data-id="${job.id}" data-action="skip">
            <i class="ti ti-player-skip-forward"></i>Skip current
          </button>
          <button class="job-action danger" type="button" data-id="${job.id}" data-action="cancel">
            <i class="ti ti-x"></i>Cancel remaining
          </button>
        </span>
      </div>
      <div class="batch-children" data-batch-children data-items-signature="${escapeHtml(batchItemsSignature(job))}">${batchChildren(job)}</div>`;
  }
  return `<div class="progress-track"><div class="progress-fill" style="width:${clamp(job.percent)}%"></div></div>
    <div class="progress-meta">
      <span data-progress-summary>${formatBytes(job.downloaded_bytes)} / ${job.total_bytes ? formatBytes(job.total_bytes) : "—"} · ${formatBytes(job.speed_bytes)}/s · ${formatEta(job.eta_seconds)} remaining · ${Math.round(job.percent)}%</span>
      <span class="progress-actions">
        <button class="job-action" type="button" data-id="${job.id}" data-action="${paused ? "resume" : "pause"}">
          <i class="ti ti-${paused ? "player-play" : "player-pause"}"></i>${paused ? "Resume" : "Pause"}
        </button>
        <button class="job-action danger" type="button" data-id="${job.id}" data-action="cancel">
          <i class="ti ti-x"></i>Cancel
        </button>
      </span>
    </div>`;
}

function finishedJobDetails(job) {
  const message = job.output_path || job.error || "No additional details.";
  const canResumeBatch = job.metadata?.batch
    && (job.metadata?.items || []).some((item) => !["completed", "skipped"].includes(item.status));
  const outputActions = job.output_path ? `
      <button class="job-action" type="button" data-copy-path="${escapeHtml(job.output_path)}"><i class="ti ti-copy"></i>Copy path</button>
      <button class="job-action" type="button" data-open-path="${escapeHtml(job.output_path)}"><i class="ti ti-folder-open"></i>Open folder</button>` : "";
  return `<div class="progress-meta">
    <span class="status ${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
    <span class="${job.status === "failed" ? "error-detail" : ""}">${escapeHtml(message)}</span>
    <span class="progress-actions">
      ${outputActions}
      ${canResumeBatch ? `<button class="job-action resume-batch-button" type="button" data-id="${job.id}"><i class="ti ti-player-play"></i>Resume remaining</button>` : ""}
      ${job.metadata?.failed_count ? `<button class="job-action retry-failed-button" type="button" data-id="${job.id}"><i class="ti ti-refresh"></i>Retry ${job.metadata.failed_count} failed</button>` : ""}
      ${job.provider === "gallery" && job.metadata?.folder ? `<button class="job-action pdf-button" type="button" data-folder="${escapeHtml(job.metadata.folder)}"><i class="ti ti-file-type-pdf"></i>Create PDF</button>` : ""}
    </span>
  </div>
  ${job.metadata?.batch ? `<div class="batch-children" data-batch-children data-items-signature="${escapeHtml(batchItemsSignature(job))}">${batchChildren(job)}</div>` : ""}`;
}

function handleDownloadListClick(event) {
  const action = event.target.closest("[data-action]");
  if (action) {
    event.stopPropagation();
    controlJob(action.dataset.id, action.dataset.action);
    return;
  }
  const copyPathButton = event.target.closest("[data-copy-path]");
  if (copyPathButton) {
    event.stopPropagation();
    copyPath(copyPathButton.dataset.copyPath);
    return;
  }
  const openPathButton = event.target.closest("[data-open-path]");
  if (openPathButton) {
    event.stopPropagation();
    openPath(openPathButton.dataset.openPath);
    return;
  }
  const pdf = event.target.closest(".pdf-button");
  if (pdf) {
    event.stopPropagation();
    convertGallery(pdf.dataset.folder);
    return;
  }
  const retry = event.target.closest(".retry-failed-button");
  if (retry) {
    event.stopPropagation();
    retryFailedBatch(retry.dataset.id);
    return;
  }
  const resumeBatch = event.target.closest(".resume-batch-button");
  if (resumeBatch) {
    event.stopPropagation();
    resumeSavedBatch(resumeBatch.dataset.id);
    return;
  }
  const summary = event.target.closest("[data-expand]");
  if (!summary) return;
  const id = summary.dataset.expand;
  state.expandedJobs.has(id) ? state.expandedJobs.delete(id) : state.expandedJobs.add(id);
  const row = summary.closest(".download-row");
  row.classList.toggle("expanded");
  summary.setAttribute("aria-expanded", String(row.classList.contains("expanded")));
}

async function controlJob(id, action) {
  if (["cancel", "skip"].includes(action)) {
    const confirmed = await confirmAction({
      title: action === "skip" ? "Skip current item?" : "Cancel download?",
      message: action === "skip"
        ? "The current batch item will be skipped and the queue will continue."
        : "This will stop the current download or remaining batch items.",
      confirmLabel: action === "skip" ? "Skip item" : "Cancel download",
      danger: action === "cancel",
    });
    if (!confirmed) return;
  }
  try {
    await api(`/api/downloads/${id}/${action}`, { method: "POST" });
    const labels = {
      cancel: "Remaining items cancelled",
      pause: "Batch will pause after the current item",
      resume: "Batch resumed",
      skip: "Current item skipped",
    };
    toast(labels[action] || `Download ${action}d`);
    await refreshJobs();
  } catch (error) {
    toast(error.message, true);
  }
}

async function copyPath(path) {
  try {
    await navigator.clipboard.writeText(path);
    toast("Output path copied");
  } catch (error) {
    toast("Could not copy path", true);
  }
}

async function openPath(path) {
  try {
    await api("/api/open-path", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
    toast("Opened output folder");
  } catch (error) {
    toast(error.message, true);
  }
}

async function retryFailedBatch(id) {
  try {
    await api(`/api/downloads/${id}/retry-failed`, { method: "POST" });
    toast("Failed batch items queued again");
  } catch (error) {
    toast(error.message, true);
  }
}

async function resumeSavedBatch(id) {
  try {
    const result = await api(`/api/downloads/${id}/resume-batch`, { method: "POST" });
    state.expandedJobs.add(result.job.id);
    toast("Unfinished batch items resumed");
    await refreshJobs();
  } catch (error) {
    toast(error.message, true);
  }
}

function batchProgressText(job) {
  const metadata = job.metadata || {};
  const total = Number(metadata.total_items || 0);
  const completed = Number(metadata.completed_items || 0);
  const failed = Number(metadata.failed_count || 0);
  const current = Number(metadata.current_item || Math.min(completed + failed + 1, total));
  const transfer = job.downloaded_bytes
    ? ` · ${formatBytes(job.downloaded_bytes)}${job.total_bytes ? ` / ${formatBytes(job.total_bytes)}` : ""}`
    : "";
  const speed = job.speed_bytes ? ` · ${formatBytes(job.speed_bytes)}/s` : "";
  return `${completed}/${total} completed · ${failed} failed/skipped · item ${current}/${total}${transfer}${speed}`;
}

function batchChildren(job) {
  const items = job.metadata?.items || [];
  return items.map((item) => `
    <div class="batch-child">
      <span>#${escapeHtml(item.index)}</span>
      ${batchThumbnail(item)}
      <strong title="${escapeHtml(item.error || item.url || "")}">${escapeHtml(item.title || `Item ${item.index}`)}</strong>
      <span class="status ${escapeHtml(item.status || "pending")}">${escapeHtml(item.status || "pending")}</span>
    </div>`).join("");
}

function batchItemsSignature(job) {
  return (job.metadata?.items || [])
    .map((item) => `${item.index}:${item.status}:${item.title}:${item.thumbnail_url || ""}`)
    .join("|");
}

function batchThumbnail(item) {
  const itemUrl = String(item.url || "");
  const thumbnailUrl = String(item.thumbnail_url || "");
  const fallback = /^https?:\/\//i.test(itemUrl)
    ? `/api/ytdlp/thumbnail?url=${encodeURIComponent(item.url)}`
    : "";
  let source = thumbnailUrl && fallback
    ? `${fallback}&thumbnail=${encodeURIComponent(thumbnailUrl)}`
    : thumbnailUrl;
  if (!source) source = fallback;
  return source
    ? `<span class="batch-thumbnail"><img data-src="${escapeHtml(source)}" data-fallback="${escapeHtml(source === fallback ? "" : fallback)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="fallbackBatchThumbnail(this)"><i class="ti ti-video"></i></span>`
    : `<span class="batch-thumbnail thumbnail-failed"><i class="ti ti-video"></i></span>`;
}

function hydrateBatchThumbnails(root) {
  if (!root) return;
  const images = $$("img[data-src]", root);
  if (!images.length) return;
  images.forEach(loadBatchThumbnail);
}

function loadBatchThumbnail(image) {
  if (!image?.dataset.src) return;
  image.src = image.dataset.src;
  image.removeAttribute("data-src");
}

function fallbackBatchThumbnail(image) {
  const fallback = image?.dataset.fallback;
  if (fallback && image.src !== new URL(fallback, location.href).href) {
    image.dataset.fallback = "";
    image.src = fallback;
    return;
  }
  image?.parentElement?.classList.add("thumbnail-failed");
}

async function clearFinished() {
  const finishedCount = state.jobs.filter((job) => terminalStatuses.has(job.status)).length;
  if (!finishedCount) return toast("No finished downloads to clear");
  const confirmed = await confirmAction({
    title: "Clear finished downloads?",
    message: `This removes ${finishedCount} finished item${finishedCount === 1 ? "" : "s"} from the history list. Files on disk are not deleted.`,
    confirmLabel: "Clear history",
    danger: true,
  });
  if (!confirmed) return;
  try {
    const result = await api("/api/downloads/finished", { method: "DELETE" });
    toast(`${result.removed} finished download${result.removed === 1 ? "" : "s"} cleared`);
    await refreshJobs();
  } catch (error) {
    toast(error.message, true);
  }
}

async function searchTorrents(event) {
  event.preventDefault();
  await loadTorrentPage(1);
}

async function autoApplyTorrentSearch() {
  const query = $("#torrentSearchInput").value.trim();
  if (!query || !state.torrentTotal) {
    $("#torrentSortStatus").textContent = query ? "Sorting will apply when you search." : "";
    return;
  }
  $("#torrentSortStatus").textContent = "Updating results…";
  await loadTorrentPage(1);
}

async function loadTorrentPage(page) {
  const query = $("#torrentSearchInput").value.trim();
  if (!query) return toast("Enter a torrent search query", true);
  const provider = $("#torrentProviderInput").value;
  const category = $("#torrentCategoryInput").value;
  const sort = $("#torrentSortInput").value;
  const order = $("#torrentOrderInput").value;
  page = Math.max(1, Math.min(torrentLastPage(), Number(page || 1)));
  state.torrentLastQuery = query;
  $("#torrentResults").innerHTML = loadingState("Searching indexes…");
  $("#torrentPagination").hidden = true;
  $("#torrentSortStatus").textContent = "Searching indexes…";
  try {
    const data = await api(
      `/api/torrents/search?q=${encodeURIComponent(query)}`
      + `&provider=${provider}&category=${category}&page=${page}`
      + `&page_size=${state.torrentPageSize}&sort=${sort}&order=${order}`
    );
    state.torrentResults = data.results;
    state.torrentPage = data.page;
    state.torrentTotal = data.total;
    state.torrentHasPrevious = data.has_previous;
    state.torrentHasNext = data.has_next;
    renderTorrentResults(provider);
    $("#torrentSortStatus").textContent = `Showing ${data.sort || sort} ${data.order === "asc" ? "low to high" : "high to low"}.`;
  } catch (error) {
    $("#torrentResults").innerHTML = emptyState("Search unavailable", error.message);
    $("#torrentSortStatus").textContent = "";
    toast(error.message, true);
  }
}

function renderTorrentResults(provider) {
  $("#torrentResults").innerHTML = state.torrentResults.length
    ? state.torrentResults.map((item, index) => torrentResultRow(item, provider, index)).join("")
    : emptyState("No torrent results", "Try another query, category, or indexer.");
  const lastPage = torrentLastPage();
  $("#torrentPagination").hidden = state.torrentTotal <= state.torrentPageSize;
  $("#torrentFirstButton").disabled = !state.torrentHasPrevious;
  $("#torrentPreviousButton").disabled = !state.torrentHasPrevious;
  $("#torrentNextButton").disabled = !state.torrentHasNext;
  $("#torrentLastButton").disabled = !state.torrentHasNext;
  $("#torrentPageInput").max = lastPage;
  $("#torrentPageInput").value = state.torrentPage;
  const first = state.torrentTotal ? (state.torrentPage - 1) * state.torrentPageSize + 1 : 0;
  const last = Math.min(state.torrentPage * state.torrentPageSize, state.torrentTotal);
  $("#torrentPageSummary").textContent = `${first}–${last} of ${state.torrentTotal} · Page ${state.torrentPage}`;
  $("#torrentResults").scrollTop = 0;
}

function torrentLastPage() {
  return Math.max(1, Math.ceil((state.torrentTotal || state.torrentPageSize) / state.torrentPageSize));
}

function torrentResultRow(item, provider, index) {
  return `<div class="torrent-result" style="animation-delay:${Math.min(index * 25, 200)}ms">
    <div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.category || "Uncategorized")}</small></div>
    <small>${item.size ? formatBytes(item.size) : escapeHtml(item.size_text || "—")}</small>
    <small class="seed-count">${Number(item.seeders || 0)}</small>
    <small>${escapeHtml(formatTorrentDate(item.published_at))}</small>
    <small>${escapeHtml(item.indexer || provider)}</small>
    <button class="button button-outline torrent-result-button" type="button" data-provider="${escapeHtml(provider)}" data-source="${escapeHtml(item.source_url)}" data-title="${escapeHtml(item.title)}">Download</button>
  </div>`;
}

function formatTorrentDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
}

async function handleTorrentResult(event) {
  const button = event.target.closest(".torrent-result-button");
  if (!button) return;
  button.disabled = true;
  try {
    let source = button.dataset.source;
    if (button.dataset.provider === "prowlarr" && !source.startsWith("magnet:")) {
      source = (await api("/api/torrents/resolve", {
        method: "POST",
        body: JSON.stringify({ provider: "prowlarr", source_url: source }),
      })).source;
    }
    if (source.startsWith("magnet:")) {
      const confirmed = await confirmAction({
        title: "Queue torrent?",
        message: `Start downloading "${button.dataset.title || "this torrent"}"?`,
        confirmLabel: "Queue torrent",
      });
      if (!confirmed) return;
      await startRequests([{ url: source, type: "torrent", quality: "best", audio_format: "mp3" }]);
      toast("Torrent queued");
      switchTab("downloads");
      await refreshJobs();
    } else {
      await inspectTorrentSource(source);
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function inspectUploadedTorrent(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const response = await fetch("/api/torrents/inspect", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not inspect torrent");
    openTorrentDialog(data);
  } catch (error) {
    toast(error.message, true);
  } finally {
    event.target.value = "";
  }
}

async function inspectTorrentSource(source) {
  openTorrentDialog(await api("/api/torrents/inspect", {
    method: "POST",
    body: JSON.stringify({ source }),
  }));
}

function openTorrentDialog(data) {
  state.torrentSource = data.source;
  state.torrentFiles = data.files;
  $("#torrentDialogName").textContent = data.name;
  $("#torrentFileList").innerHTML = data.files.map((file) => `
    <label class="torrent-file-option">
      <input type="checkbox" value="${escapeHtml(file.index)}" checked>
      <span>#${escapeHtml(file.index)}</span>
      <strong>${escapeHtml(file.path)}</strong>
    </label>`).join("");
  updateTorrentSelectionSummary();
  openDialog($("#torrentDialog"));
}

function confirmAction({ title = "Confirm action", message = "Are you sure?", confirmLabel = "Confirm", danger = false } = {}) {
  return new Promise((resolve) => {
    state.confirmResolve = resolve;
    $("#confirmDialogTitle").textContent = title;
    $("#confirmDialogMessage").textContent = message;
    const button = $("#confirmActionButton");
    button.textContent = confirmLabel;
    button.classList.toggle("button-danger", danger);
    openDialog($("#confirmDialog"));
    window.setTimeout(() => button.focus(), 80);
  });
}

function resolveConfirm(value) {
  const resolver = state.confirmResolve;
  state.confirmResolve = null;
  closeDialog($("#confirmDialog"));
  if (resolver) resolver(Boolean(value));
}

function updateTorrentSelectionSummary() {
  const selected = $$("#torrentFileList input[type=checkbox]:checked").length;
  const total = $$("#torrentFileList input[type=checkbox]").length;
  $("#torrentSelectionSummary").textContent = `${selected} of ${total} files selected`;
}

function selectAllTorrentFiles() {
  const boxes = $$("#torrentFileList input[type=checkbox]");
  const shouldCheck = boxes.some((box) => !box.checked);
  boxes.forEach((box) => { box.checked = shouldCheck; });
  updateTorrentSelectionSummary();
}

async function downloadSelectedTorrentFiles() {
  const selected = $$("#torrentFileList input[type=checkbox]:checked").map((box) => box.value);
  if (!selected.length) return toast("Select at least one torrent file", true);
  try {
    await startRequests([{
      url: state.torrentSource,
      type: "torrent",
      quality: "best",
      audio_format: "mp3",
      selected_files: selected,
    }]);
    closeDialog($("#torrentDialog"));
    switchTab("downloads");
    toast(`${selected.length} torrent file${selected.length === 1 ? "" : "s"} queued`);
    await refreshJobs();
  } catch (error) {
    toast(error.message, true);
  }
}

async function startRequests(requests) {
  return api("/api/downloads/start", {
    method: "POST",
    body: JSON.stringify(requests.length === 1 ? requests[0] : requests),
  });
}

async function convertGallery(folder) {
  try {
    const result = await api("/api/pdf/convert", {
      method: "POST",
      body: JSON.stringify({ folder }),
    });
    toast(`PDF created: ${result.pdf_path}`);
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadSettings() {
  try {
    state.settings = await api("/api/settings");
    const form = $("#settingsForm");
    Object.entries(state.settings).forEach(([key, value]) => {
      const input = form.elements[key];
      if (!input) return;
      if (input.type === "checkbox") input.checked = Boolean(value);
      else input.value = value;
    });
    resetDownloadOptions();
    updateCookieFileHint();
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadCookieBrowsers() {
  const browserInput = $("#cookieBrowserInput");
  if (!browserInput) return;
  const status = $("#cookieFetchStatus");
  try {
    const result = await api("/api/cookies/browsers");
    state.cookieBrowsers = result.browsers || [];
    browserInput.innerHTML = state.cookieBrowsers.map((browser) => (
      `<option value="${escapeHtml(browser.id)}">${escapeHtml(browser.label)}</option>`
    )).join("");
    renderCookieProfiles();
    if (status) status.textContent = state.cookieBrowsers.length
      ? "Choose a browser/profile, then fetch to create a local cookies file."
      : "No supported browser cookie sources were detected.";
  } catch (error) {
    if (status) status.textContent = `Could not inspect browser profiles: ${error.message}`;
  }
}

function renderCookieProfiles() {
  const browserInput = $("#cookieBrowserInput");
  const profileInput = $("#cookieProfileInput");
  const pathInput = $("#cookieProfilePathInput");
  if (!browserInput || !profileInput) return;
  const browser = state.cookieBrowsers.find((item) => item.id === browserInput.value);
  const profiles = browser?.profiles || [];
  profileInput.innerHTML = [
    `<option value="">Default profile</option>`,
    ...profiles.map((profile) => `<option value="${escapeHtml(profile.path)}">${escapeHtml(profile.name)}</option>`),
  ].join("");
  if (pathInput) pathInput.value = "";
}

async function fetchBrowserCookies() {
  const browserInput = $("#cookieBrowserInput");
  const profileInput = $("#cookieProfileInput");
  const pathInput = $("#cookieProfilePathInput");
  const button = $("#cookieFetchButton");
  const status = $("#cookieFetchStatus");
  if (!browserInput || !button) return;
  const profile = (pathInput?.value.trim() || profileInput?.value || "").trim();
  setButtonLoading(button, true, "Fetching cookies…", "cookie");
  if (status) status.textContent = "Reading the selected browser profile and exporting cookies…";
  try {
    const result = await api("/api/cookies/export", {
      method: "POST",
      body: JSON.stringify({ browser: browserInput.value, profile }),
    });
    if (result.settings) {
      state.settings = result.settings;
      const input = $("#settingsCookiesFile");
      if (input) input.value = result.settings.ytdlp_cookies_file || "";
      updateCookieFileHint();
    }
    const cookies = result.cookies || {};
    if (status) status.textContent = `Saved ${cookies.count || 0} cookies to ${cookies.path || "the app cookies file"}.`;
    toast("Browser cookies exported and saved to yt-dlp settings.");
  } catch (error) {
    if (status) status.textContent = error.message || "Cookie export failed. Close the browser, unlock the profile, or choose another profile.";
    toast(error.message, true);
  } finally {
    setButtonLoading(button, false, "Fetch cookies from browser", "cookie");
  }
}

function updateCookieFileHint() {
  const input = $("#settingsCookiesFile");
  const hint = $("#cookiesFileHint");
  if (!input || !hint) return;
  const value = input.value.trim().replaceAll("\\", "/").toLowerCase();
  const looksLikeBrowserDb = value.endsWith("/network/cookies") || value.endsWith("/cookies.sqlite");
  if (looksLikeBrowserDb) {
    hint.textContent = "This is a browser database, not a yt-dlp cookies.txt file. Use Fetch cookies to export a compatible file.";
    hint.classList.add("warning");
  } else {
    hint.textContent = "Use a Netscape cookies.txt file. Browser SQLite databases must be fetched first.";
    hint.classList.remove("warning");
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {};
  Object.keys(state.settings).forEach((key) => {
    const input = form.elements[key];
    if (!input) return;
    if (input.type === "checkbox") payload[key] = input.checked;
    else if (input.type === "number") payload[key] = Number(input.value);
    else payload[key] = input.value;
  });
  try {
    state.settings = await api("/api/settings", { method: "POST", body: JSON.stringify(payload) });
    toast("Settings saved");
    await loadDependencyHealth({ autoInstall: false });
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadDependencyHealth(options = {}) {
  const autoInstall = options.autoInstall !== false;
  const button = $("#dependencyTestButton");
  const installButton = $("#dependencyInstallButton");
  const summary = $("#dependencyHealthSummary");
  const grid = $("#dependencyGrid");
  if (!button || !summary || !grid) return;
  setButtonLoading(button, true, "Testing…", "stethoscope");
  try {
    const health = await api("/api/health");
    state.updatableTools = health.updatable_tools || state.updatableTools || [];
    const entries = Object.entries(health.dependencies || {});
    const missing = entries.filter(([, ok]) => !ok).map(([name]) => name);
    summary.textContent = missing.length
      ? `${missing.length} missing: ${missing.join(", ")}`
      : "All required tools are ready.";
    if (installButton) {
      installButton.title = missing.length
        ? `Download and configure ${missing.join(", ")}`
        : "All tools are already available.";
      installButton.disabled = missing.length === 0;
      installButton.setAttribute("aria-disabled", String(missing.length === 0));
      installButton.dataset.missingCount = String(missing.length);
    }
    const summaryChip = $("#settingsToolSummary");
    if (summaryChip) summaryChip.textContent = missing.length ? `${entries.length - missing.length}/${entries.length} ready` : `${entries.length}/${entries.length} ready`;
    grid.innerHTML = entries.map(([name, ok]) => `
      <span class="dependency-pill ${ok ? "ready" : "missing"}">
        <i class="ti ti-${ok ? "circle-check" : "alert-triangle"}" aria-hidden="true"></i>
        <strong>${escapeHtml(name)}</strong>
        <small>${ok ? "Ready" : "Missing"}</small>
      </span>`).join("");
    renderToolUpdateGrid(health.dependencies || {});
    if (autoInstall && health.portable_lite && missing.length && !state.portableToolInstallAttempted) {
      state.portableToolInstallAttempted = true;
      summary.textContent = `Portable setup needs ${missing.join(", ")}. Starting automatic download…`;
      window.setTimeout(() => installMissingTools({ automatic: true }), 250);
    }
  } catch (error) {
    summary.textContent = "Could not check tool health.";
    const summaryChip = $("#settingsToolSummary");
    if (summaryChip) summaryChip.textContent = "Check failed";
    if (installButton) {
      installButton.disabled = false;
      installButton.setAttribute("aria-disabled", "false");
      installButton.dataset.missingCount = "";
      installButton.title = "Could not verify dependencies. Try downloading missing tools.";
    }
    grid.innerHTML = `<span class="dependency-pill missing"><i class="ti ti-alert-triangle"></i><strong>Health check</strong><small>${escapeHtml(error.message)}</small></span>`;
  } finally {
    setButtonLoading(button, false, "Test tools", "stethoscope");
  }
}

function renderToolUpdateGrid(dependencies = {}) {
  const grid = $("#toolUpdateGrid");
  if (!grid) return;
  const tools = state.updatableTools.length ? state.updatableTools : ["aria2c", "yt-dlp", "ffmpeg", "deno"];
  grid.innerHTML = tools.map((name) => {
    const ok = dependencies[name] !== false;
    return `
      <span class="dependency-pill ${ok ? "ready" : "missing"}">
        <i class="ti ti-${ok ? "refresh" : "alert-triangle"}" aria-hidden="true"></i>
        <strong>${escapeHtml(name)}</strong>
        <small>${ok ? "Can refresh" : "Will install"}</small>
      </span>`;
  }).join("");
}

async function installMissingTools(options = {}) {
  const automatic = Boolean(options.automatic);
  const button = $("#dependencyInstallButton");
  const testButton = $("#dependencyTestButton");
  const summary = $("#dependencyHealthSummary");
  if (!button) return;
  if (button.disabled && button.dataset.missingCount === "0") return;
  let refreshHealth = false;
  setButtonLoading(button, true, "Downloading…", "download");
  if (automatic) setButtonLoading(button, true, "Auto setup…", "download");
  if (testButton) testButton.disabled = true;
  if (summary) summary.textContent = "Downloading and configuring missing tools…";
  if (automatic && summary) summary.textContent = "Portable first-run setup is downloading and configuring missing tools…";
  try {
    const result = await api("/api/tools/install-missing", {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (result.settings) state.settings = result.settings;
    const installed = result.installed || [];
    const failed = result.failed || [];
    if (failed.length) {
      toast(`${failed.length} tool${failed.length === 1 ? "" : "s"} could not be installed. Open Tools for details.`, true);
      const grid = $("#dependencyGrid");
      if (grid) {
        grid.innerHTML = failed.map((item) => `
          <span class="dependency-pill missing">
            <i class="ti ti-alert-triangle" aria-hidden="true"></i>
            <strong>${escapeHtml(item.name)}</strong>
            <small>${escapeHtml(item.message || "Install failed")}</small>
          </span>`).join("");
      }
    } else if (installed.length) {
      toast(`${automatic ? "Portable setup installed" : "Installed"} ${installed.join(", ")}`);
    } else {
      toast("All tools are already ready.");
    }
    refreshHealth = true;
  } catch (error) {
    toast(error.message, true);
    if (summary) summary.textContent = "Tool download failed.";
  } finally {
    setButtonLoading(button, false, "Download missing tools", "download");
    if (testButton) testButton.disabled = false;
    if (refreshHealth) await loadDependencyHealth({ autoInstall: false });
  }
}

async function updateTools() {
  const button = $("#toolUpdateButton");
  const testButton = $("#dependencyTestButton");
  const summary = $("#dependencyHealthSummary");
  if (!button) return;
  setButtonLoading(button, true, "Updating…", "refresh");
  if (testButton) testButton.disabled = true;
  if (summary) summary.textContent = "Refreshing downloadable tools…";
  try {
    const result = await api("/api/tools/update", {
      method: "POST",
      body: JSON.stringify({ tools: state.updatableTools || undefined }),
    });
    if (result.settings) state.settings = result.settings;
    const updated = result.updated || [];
    const failed = result.failed || [];
    if (failed.length) {
      toast(`${failed.length} tool${failed.length === 1 ? "" : "s"} could not be updated.`, true);
      const grid = $("#toolUpdateGrid");
      if (grid) {
        grid.innerHTML = failed.map((item) => `
          <span class="dependency-pill missing">
            <i class="ti ti-alert-triangle" aria-hidden="true"></i>
            <strong>${escapeHtml(item.name)}</strong>
            <small>${escapeHtml(item.message || "Update failed")}</small>
          </span>`).join("");
      }
    } else {
      toast(updated.length ? `Updated ${updated.join(", ")}` : "Tools are already current.");
    }
    await loadDependencyHealth({ autoInstall: false });
  } catch (error) {
    toast(error.message, true);
    if (summary) summary.textContent = "Tool update failed.";
  } finally {
    setButtonLoading(button, false, "Update tools", "refresh");
    if (testButton) testButton.disabled = false;
  }
}

function applySavedTheme() {
  const theme = localStorage.getItem("aio-theme") || "dark";
  document.documentElement.dataset.theme = theme;
  updateThemeIcon();
}

function toggleTheme() {
  document.documentElement.dataset.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("aio-theme", document.documentElement.dataset.theme);
  updateThemeIcon();
}

function updateThemeIcon() {
  const dark = document.documentElement.dataset.theme === "dark";
  $("#themeToggle").innerHTML = `<i class="ti ti-${dark ? "moon" : "sun"}"></i>`;
  $("#themeToggle").setAttribute("aria-label", `Switch to ${dark ? "light" : "dark"} theme`);
}

function sourceIcon(provider, requestedType) {
  if (provider === "spotify" || requestedType === "spotify") return "ti ti-brand-spotify";
  if (provider === "gallery" || requestedType === "gallery") return "ti ti-photo";
  if (provider === "aria2" && (requestedType === "torrent")) return "ti ti-magnet";
  if (provider === "aria2") return "ti ti-file";
  if (requestedType === "audio") return "ti ti-music";
  return "ti ti-brand-youtube";
}

function sourceIconClass(provider, requestedType) {
  if (provider === "spotify" || requestedType === "spotify") return "spotify";
  if (provider === "gallery" || requestedType === "gallery") return "gallery";
  if (provider === "aria2" && requestedType === "torrent") return "torrent";
  if (provider === "yt-dlp") return "video";
  return "";
}

function sourceLabel(job) {
  if (job.provider === "yt-dlp") return job.request.type === "audio" ? "Audio" : "yt-dlp";
  if (job.provider === "aria2") return job.request.type === "torrent" || job.request.url.startsWith("magnet:") ? "aria2 · Torrent" : "aria2 · Direct";
  if (job.provider === "gallery") return "Gallery";
  return job.provider === "pending" ? "Detecting" : job.provider;
}

function emptyState(title, detail) {
  return `<div class="empty-state"><i class="ti ti-download-off"></i><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>`;
}

function loadingState(label) {
  return `<div class="empty-state"><i class="ti ti-loader-2 loading-icon"></i><strong>${escapeHtml(label)}</strong></div>`;
}

function formatBytes(value) {
  let amount = Number(value || 0);
  const units = ["B", "KB", "MB", "GB", "TB"];
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${unit === 0 ? amount.toFixed(0) : amount.toFixed(amount >= 10 ? 1 : 2)} ${units[unit]}`;
}

function formatEta(seconds) {
  if (seconds == null) return "—";
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${String(Math.floor(seconds % 60)).padStart(2, "0")}s`;
}

function formatDuration(seconds) {
  if (!seconds) return "Unknown";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = Math.floor(seconds % 60);
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function clamp(value) { return Math.max(0, Math.min(100, Number(value || 0))); }

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[character]));
}

function toast(message, error = false) {
  const element = document.createElement("div");
  element.className = `toast${error ? " error" : ""}`;
  element.textContent = message;
  $("#toastRegion").append(element);
  window.setTimeout(() => element.remove(), 3600);
}
