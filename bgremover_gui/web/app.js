'use strict';

const TOKEN = document.querySelector('meta[name="bgr-token"]').content;
const CID = Array.from(crypto.getRandomValues(new Uint8Array(8)), b => b.toString(16).padStart(2, '0')).join('');
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  settings: null,
  info: {},
  jobs: new Map(),
  history: new Map(),
  previews: new Map(),
  selected: new Set(),
  view: null,
  search: '',
};

const ICONS = {
  sparkles: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
  settings: '<path d="M4 6h8M16 6h4M4 12h2M10 12h10M4 18h10M18 18h2"/><circle cx="14" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="16" cy="18" r="2"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  power: '<path d="M12 3v9"/><path d="M6.3 6.3a8 8 0 1 0 11.4 0"/>',
  'image-plus': '<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7"/><path d="M16 5h6M19 2v6"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  'folder-open': '<path d="M6 14l1.5-3.5A2 2 0 0 1 9.3 9H20a2 2 0 0 1 1.9 2.5l-1.5 6a2 2 0 0 1-1.9 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.7.9l.8 1.2a2 2 0 0 0 1.7.9H18a2 2 0 0 1 2 2v2"/>',
  clipboard: '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>',
  play: '<path d="M6 4l14 8-14 8z"/>',
  x: '<path d="M18 6L6 18M6 6l12 12"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
  eraser: '<path d="M3 6h18M3 12h10M3 18h6M16 15l5 5M21 15l-5 5"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  trash: '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  external: '<path d="M15 3h6v6M10 14L21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  'chevron-left': '<path d="M15 18l-6-6 6-6"/>',
  'chevron-right': '<path d="M9 18l6-6-6-6"/>',
  chevrons: '<path d="M9 7l-5 5 5 5M15 7l5 5-5 5"/>',
  columns: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M12 3v18"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  crop: '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
  scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.1 15.9M14.5 14.5L20 20M8.1 8.1L12 12"/>',
  alert: '<path d="M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
};

// ── helpers ────────────────────────────────────────────────────────────────
function icon(name) {
  const span = document.createElement('i');
  span.dataset.icon = name;
  span.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  return span;
}

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key in el) el[key] = value;
    else el.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child != null && child !== false) el.append(child);
  }
  return el;
}

async function api(method, path, body) {
  const opts = { method, headers: { 'X-BGR-Token': TOKEN } };
  if (body instanceof Blob) opts.body = body;
  else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch('/api/' + path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText || 'Request failed');
  return data;
}

// The revision changes when a result is edited in place (trim), so cached copies are not reused.
const fileUrl = (id, kind, download) =>
  `/api/file/${id}/${kind}?t=${TOKEN}&v=${state.history.get(id)?.rev || 0}${download ? '&dl=1' : ''}`;

function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

function dayLabel(epoch) {
  const d = new Date(epoch * 1000);
  const start = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(new Date()) - start(d)) / 86400000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  return d.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
}

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const isTextField = el => el && (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && /^(text|search|number)$/.test(el.type)));

function toast(message, kind = 'info') {
  const el = h('div', { class: `toast ${kind}` }, icon(kind === 'error' ? 'alert' : 'check'), message);
  $('#toasts').append(el);
  setTimeout(() => {
    el.classList.add('out');
    setTimeout(() => el.remove(), 300);
  }, kind === 'error' ? 5000 : 2200);
}

function confirmDialog(title, text, okLabel) {
  return new Promise(resolve => {
    $('#confirm-title').textContent = title;
    $('#confirm-text').textContent = text;
    $('#confirm-ok').textContent = okLabel;
    $('#confirm').hidden = false;
    $('#confirm-ok').focus();
    confirmDialog.finish = answer => {
      $('#confirm').hidden = true;
      confirmDialog.finish = null;
      resolve(answer);
    };
  });
}

// ── settings ───────────────────────────────────────────────────────────────
const getSetting = path => {
  const [section, key] = path.split('.');
  return state.settings[section][key];
};

let pendingPatch = {};
let saveTimer = null;
let savedTimer = null;

function setSetting(path, value) {
  const [section, key] = path.split('.');
  if (state.settings[section][key] === value) return;
  state.settings[section][key] = value;
  (pendingPatch[section] ||= {})[key] = value;
  applySettings();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushSettings, 150);
}

async function flushSettings() {
  const patch = pendingPatch;
  pendingPatch = {};
  try {
    const { settings } = await api('PUT', 'settings', patch);
    if (!Object.keys(pendingPatch).length) {
      state.settings = settings;
      applySettings();
    }
    $('#saved-indicator').classList.add('show');
    clearTimeout(savedTimer);
    savedTimer = setTimeout(() => $('#saved-indicator').classList.remove('show'), 1600);
  } catch (e) {
    toast(`Could not save settings: ${e.message}`, 'error');
  }
}

let lastSort = null;

function applySettings() {
  const s = state.settings;
  for (const el of $$('[data-setting]')) {
    const value = getSetting(el.dataset.setting);
    if (el.type === 'radio') el.checked = el.value === String(value);
    else if (el.type === 'checkbox') el.checked = !!value;
    else if (el !== document.activeElement) el.value = value;
  }
  for (const el of $$('[data-value-of]')) el.textContent = getSetting(el.dataset.valueOf);
  for (const el of $$('[data-show-if]')) {
    const [path, want] = el.dataset.showIf.split('=');
    el.hidden = String(getSetting(path)) !== want;
  }

  document.documentElement.dataset.theme = s.appearance.theme;
  document.body.dataset.thumbs = s.appearance.thumbnail_size;
  document.body.dataset.fit = s.appearance.thumbnail_fit;
  $('#viewer-stage').dataset.backdrop = s.appearance.viewer_background;
  $('#suffix-example').textContent = `${s.output.suffix}.${s.output.format}`;
  const dark = s.appearance.theme === 'dark' || (s.appearance.theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  $('#theme-toggle').replaceChildren(icon(dark ? 'sun' : 'moon'));
  $('#theme-toggle').title = dark ? 'Switch to light mode' : 'Switch to dark mode';

  if (lastSort !== s.appearance.history_sort) {
    lastSort = s.appearance.history_sort;
    scheduleHistoryRender();
  }
  applyInfo();
}

function applyInfo() {
  const info = state.info;
  const useGpu = info.cuda && state.settings.processing.device !== 'cpu';
  const gpu = info.gpu_name ? info.gpu_name.replace(/^NVIDIA /, '') : 'GPU';
  $('#device-chip').classList.toggle('ready', !!info.ready);
  $('#device-text').textContent = !info.ready ? 'Starting engine…' : useGpu ? gpu : 'CPU';
  $('#device-chip').title = (!info.ready ? 'Loading PyTorch' : useGpu ? `Running on ${info.gpu_name}` : 'Running on the CPU') +
    (info.ready ? `\nModel in memory: ${info.loaded_model || 'none'}` : '');
  $('#loaded-model').textContent = info.ready ? `In memory now: ${info.loaded_model || 'nothing'}.` : '';
  $('#birefnet-note').textContent = info.birefnet_downloaded === false ? ' (first use downloads 444 MB)' : '';
  $('#device-detail').textContent = !info.ready
    ? 'Detecting hardware…'
    : info.cuda
      ? `Detected ${info.gpu_name} (${Math.round(info.gpu_memory_mb / 1024)} GB). Auto uses it.`
      : 'No supported GPU detected, so processing runs on the CPU.';
  for (const [key, folder] of Object.entries(info.watch_folders || {})) {
    $(`#watch-${key}-path`).textContent = folder;
    $(`#watch-${key}-chip`).title = `Process new images that appear in ${folder} while the app is open`;
  }
  $('#output-link').textContent = info.output_dir || '';
  $('#settings-path').textContent = info.settings_path || '';
  $('#about-text').textContent =
    `Background Remover GUI ${info.version || ''}` +
    (info.torch ? ` · PyTorch ${info.torch}` : '') +
    (info.ready && info.matting === false ? ' · edge refinement unavailable (pymatting not installed)' : '') +
    (info.error ? ` · engine error: ${info.error}` : '');
}

// ── views ──────────────────────────────────────────────────────────────────
function setView(view, persist = true) {
  state.view = view;
  for (const section of $$('.view')) section.hidden = section.id !== `view-${view}`;
  for (const item of $$('.nav-item')) item.classList.toggle('active', item.dataset.view === view);
  $('.main').scrollTop = 0;
  if (view === 'history') {
    renderHistory();
    refreshHistory();
  }
  if (persist) setSetting('appearance.last_view', view);
}

// ── tiles ──────────────────────────────────────────────────────────────────
function buildTile() {
  const img = h('img', { alt: '', loading: 'lazy', hidden: true });
  const placeholder = h('div', { class: 'placeholder' }, icon('image'));
  const stage = h('span');
  const name = h('strong');
  const meta = h('span');
  const actions = h('div', { class: 'tile-actions' });
  const el = h('div', { class: 'tile' },
    h('div', { class: 'thumb' }, placeholder, img, h('div', { class: 'status' }, h('div', { class: 'spinner' }), stage)),
    h('div', { class: 'tile-foot' }, name, meta),
    actions);
  const tile = { el, img, placeholder, stage, name, meta, actions, entryId: null };
  img.addEventListener('error', () => { img.hidden = true; placeholder.hidden = false; });
  img.addEventListener('dragstart', e => startDragOut(e, tile.entryId));
  return tile;
}

function setTileImage(tile, src) {
  if (!src) {
    tile.img.hidden = true;
    tile.placeholder.hidden = false;
    return;
  }
  if (tile.img.getAttribute('src') !== src) tile.img.src = src;
  tile.img.hidden = false;
  tile.placeholder.hidden = true;
}

function actionButton(iconName, title, handler, cls = '') {
  return h('button', {
    class: cls,
    title,
    onclick: e => { e.stopPropagation(); handler(); },
  }, icon(iconName));
}

let internalDrag = false;

function startDragOut(event, entryId) {
  internalDrag = true;
  const entry = entryId && state.history.get(entryId);
  if (!entry) return;
  // Lets Chromium browsers drop the full-resolution file onto the desktop or into other apps.
  const url = location.origin + fileUrl(entry.id, 'output');
  const mime = entry.format === 'webp' ? 'image/webp' : 'image/png';
  event.dataTransfer.setData('DownloadURL', `${mime}:${entry.output_name}:${url}`);
  event.dataTransfer.setData('text/uri-list', url);
}

// ── result actions ─────────────────────────────────────────────────────────
async function copyEntry(id) {
  try {
    if (!window.ClipboardItem) throw new Error('this browser cannot copy images');
    const blob = fetch(fileUrl(id, 'png')).then(res => {
      if (!res.ok) throw new Error('the file no longer exists');
      return res.blob();
    });
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
    toast('Image copied to clipboard');
  } catch (e) {
    toast(`Copy failed: ${e.message}`, 'error');
  }
}

function downloadUrl(url) {
  const a = h('a', { href: url, download: '' });
  document.body.append(a);
  a.click();
  a.remove();
}

const downloadEntry = id => downloadUrl(fileUrl(id, 'output', true));

function downloadZip(ids) {
  if (!ids.length) return;
  if (ids.length === 1) return downloadEntry(ids[0]);
  if (ids.length > 1500) return toast('Select at most 1500 images per .zip', 'error');
  downloadUrl(`/api/zip?t=${TOKEN}&ids=${ids.join(',')}`);
}

async function revealEntry(id) {
  try { await api('POST', 'reveal', { id }); } catch (e) { toast(e.message, 'error'); }
}

async function reprocessEntry(id) {
  try {
    await api('POST', 'reprocess', { id });
    toast(state.view === 'workspace' ? 'Re-processing with the current settings' : 'Re-processing; the new result will appear in the Workspace');
    return true;
  } catch (e) {
    toast(e.message, 'error');
    return false;
  }
}

async function trimEntry(id) {
  try {
    const { entry } = await api('POST', 'trim', { id });
    updateHistory(entry);
    toast(`Trimmed to ${entry.width} × ${entry.height}`);
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function deleteEntries(ids) {
  if (!ids.length) return false;
  const what = ids.length === 1 ? (state.history.get(ids[0])?.output_name || 'this image') : plural(ids.length, 'image');
  const ok = await confirmDialog(
    ids.length === 1 ? 'Delete this result?' : `Delete ${plural(ids.length, 'result')}?`,
    `${what} will be moved to the Recycle Bin and removed from the history.`,
    'Delete');
  if (!ok) return false;
  try {
    const { removed, errors } = await api('POST', 'history/delete', { ids });
    removeHistory(removed);
    if (errors.length) toast(`Could not delete: ${errors[0]}`, 'error');
    else toast(`Deleted ${plural(removed.length, 'image')}`);
    return true;
  } catch (e) {
    toast(e.message, 'error');
    return false;
  }
}

// ── workspace: adding files ────────────────────────────────────────────────
const MIME_EXT = { 'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif', 'image/bmp': '.bmp', 'image/avif': '.avif', 'image/heic': '.heic', 'image/tiff': '.tif' };

function normaliseFile(file) {
  const extensions = state.info.extensions || [];
  const ext = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase();
  if (extensions.includes(ext)) return file;
  const fromMime = MIME_EXT[file.type];
  return fromMime ? new File([file], (file.name || 'image') + fromMime, { type: file.type }) : null;
}

async function addFiles(files) {
  const accepted = files.map(normaliseFile).filter(Boolean);
  const skipped = files.length - accepted.length;
  if (skipped) toast(`Skipped ${plural(skipped, 'file')} that ${skipped === 1 ? 'is not a supported image' : 'are not supported images'}`, 'error');
  if (!accepted.length) return;
  if (state.view !== 'workspace') setView('workspace');

  const start = state.settings.processing.auto_start ? '&start=1' : '';
  const pending = [...accepted];
  const failures = [];
  const worker = async () => {
    for (let file = pending.shift(); file; file = pending.shift()) {
      try {
        const { job } = await api('POST', `upload?name=${encodeURIComponent(file.name)}${start}`, file);
        state.previews.set(job.id, URL.createObjectURL(file));
        upsertJob(state.jobs.get(job.id) || job);
      } catch (e) {
        failures.push(`${file.name}: ${e.message}`);
      }
    }
  };
  await Promise.all([worker(), worker(), worker()]);
  if (failures.length) toast(failures.length === 1 ? failures[0] : `${failures.length} files could not be added. ${failures[0]}`, 'error');
}

function readEntries(reader) {
  return new Promise((resolve, reject) => reader.readEntries(resolve, reject));
}

async function walkEntry(entry, out) {
  if (entry.isFile) {
    out.push(await new Promise((resolve, reject) => entry.file(resolve, reject)));
  } else if (entry.isDirectory) {
    const reader = entry.createReader();
    for (let batch = await readEntries(reader); batch.length; batch = await readEntries(reader)) {
      for (const child of batch) await walkEntry(child, out);
    }
  }
}

async function filesFromDrop(dataTransfer) {
  // Entries must be captured synchronously, before the drop event finishes.
  const plain = [...dataTransfer.files];
  const entries = [...dataTransfer.items]
    .filter(item => item.kind === 'file' && item.webkitGetAsEntry)
    .map(item => item.webkitGetAsEntry())
    .filter(Boolean);
  if (!entries.some(entry => entry.isDirectory)) return plain;
  const out = [];
  for (const entry of entries) {
    try { await walkEntry(entry, out); } catch (e) { /* unreadable folder: skip */ }
  }
  return out;
}

function pastedName(file, index = 0) {
  if (file.name && file.name !== 'image.png') return file;
  const now = new Date();
  const two = n => String(n).padStart(2, '0');
  const stamp = `${now.getFullYear()}${two(now.getMonth() + 1)}${two(now.getDate())}-${two(now.getHours())}${two(now.getMinutes())}${two(now.getSeconds())}`;
  const ext = MIME_EXT[file.type] || '.png';
  return new File([file], `pasted-${stamp}${index ? '-' + index : ''}${ext}`, { type: file.type });
}

async function pasteFromButton() {
  try {
    const files = [];
    for (const item of await navigator.clipboard.read()) {
      const type = item.types.find(t => t.startsWith('image/'));
      if (type) files.push(pastedName(new File([await item.getType(type)], 'image.png', { type }), files.length));
    }
    if (files.length) addFiles(files);
    else toast('The clipboard does not contain an image', 'error');
  } catch (e) {
    toast('Clipboard access was blocked. Press Ctrl + V instead.', 'error');
  }
}

// ── workspace: queue ───────────────────────────────────────────────────────
const jobTiles = new Map();

function dropPreview(id) {
  const url = state.previews.get(id);
  if (url) {
    URL.revokeObjectURL(url);
    state.previews.delete(id);
  }
}

function doneIds() {
  return [...state.jobs.values()].filter(j => j.status === 'done' && state.history.has(j.history_id)).map(j => j.history_id);
}

function upsertJob(job) {
  state.jobs.set(job.id, job);
  let tile = jobTiles.get(job.id);
  if (!tile) {
    tile = buildTile();
    const current = () => state.jobs.get(job.id);
    tile.reprocess = actionButton('refresh', 'Re-process with the current settings', () => reprocessEntry(current().history_id), 'needs-result');
    tile.trim = actionButton('crop', 'Trim empty space', () => trimEntry(current().history_id), 'needs-result');
    tile.actions.append(
      actionButton('copy', 'Copy image', () => copyEntry(current().history_id), 'needs-result'),
      actionButton('download', 'Download', () => downloadEntry(current().history_id), 'needs-result'),
      actionButton('external', 'Show in folder', () => revealEntry(current().history_id), 'needs-result'),
      tile.reprocess,
      tile.trim,
      actionButton('x', 'Remove from this list', () => api('POST', 'jobs/remove', { ids: [job.id] }).catch(e => toast(e.message, 'error'))));
    tile.el.addEventListener('click', () => {
      const j = current();
      if (j.status === 'done' && state.history.has(j.history_id)) openViewer(doneIds(), j.history_id);
    });
    jobTiles.set(job.id, tile);
    $('#job-grid').append(tile.el);
  }
  updateJobTile(tile, job);
  renderQueueBar();
}

function updateJobTile(tile, job) {
  const entry = job.status === 'done' ? state.history.get(job.history_id) : null;
  tile.el.dataset.status = job.status;
  tile.el.classList.toggle('clickable', !!entry);
  tile.entryId = entry ? entry.id : null;
  tile.img.draggable = !!entry;
  tile.name.textContent = entry ? entry.output_name : job.name;
  tile.name.title = tile.name.textContent;
  if (entry) {
    dropPreview(job.id);
    tile.reprocess.hidden = !entry.has_original;
    tile.trim.hidden = entry.mode === 'color';
    setTileImage(tile, fileUrl(entry.id, 'thumb'));
    tile.meta.textContent = `${entry.width} × ${entry.height} · ${fmtBytes(entry.bytes)} · ${entry.seconds}s`;
    return;
  }
  setTileImage(tile, state.previews.get(job.id));
  const labels = { pending: 'Ready to start', queued: 'Waiting…', processing: job.stage || 'Processing…', error: job.error || 'Failed', done: 'File was removed' };
  tile.stage.textContent = labels[job.status];
  tile.stage.title = job.status === 'error' ? job.error : '';
  tile.meta.textContent = { pending: 'Ready', queued: 'In queue', processing: 'Processing', error: 'Failed', done: 'File was removed' }[job.status];
}

function setJobs(list) {
  const keep = new Set(list.map(j => j.id));
  for (const [id, tile] of jobTiles) {
    if (keep.has(id)) continue;
    tile.el.remove();
    jobTiles.delete(id);
    state.jobs.delete(id);
    dropPreview(id);
  }
  list.forEach(upsertJob);
  renderQueueBar();
}

function renderQueueBar() {
  const jobs = [...state.jobs.values()];
  const count = status => jobs.filter(j => j.status === status).length;
  const total = jobs.length;
  const done = count('done');
  const failed = count('error');
  const pending = count('pending');
  const running = count('queued') + count('processing');
  const finished = done + failed;

  $('#queue-bar').hidden = total === 0;
  $('#dropzone').classList.toggle('compact', total > 0);
  $('#queue-title').textContent = running
    ? `Processing ${Math.min(finished + 1, total)} of ${total}`
    : pending
      ? `${plural(pending, 'image')} ready to start`
      : `Finished ${plural(done, 'image')}`;
  $('#queue-sub').textContent = failed ? `${failed} failed` : '';
  $('#queue-fill').style.width = total ? `${(finished / total) * 100}%` : '0';
  $('#start-btn').hidden = pending === 0;
  $('#cancel-btn').hidden = pending + count('queued') === 0;
  $('#zip-btn').hidden = doneIds().length < 2;
  $('#clear-btn').hidden = finished === 0;

  const active = pending + running;
  $('#badge-queue').hidden = active === 0;
  $('#badge-queue').textContent = active;
  document.title = running ? `(${finished}/${total}) Background Remover` : 'Background Remover';
}

// ── history ────────────────────────────────────────────────────────────────
const historyTiles = new Map();
let historyOrder = [];
let lastChecked = null;
let historyTimer = null;

function scheduleHistoryRender() {
  clearTimeout(historyTimer);
  historyTimer = setTimeout(renderHistory, 80);
}

function addHistory(entry) {
  state.history.set(entry.id, entry);
  for (const job of state.jobs.values()) {
    if (job.history_id === entry.id) upsertJob(job);
  }
  updateHistoryBadge();
  scheduleHistoryRender();
}

function updateHistory(entry) {
  if (!state.history.has(entry.id)) return;
  state.history.set(entry.id, entry);
  for (const job of state.jobs.values()) {
    if (job.history_id === entry.id) upsertJob(job);
  }
  scheduleHistoryRender();
  if (!$('#viewer').hidden && currentEntry()?.id === entry.id) renderViewer();
}

function removeHistory(ids) {
  if (!ids.length) return;
  for (const id of ids) {
    state.history.delete(id);
    state.selected.delete(id);
  }
  for (const job of state.jobs.values()) {
    if (ids.includes(job.history_id)) upsertJob(job);
  }
  updateHistoryBadge();
  renderHistory();
  if (!$('#viewer').hidden) {
    viewer.ids = viewer.ids.filter(id => state.history.has(id));
    if (!viewer.ids.length) closeViewer();
    else {
      viewer.index = Math.min(viewer.index, viewer.ids.length - 1);
      renderViewer();
    }
  }
}

function updateHistoryBadge() {
  $('#badge-history').hidden = state.history.size === 0;
  $('#badge-history').textContent = state.history.size;
}

async function refreshHistory() {
  try {
    const { history } = await api('GET', 'history');
    const live = new Set(history.map(e => e.id));
    const gone = [...state.history.keys()].filter(id => !live.has(id));
    for (const entry of history) state.history.set(entry.id, entry);
    if (gone.length) removeHistory(gone);
    else scheduleHistoryRender();
    updateHistoryBadge();
  } catch (e) { /* offline overlay handles a dead server */ }
}

function filteredHistory() {
  const term = state.search.trim().toLowerCase();
  let list = [...state.history.values()];
  if (term) list = list.filter(e => e.output_name.toLowerCase().includes(term) || e.name.toLowerCase().includes(term));
  const sort = state.settings.appearance.history_sort;
  if (sort === 'name') list.sort((a, b) => a.output_name.localeCompare(b.output_name, undefined, { numeric: true }));
  else if (sort === 'largest') list.sort((a, b) => b.bytes - a.bytes);
  else if (sort === 'oldest') list.sort((a, b) => a.created - b.created);
  else list.sort((a, b) => b.created - a.created);
  return list;
}

function toggleSelected(id, event) {
  if (event && event.shiftKey && lastChecked && historyOrder.includes(lastChecked)) {
    const [from, to] = [historyOrder.indexOf(lastChecked), historyOrder.indexOf(id)].sort((a, b) => a - b);
    for (const other of historyOrder.slice(from, to + 1)) state.selected.add(other);
  } else if (state.selected.has(id)) state.selected.delete(id);
  else state.selected.add(id);
  lastChecked = id;
  updateSelection();
}

function updateSelection() {
  for (const [id, tile] of historyTiles) tile.el.classList.toggle('selected', state.selected.has(id));
  const n = state.selected.size;
  $('#select-bar').hidden = n === 0;
  $('#select-count').textContent = `${n} selected`;
  $('#history-body').classList.toggle('selecting', n > 0);
}

function historyTile(entry) {
  const tile = buildTile();
  tile.entryId = entry.id;
  tile.el.dataset.status = 'done';
  tile.el.classList.add('clickable');
  tile.name.textContent = entry.output_name;
  tile.name.title = entry.output_name;
  tile.meta.textContent = `${entry.width} × ${entry.height} · ${fmtBytes(entry.bytes)}`;
  setTileImage(tile, fileUrl(entry.id, 'thumb'));
  tile.actions.append(...[
    actionButton('copy', 'Copy image', () => copyEntry(entry.id)),
    actionButton('download', 'Download', () => downloadEntry(entry.id)),
    actionButton('external', 'Show in folder', () => revealEntry(entry.id)),
    entry.has_original && actionButton('refresh', 'Re-process with the current settings', () => reprocessEntry(entry.id)),
    entry.mode !== 'color' && actionButton('crop', 'Trim empty space', () => trimEntry(entry.id)),
    actionButton('trash', 'Delete', () => deleteEntries([entry.id]), 'danger'),
  ].filter(Boolean));
  tile.el.append(h('div', {
    class: 'check',
    title: 'Select',
    onclick: e => { e.stopPropagation(); toggleSelected(entry.id, e); },
  }, icon('check')));
  tile.el.addEventListener('click', e => {
    if (state.selected.size || e.ctrlKey || e.metaKey || e.shiftKey) toggleSelected(entry.id, e);
    else openViewer(historyOrder, entry.id);
  });
  return tile;
}

function renderHistory() {
  if (state.view !== 'history') return;
  const all = state.history.size;
  const list = filteredHistory();
  const bytes = [...state.history.values()].reduce((sum, e) => sum + e.bytes, 0);
  $('#history-summary').textContent = all
    ? `${plural(all, 'image')} · ${fmtBytes(bytes)} on disk` + (list.length !== all ? ` · ${list.length} shown` : '')
    : 'Processed images that still exist on disk appear here.';

  historyTiles.clear();
  historyOrder = list.map(e => e.id);
  const body = $('#history-body');
  if (!list.length) {
    body.replaceChildren(h('div', { class: 'empty' }, icon(all ? 'search' : 'history'),
      h('strong', {}, all ? 'No matches' : 'Nothing here yet'),
      h('span', {}, all ? 'Try a different search.' : 'Results show up here after you process images. Files you delete or move from the output folder drop off the list.')));
    updateSelection();
    return;
  }

  const fragment = document.createDocumentFragment();
  const grouped = ['newest', 'oldest'].includes(state.settings.appearance.history_sort);
  let grid = null;
  let label = null;
  for (const entry of list) {
    const day = grouped ? dayLabel(entry.created) : '';
    if (!grid || day !== label) {
      label = day;
      if (grouped) fragment.append(h('div', { class: 'group-title' }, day));
      grid = h('div', { class: 'grid' });
      fragment.append(grid);
    }
    const tile = historyTile(entry);
    historyTiles.set(entry.id, tile);
    grid.append(tile.el);
  }
  body.replaceChildren(fragment);
  updateSelection();
}

// ── viewer ─────────────────────────────────────────────────────────────────
const viewer = { ids: [], index: 0, compare: true };

function openViewer(ids, id) {
  viewer.ids = [...ids];
  viewer.index = Math.max(0, viewer.ids.indexOf(id));
  $('#viewer').hidden = false;
  renderViewer();
}

function closeViewer() {
  $('#viewer').hidden = true;
  $('#viewer-result').removeAttribute('src');
  $('#viewer-original').removeAttribute('src');
}

const currentEntry = () => state.history.get(viewer.ids[viewer.index]);

function fitViewer() {
  const entry = currentEntry();
  if (!entry || $('#viewer').hidden) return;
  const stage = $('#viewer-stage');
  const availW = Math.max(80, stage.clientWidth - 128);
  const availH = Math.max(80, stage.clientHeight - 100);
  const fit = Math.min(availW / entry.width, availH / entry.height);
  const scale = Math.min(fit, Math.max(1, 360 / Math.max(entry.width, entry.height)));
  const frame = $('#viewer-frame');
  frame.style.width = `${Math.round(entry.width * scale)}px`;
  frame.style.height = `${Math.round(entry.height * scale)}px`;
}

function renderViewer() {
  const entry = currentEntry();
  if (!entry) return closeViewer();
  const comparing = viewer.compare && entry.has_original;
  const frame = $('#viewer-frame');
  frame.classList.toggle('comparing', comparing);
  frame.style.setProperty('--pos', '50%');
  $('#viewer-result').src = fileUrl(entry.id, 'output');
  $('#viewer-result').draggable = !comparing;
  const original = $('#viewer-original');
  if (entry.has_original) original.src = fileUrl(entry.id, 'original');
  else original.removeAttribute('src');
  // A trimmed result covers only part of its original: line the original up behind it.
  const [sourceW, sourceH] = entry.source_size || [entry.width, entry.height];
  const [left, top, right, bottom] = entry.crop || [0, 0, sourceW, sourceH];
  original.style.width = `${(sourceW / (right - left)) * 100}%`;
  original.style.height = `${(sourceH / (bottom - top)) * 100}%`;
  original.style.left = `${(-left / (right - left)) * 100}%`;
  original.style.top = `${(-top / (bottom - top)) * 100}%`;
  fitViewer();

  $('#viewer-compare').hidden = !entry.has_original;
  $('#viewer-compare').classList.toggle('active', comparing);
  $('#viewer-reprocess').hidden = !entry.has_original;
  $('#viewer-trim').hidden = entry.mode === 'color';
  $('#viewer-prev').hidden = $('#viewer-next').hidden = viewer.ids.length < 2;
  $('#viewer-counter').textContent = `${viewer.index + 1} / ${viewer.ids.length}`;
  $('#viewer-name').textContent = entry.output_name;

  const modelNames = { u2net: 'General (u2net)', u2netp: 'Lightweight (u2netp)', u2net_human_seg: 'People (u2net_human_seg)', birefnet: 'High detail (BiRefNet)' };
  const modeNames = { transparent: 'Transparent', color: 'Solid color', mask: 'Mask only' };
  const rows = [
    ['Dimensions', `${entry.width} × ${entry.height}`],
    ['File size', fmtBytes(entry.bytes)],
    ['Format', entry.format.toUpperCase()],
    ['Model', modelNames[entry.model] || entry.model],
    ['Background', modeNames[entry.mode] || entry.mode],
    ['Edges refined', entry.alpha_matting ? 'Yes' : 'No'],
    ['Processed in', `${entry.seconds}s on ${entry.device === 'cuda' ? 'GPU' : 'CPU'}${entry.precision ? `, ${entry.precision} precision` : ''}`],
    ['Created', new Date(entry.created * 1000).toLocaleString()],
    ['Source', entry.name],
    ['Saved to', entry.output_path],
  ];
  $('#viewer-details').replaceChildren(...rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]));
}

function stepViewer(delta) {
  if (viewer.ids.length < 2) return;
  viewer.index = (viewer.index + delta + viewer.ids.length) % viewer.ids.length;
  renderViewer();
}

function bindViewer() {
  const frame = $('#viewer-frame');
  const move = e => {
    const rect = frame.getBoundingClientRect();
    const pos = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    frame.style.setProperty('--pos', `${pos * 100}%`);
  };
  frame.addEventListener('pointerdown', e => {
    if (!frame.classList.contains('comparing')) return;
    frame.setPointerCapture(e.pointerId);
    move(e);
    frame.addEventListener('pointermove', move);
  });
  const release = () => frame.removeEventListener('pointermove', move);
  frame.addEventListener('pointerup', release);
  frame.addEventListener('pointercancel', release);

  $('#viewer-result').addEventListener('dragstart', e => startDragOut(e, currentEntry()?.id));
  $('#viewer').addEventListener('click', e => { if (e.target === $('#viewer')) closeViewer(); });
  $('#viewer-close').onclick = closeViewer;
  $('#viewer-prev').onclick = () => stepViewer(-1);
  $('#viewer-next').onclick = () => stepViewer(1);
  $('#viewer-compare').onclick = () => { viewer.compare = !viewer.compare; renderViewer(); };
  $('#viewer-copy').onclick = () => copyEntry(currentEntry().id);
  $('#viewer-download').onclick = () => downloadEntry(currentEntry().id);
  $('#viewer-reveal').onclick = () => revealEntry(currentEntry().id);
  $('#viewer-delete').onclick = () => deleteEntries([currentEntry().id]);
  $('#viewer-trim').onclick = () => trimEntry(currentEntry().id);
  $('#viewer-reprocess').onclick = async () => {
    if (!(await reprocessEntry(currentEntry().id))) return;
    closeViewer();
    setView('workspace');
  };
  window.addEventListener('resize', fitViewer);
}

// ── server connection ──────────────────────────────────────────────────────
let offlineTimer = null;
let pingTimer = null;

function setOffline(offline) {
  $('#offline').hidden = !offline;
  clearInterval(pingTimer);
  if (!offline) return;
  // A relaunch issues a new session token, so a full reload is needed to pick it up.
  pingTimer = setInterval(async () => {
    try {
      if ((await fetch('/api/ping', { cache: 'no-store' })).ok) location.reload();
    } catch (e) { /* still down */ }
  }, 2000);
}

function connect() {
  const source = new EventSource(`/api/events?t=${TOKEN}&cid=${CID}`);
  let wasDown = false;
  source.onopen = async () => {
    clearTimeout(offlineTimer);
    offlineTimer = null;
    setOffline(false);
    if (wasDown) {
      wasDown = false;
      try { adoptState(await api('GET', 'state')); } catch (e) { /* retried on next open */ }
    }
  };
  source.onerror = () => {
    wasDown = true;
    if (!offlineTimer) offlineTimer = setTimeout(() => setOffline(true), 3500);
  };
  const on = (name, fn) => source.addEventListener(name, e => fn(JSON.parse(e.data)));
  on('job', upsertJob);
  on('jobs', setJobs);
  on('history_add', addHistory);
  on('history_update', updateHistory);
  on('history_remove', removeHistory);
  on('info', info => { state.info = info; applyInfo(); });
  on('settings', settings => {
    if (Object.keys(pendingPatch).length) return;
    state.settings = settings;
    applySettings();
  });
  window.addEventListener('pagehide', () => navigator.sendBeacon(`/api/bye?t=${TOKEN}&cid=${CID}`));
}

function adoptState(data) {
  state.settings = data.settings;
  state.info = data.info;
  state.history = new Map(data.history.map(e => [e.id, e]));
  applySettings();
  setJobs(data.jobs);
  updateHistoryBadge();
  scheduleHistoryRender();
}

// ── wiring ─────────────────────────────────────────────────────────────────
function bindSettings() {
  document.addEventListener('change', e => {
    const el = e.target;
    if (!el.dataset || !el.dataset.setting) return;
    let value;
    if (el.type === 'checkbox') value = el.checked;
    else if (el.type === 'radio') { if (!el.checked) return; value = el.value; }
    else if (el.type === 'number' || el.type === 'range' || el.dataset.type === 'int') {
      value = parseInt(el.value, 10);
      if (Number.isNaN(value)) return applySettings();
    } else value = el.value.trim();
    setSetting(el.dataset.setting, value);
    const watched = el.dataset.setting.match(/^watch\.(\w+)$/);
    if (watched && value) toast(`Watching ${(state.info.watch_folders || {})[watched[1]] || 'the folder'} for new images`);
  });
  document.addEventListener('input', e => {
    const el = e.target;
    if (el.type !== 'range' || !el.dataset.setting) return;
    for (const out of $$(`[data-value-of="${el.dataset.setting}"]`)) out.textContent = el.value;
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applySettings);

  $('#theme-toggle').onclick = () => {
    const theme = state.settings.appearance.theme;
    const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
    setSetting('appearance.theme', dark ? 'light' : 'dark');
  };
  $('#pick-folder').onclick = async e => {
    const button = e.currentTarget;
    button.disabled = true;
    try {
      const { path } = await api('POST', 'pick-folder');
      if (path) setSetting('output.directory', path);
    } catch (err) {
      toast(err.message, 'error');
    }
    button.disabled = false;
  };
  const openOutput = e => {
    e.preventDefault();
    api('POST', 'open-output').catch(err => toast(err.message, 'error'));
  };
  $('#open-folder').onclick = openOutput;
  $('#output-link').onclick = openOutput;
}

function bindWorkspace() {
  const dropzone = $('#dropzone');
  const fileInput = $('#file-input');
  const folderInput = $('#folder-input');
  dropzone.addEventListener('click', e => { if (!e.target.closest('button')) fileInput.click(); });
  dropzone.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target === dropzone) { e.preventDefault(); fileInput.click(); }
  });
  $('#browse-files').onclick = () => fileInput.click();
  $('#browse-folder').onclick = () => folderInput.click();
  $('#paste-btn').onclick = pasteFromButton;
  for (const input of [fileInput, folderInput]) {
    input.addEventListener('change', () => {
      addFiles([...input.files]);
      input.value = '';
    });
  }

  $('#start-btn').onclick = () => api('POST', 'start', {}).catch(e => toast(e.message, 'error'));
  $('#cancel-btn').onclick = () => api('POST', 'jobs/remove', { scope: 'waiting' }).catch(e => toast(e.message, 'error'));
  $('#clear-btn').onclick = () => api('POST', 'jobs/remove', { scope: 'finished' }).catch(e => toast(e.message, 'error'));
  $('#zip-btn').onclick = () => downloadZip(doneIds());

  // Drag & drop anywhere in the window.
  let depth = 0;
  const hasFiles = e => !internalDrag && e.dataTransfer && [...e.dataTransfer.types].includes('Files');
  const overlay = $('#drop-overlay');
  window.addEventListener('dragend', () => { internalDrag = false; });
  window.addEventListener('dragenter', e => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth += 1;
    overlay.hidden = false;
  });
  window.addEventListener('dragover', e => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });
  window.addEventListener('dragleave', e => {
    if (!hasFiles(e)) return;
    depth = Math.max(0, depth - 1);
    if (!depth) overlay.hidden = true;
  });
  window.addEventListener('drop', async e => {
    e.preventDefault();
    depth = 0;
    overlay.hidden = true;
    if (internalDrag) { internalDrag = false; return; }
    if (!e.dataTransfer || ![...e.dataTransfer.types].includes('Files')) return;
    addFiles(await filesFromDrop(e.dataTransfer));
  });

  document.addEventListener('paste', e => {
    if (isTextField(e.target)) return;
    const files = [...(e.clipboardData ? e.clipboardData.files : [])];
    if (!files.length) return toast('The clipboard does not contain an image', 'error');
    e.preventDefault();
    addFiles(files.map((f, i) => pastedName(f, i)));
  });
}

function bindHistory() {
  $('#history-search').addEventListener('input', e => {
    state.search = e.target.value;
    scheduleHistoryRender();
  });
  $('#history-refresh').onclick = async () => {
    await refreshHistory();
    toast('History is up to date');
  };
  $('#select-all').onclick = () => { historyOrder.forEach(id => state.selected.add(id)); updateSelection(); };
  $('#select-none').onclick = () => { state.selected.clear(); updateSelection(); };
  $('#select-zip').onclick = () => downloadZip([...state.selected]);
  $('#select-delete').onclick = () => deleteEntries([...state.selected]);
}

function bindGlobal() {
  for (const item of $$('.nav-item')) item.onclick = () => setView(item.dataset.view);
  $('#confirm-ok').onclick = () => confirmDialog.finish && confirmDialog.finish(true);
  $('#confirm-cancel').onclick = () => confirmDialog.finish && confirmDialog.finish(false);
  $('#offline-reload').onclick = () => location.reload();
  $('#quit-btn').onclick = async () => {
    const busy = [...state.jobs.values()].some(j => j.status === 'queued' || j.status === 'processing');
    if (busy && !(await confirmDialog('Quit while processing?', 'Images that are still waiting will not be processed.', 'Quit'))) return;
    try { await api('POST', 'quit', {}); } catch (e) { /* already gone */ }
    setOffline(true);
    window.close();
  };

  document.addEventListener('keydown', e => {
    if (confirmDialog.finish) {
      if (e.key === 'Escape') confirmDialog.finish(false);
      return;
    }
    if ($('#viewer').hidden) {
      if (e.key === 'Escape' && state.selected.size) { state.selected.clear(); updateSelection(); }
      return;
    }
    if (e.key === 'Escape') closeViewer();
    else if (e.key === 'ArrowLeft') stepViewer(-1);
    else if (e.key === 'ArrowRight') stepViewer(1);
    else if (e.key === 'Delete') deleteEntries([currentEntry().id]);
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c' && !String(getSelection())) {
      e.preventDefault();
      copyEntry(currentEntry().id);
    }
  });
}

async function init() {
  for (const el of $$('i[data-icon]')) el.replaceWith(icon(el.dataset.icon));
  bindGlobal();
  bindSettings();
  bindWorkspace();
  bindHistory();
  bindViewer();
  try {
    const data = await api('GET', 'state');
    adoptState(data);
    setView(data.settings.appearance.last_view, false);
    connect();
  } catch (e) {
    setOffline(true);
  }
}

init();
