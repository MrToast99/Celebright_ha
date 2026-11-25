/**
 * Celebright Card
 *
 * Controls a Celebright permanent-lighting controller from a dashboard: power,
 * brightness and colour, saved scenes, and the schedule (view, switch on and off,
 * add, edit and delete events).
 *
 * Usage:
 *   type: custom:celebright-card
 *   device: <device id>        # optional with one controller (pick it in the editor)
 *   title: House               # optional, defaults to the controller's name
 *   show_controls: true        # optional, power, brightness and colour
 *   show_scenes: true          # optional
 *   show_schedule: true        # optional
 *   show_info: true            # optional, model, firmware and so on (collapsed)
 *
 * The integration serves this file and adds it to Lovelace's resources itself.
 * The card asks the integration (celebright/card_info) which entities, scenes and
 * events each controller has, then reads live state from Home Assistant.
 */

const CARD_VERSION = "1.9.6";

const EN = {
  loading: "Loading…",
  notReady: "The Celebright integration isn't loaded.",
  noDevice: "No Celebright controller found.",
  offline: "Offline",
  online: "Online",
  power: "Power",
  brightness: "Brightness",
  color: "Colour",
  customColor: "Pick a colour",
  scenes: "Scenes",
  searchScenes: "Search scenes",
  noScenes: "No saved scenes. Create some in the Celebright app, then refresh.",
  noMatch: "No scene matches.",
  resume: "Resume schedule",
  refresh: "Refresh scenes",
  schedule: "Schedule",
  scheduleOn: "Schedule on",
  scheduleOff: "Schedule off",
  activeNow: "Playing now",
  nextStart: "Next event",
  none: "None",
  unknown: "Unknown",
  events: "Events",
  noEvents: "No events scheduled.",
  addEvent: "Add event",
  editEvent: "Edit event",
  newEvent: "New event",
  edit: "Edit",
  remove: "Delete",
  save: "Save",
  cancel: "Cancel",
  working: "Saving…",
  confirmDelete: "Delete this event?",
  confirmDeleteBody: "It is removed from the controller and can't be undone.",
  name: "Name",
  scene: "Scene",
  chooseScene: "Choose a scene",
  priority: "Priority",
  priorities: { 1: "Lowest", 2: "Low", 3: "High", 4: "Highest" },
  starts: "Starts",
  ends: "Ends",
  sunset: "Sunset",
  midnight: "Midnight",
  sunrise: "Sunrise",
  atTime: "At a time",
  offset: "Minutes after sunset or sunrise; negative is before.",
  minutes: "min",
  firstNight: "First night",
  repeat: "Repeats",
  once: "Once",
  daily: "Every day",
  yearlyDate: "Every year, same date",
  yearlyWeekday: "Every year, same weekday",
  until: "Stop after (optional)",
  enabled: "Enabled",
  needName: "Give the event a name.",
  needScene: "Choose a scene.",
  sceneOrPlaylist: "Scene or playlist",
  chooseSceneOrPlaylist: "Choose a scene or playlist",
  scenesGroup: "Scenes",
  playlistsGroup: "Playlists",
  playlistPrefix: "Playlist",
  evSeconds: "Time per scene (s)",
  evShuffle: "Shuffle",
  evOnce: "Once per event",
  needDate: "Choose a date.",
  info: "Controller details",
  model: "Model",
  firmware: "Firmware",
  hardware: "Hardware",
  leds: "LEDs",
  bulb: "Bulb type",
  order: "Colour order",
  location: "Location",
  source: { user_display: "Manual", off: "Off", event: "Scheduled event", schedule: "Schedule" },
  today: "Today",
  tomorrow: "Tomorrow",
  weekdays: { MO: "Monday", TU: "Tuesday", WE: "Wednesday", TH: "Thursday", FR: "Friday", SA: "Saturday", SU: "Sunday" },
};

const SWATCHES = [
  ["#FFFFFF", "White"], ["#FFB347", "Warm"], ["#FF2D2D", "Red"], ["#FF7A00", "Orange"],
  ["#FFD60A", "Yellow"], ["#30D158", "Green"], ["#00C7BE", "Teal"], ["#0A84FF", "Blue"],
  ["#7D3CFF", "Purple"], ["#FF4FA3", "Pink"],
];
const PRIORITY_COLOR = { 1: "#8e8e93", 2: "#0a84ff", 3: "#ff9f0a", 4: "#ff453a" };
const DAYS = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const t = (key) => EN[key] ?? key;
const hex2 = (n) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, "0");
const rgbToHex = (rgb) => `#${hex2(rgb[0])}${hex2(rgb[1])}${hex2(rgb[2])}`;
const hexToRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

// The scene's colours as a strip: solid, pattern palette (smooth or in bands) or a row of bulbs.
// The integration sends `preview` = {kind, colors, blend?, bg?}; colours are re-checked here.
function previewHtml(p) {
  const colors = ((p && p.colors) || []).filter((c) => /^[0-9a-f]{6}$/i.test(c)).map((c) => `#${c}`);
  if (!colors.length) return "";
  if (p.kind === "bulbs") return `<span class="strip dots">${colors.map((c) => `<i style="background:${c}"></i>`).join("")}</span>`;
  let stops;
  if (p.kind === "pattern" && p.blend && colors.length > 1) {
    stops = [...colors, colors[0]].join(",");
  } else {
    // Hard bands; a short palette repeats so the strip still shows several bands.
    const run = Array.from({ length: Math.max(colors.length, 12) }, (_, i) => colors[i % colors.length]);
    stops = run.map((c, i) => `${c} ${(i / run.length) * 100}% ${((i + 1) / run.length) * 100}%`).join(",");
  }
  const bg = /^[0-9a-f]{6}$/i.test((p && p.bg) || "") ? `#${p.bg}` : "transparent";
  return `<span class="strip" style="background:linear-gradient(90deg,${stops}),${bg}"></span>`;
}

// "2026-11-24T17:40:00" (the controller's local time) -> a Date at that wall-clock time.
function parseLocal(text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(text || "");
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : null;
}

function formatNext(text, lang) {
  const when = parseLocal(text);
  if (!when) return null;
  const midnight = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((midnight(when) - midnight(new Date())) / 864e5);
  const time = when.toLocaleTimeString(lang, { hour: "numeric", minute: "2-digit" });
  if (days === 0) return `${t("today")} ${time}`;
  if (days === 1) return `${t("tomorrow")} ${time}`;
  return `${when.toLocaleDateString(lang, { weekday: "short", month: "short", day: "numeric" })} ${time}`;
}

const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (iso, n) => {
  const [y, m, d] = iso.split("-").map(Number);
  return isoDate(new Date(y, m - 1, d + n));
};
const dayDiff = (a, b) => {
  const pa = a.split("-").map(Number), pb = b.split("-").map(Number);
  return Math.round((new Date(pb[0], pb[1] - 1, pb[2]) - new Date(pa[0], pa[1] - 1, pa[2])) / 864e5);
};

// Event form <-> create_event / update_event fields.
const SUN_MINUTES = { sunrise: 360, sunset: 1080 };
const timeKind = (value) => (value === "sunset" || value === "sunrise" ? value : "time");
const clockMinutes = (value) => {
  if (SUN_MINUTES[value]) return SUN_MINUTES[value];
  const [h, m] = String(value || "0:0").split(":").map(Number);
  return (h || 0) * 60 + (m || 0);
};

function formFromEvent(ev, today) {
  const f = (ev && ev.form) || {};
  const start = f.start_date || today;
  const mode = f.frequency === 4 ? (f.by_day ? "yearly_weekday" : "yearly_date") : f.frequency === 1 ? "daily" : f.frequency === 0 ? "once" : "daily";
  const form = {
    name: ev ? ev.name : "",
    // "pl:<uuid>" is a playlist, anything else a scene.
    scene: ev ? (ev.playlist ? `pl:${ev.playlist.uuid}` : ev.scene_uuid) : "",
    pl_seconds: ev && ev.playlist ? ev.playlist.seconds : 30,
    pl_shuffle: !!(ev && ev.playlist && ev.playlist.shuffle),
    pl_once: !!(ev && ev.playlist && ev.playlist.once),
    priority: ev ? ev.priority || 3 : 3,
    start_date: start,
    start_kind: timeKind(f.start_time || "sunset"),
    start_clock: /^\d/.test(f.start_time || "") ? f.start_time : "18:00",
    start_offset: f.start_offset_minutes || 0,
    end_kind: timeKind(f.end_time || "sunrise"),
    end_clock: /^\d/.test(f.end_time || "") ? f.end_time : "23:00",
    end_offset: f.end_offset_minutes || 0,
    mode: ev ? mode : "daily",
    until: f.repeat_until || "",
    enabled: ev ? ev.enabled !== false : true,
    keepOffset: null,
  };
  if (f.end_date) {
    const gap = dayDiff(start, f.end_date);
    if (gap < 0 || gap > 1) form.keepOffset = gap;  // a multi-day window the form can't express
  }
  return form;
}

function eventData(form, device) {
  const start = form.start_kind === "time" ? form.start_clock : form.start_kind;
  const end = form.end_kind === "time" ? form.end_clock : form.end_kind;
  const overnight = clockMinutes(end) <= clockMinutes(start) ? 1 : 0;
  const data = {
    device_id: device.device_id,
    name: form.name.trim(),
    priority: Number(form.priority),
    start_date: form.start_date,
    end_date: addDays(form.start_date, form.keepOffset ?? overnight),
    start_time: start,
    end_time: end,
  };
  if (String(form.scene).startsWith("pl:")) {
    data.playlist = form.scene.slice(3);
    data.seconds_per_scene = Math.max(1, Math.min(3600, Math.round(Number(form.pl_seconds)) || 30));
    data.shuffle = !!form.pl_shuffle;
    data.play_once = !!form.pl_once;
  } else {
    data.scene = form.scene;
  }
  if (device.v3) {
    data.enabled = !!form.enabled;
    if (form.start_kind !== "time") data.start_offset_minutes = Number(form.start_offset) || 0;
    if (form.end_kind !== "time") data.end_offset_minutes = Number(form.end_offset) || 0;
  }
  const [, month, day] = form.start_date.split("-").map(Number);
  if (form.mode === "once") {
    data.frequency = 0;
  } else {
    data.frequency = form.mode === "daily" ? 1 : 4;
    if (form.mode === "yearly_date") {
      data.by_month = month;
      data.by_month_day = day;
    } else if (form.mode === "yearly_weekday") {
      const when = parseLocal(`${form.start_date}T00:00`);
      data.by_month = month;
      data.by_day = DAYS[when.getDay()];
      data.by_set_pos = Math.ceil(day / 7) > 4 ? -1 : Math.ceil(day / 7);
    }
    if (form.until) data.repeat_until = form.until;
  }
  return data;
}

const CSS = `
  :host { display: block; color-scheme: light; }
  *, *::before, *::after { box-sizing: border-box; }
  [hidden] { display: none !important; }
  button, input, select { touch-action: manipulation; -webkit-tap-highlight-color: transparent; }
  :host([dark]) { color-scheme: dark; }
  :host { display: block; max-width: 1200px; margin: 0 auto; }
  ha-card { display: block; overflow: hidden; container-type: inline-size; }
  .card { padding: 16px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; color: var(--primary-text-color); }
  .cols { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; }
  .col { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; align-content: start; }
  .col:empty { display: none; }
  .head { display: flex; align-items: center; gap: 12px; }
  .head .title { font-size: 1.25rem; font-weight: 500; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 999px; font-size: 0.78rem;
          background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .chip.ok { color: var(--success-color, #2e7d32); }
  .chip.bad { color: var(--error-color, #c62828); }
  .chip ha-icon { --mdc-icon-size: 14px; }
  h3 { margin: 0 0 8px; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--secondary-text-color); }
  .row { display: flex; align-items: center; gap: 12px; }
  button { font: inherit; color: inherit; cursor: pointer; }
  .power { width: 56px; height: 56px; border-radius: 50%; border: 0; display: grid; place-items: center; flex: none;
           background: var(--secondary-background-color); color: var(--secondary-text-color); transition: background .2s, color .2s, box-shadow .2s; }
  .power ha-icon { --mdc-icon-size: 28px; }
  .power.on { background: var(--glow, var(--primary-color)); color: #fff; box-shadow: 0 0 18px var(--glow, var(--primary-color)); }
  .power[disabled] { opacity: .5; cursor: default; }
  .slider { flex: 1; display: grid; gap: 4px; min-width: 0; }
  .slider .label { display: flex; justify-content: space-between; font-size: 0.85rem; color: var(--secondary-text-color); }
  input[type=range] { width: 100%; height: 36px; accent-color: var(--glow, var(--primary-color)); margin: 0; }
  .swatches { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; align-items: center; }
  .swatch { width: 32px; height: 32px; border-radius: 50%; border: 2px solid var(--divider-color); padding: 0; }
  .swatch.sel { border-color: var(--primary-text-color); }
  .swatch.custom { position: relative; overflow: hidden; background: conic-gradient(red, yellow, lime, aqua, blue, magenta, red); }
  .swatch.custom input { position: absolute; inset: -6px; width: 44px; height: 44px; opacity: 0; cursor: pointer; }
  .tools { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
  .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 38px; padding: 7px 14px; border-radius: 18px; border: 1px solid var(--divider-color);
         background: transparent; font-size: 0.85rem; }
  .btn:hover { background: var(--secondary-background-color); }
  .btn.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn.danger { color: var(--error-color, #c62828); border-color: var(--error-color, #c62828); }
  .btn[disabled] { opacity: .5; cursor: default; }
  .btn ha-icon { --mdc-icon-size: 18px; }
  .search { flex: 1; min-width: 120px; min-height: 38px; padding: 7px 12px; border-radius: 18px; border: 1px solid var(--divider-color);
            background: var(--card-background-color); color: var(--primary-text-color); font: inherit; font-size: 0.85rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; max-height: 340px; overflow: auto; padding: 2px; }
  .scene { text-align: left; padding: 10px 12px; border-radius: 12px; border: 1px solid var(--divider-color); background: var(--card-background-color);
           display: flex; flex-direction: column; align-items: stretch; gap: 8px; min-width: 0; }
  .scene .row { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .strip { display: block; height: 12px; border-radius: 6px; box-shadow: inset 0 0 0 1px rgba(128, 128, 128, .35); overflow: hidden; }
  .strip.dots { display: flex; align-items: center; justify-content: space-between; padding: 0 4px; background: #111; }
  .strip.dots i { width: 5px; height: 5px; border-radius: 50%; flex: none; }
  .scene:hover { background: var(--secondary-background-color); }
  .scene.active { border-color: var(--primary-color); box-shadow: inset 0 0 0 1px var(--primary-color); background: color-mix(in srgb, var(--primary-color) 12%, transparent); }
  .scene ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); flex: none; }
  .scene.active ha-icon { color: var(--primary-color); }
  .scene span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .scene .row > span:not(.row) { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow-wrap: break-word; line-height: 1.2; }
  .scene .strip { margin-top: auto; }
  .muted { color: var(--secondary-text-color); font-size: 0.9rem; }
  .facts { display: grid; grid-template-columns: auto 1fr; gap: 4px 14px; font-size: 0.9rem; margin-bottom: 10px; }
  .facts dt { color: var(--secondary-text-color); } .facts dd { margin: 0; text-align: right; }
  .events { display: grid; grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .event { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 12px; background: var(--secondary-background-color); }
  .event.off .body, .event.off .dot { opacity: .5; }
  .event .dot { width: 8px; align-self: stretch; border-radius: 4px; flex: none; }
  .event .body { flex: 1; min-width: 0; }
  .event .name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .event .sub { font-size: 0.8rem; color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .icon { width: 40px; height: 40px; border: 0; border-radius: 50%; background: transparent; display: grid; place-items: center; color: var(--secondary-text-color); flex: none; }
  .icon:hover { background: var(--divider-color); }
  .toggle { width: 40px; height: 22px; border-radius: 11px; border: 0; background: var(--disabled-text-color, #999); position: relative; flex: none; transition: background .2s; padding: 0; }
  .toggle::after { content: ""; position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: transform .2s; }
  .toggle.on { background: var(--primary-color); } .toggle.on::after { transform: translateX(18px); }
  details summary { cursor: pointer; list-style: none; }
  details summary::-webkit-details-marker { display: none; }
  details summary h3 { display: flex; align-items: center; gap: 6px; margin: 0; }
  details[open] summary h3 { margin-bottom: 8px; }
  .err { color: var(--error-color, #c62828); font-size: 0.85rem; }
  .msg { padding: 24px 16px; text-align: center; color: var(--secondary-text-color); }
  .modal { position: fixed; inset: 0; z-index: 9; background: rgba(0,0,0,.5); display: grid; place-items: center; padding: 16px; }
  .sheet { background: var(--card-background-color, #fff); color: var(--primary-text-color); border-radius: 16px; width: min(480px, 100%);
           max-height: calc(100vh - 32px); max-height: calc(100dvh - 32px); overflow: auto; overscroll-behavior: contain; padding: 18px; display: grid; gap: 12px; box-shadow: 0 8px 32px rgba(0,0,0,.4); }
  .sheet h2 { margin: 0; font-size: 1.15rem; font-weight: 500; }
  .field { display: grid; gap: 4px; font-size: 0.85rem; color: var(--secondary-text-color); }
  .field input, .field select { padding: 9px 10px; min-height: 42px; width: 100%; border-radius: 8px; border: 1px solid var(--divider-color); background: var(--card-background-color);
           color: var(--primary-text-color); font: inherit; font-size: 1rem; min-width: 0; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .offset { display: flex; align-items: center; gap: 6px; } .offset input { flex: 1; width: 100%; } .offset span { white-space: nowrap; }
  .hint { font-size: 0.75rem; }
  .check { display: flex; align-items: center; gap: 8px; font-size: 0.95rem; color: var(--primary-text-color); }
  /* A checkbox must not take the size of a text box (the .field input rule). */
  .check input[type=checkbox] { width: 20px; height: 20px; min-height: 0; padding: 0; margin: 0; flex: none; accent-color: var(--primary-color); }
  .checks { display: grid; gap: 12px; align-content: center; }
  .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px; }
  .actions .btn { min-height: 42px; padding: 8px 18px; }
  /* Wide card (a full-width panel view on a computer). */
  @container (min-width: 780px) {
    .card { padding: 20px; gap: 22px; }
    .cols { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px; }
    .grid { max-height: 420px; }
  }
  /* Narrow card (a phone, or a thin dashboard column). */
  @container (max-width: 440px) {
    .card { padding: 12px; gap: 16px; }
    .head { flex-wrap: wrap; gap: 6px 12px; }
    .power { width: 52px; height: 52px; }
    .swatches { gap: 10px; }
    .swatch { width: 36px; height: 36px; }
    .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); max-height: 240px; }
    .tools .search { flex-basis: 100%; }
    .event { gap: 8px; padding: 8px; }
    .event .sub { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
    .icon { width: 36px; height: 36px; }
  }
  /* The editor becomes a bottom sheet on a phone. */
  @media (max-width: 600px) {
    .modal { place-items: end center; padding: 0; }
    .sheet { width: 100%; border-radius: 16px 16px 0 0; max-height: 92vh; max-height: 92dvh; padding: 16px 16px calc(16px + env(safe-area-inset-bottom, 0px)); }
    .actions { position: sticky; bottom: calc(-16px - env(safe-area-inset-bottom, 0px)); background: var(--card-background-color); padding: 10px 0 2px; margin-top: 0; }
    .actions .btn { flex: 1; }
  }
`;

class CelebrightCard extends HTMLElement {
  static getStubConfig() {
    return { show_controls: true, show_scenes: true, show_schedule: true, show_info: true };
  }

  static getConfigElement() {
    return document.createElement("celebright-card-editor");
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._info = null;
    this._error = null;
    this._sig = "";
    this._search = "";
    this._dragging = false;
    this._modal = null;
    this.shadowRoot.innerHTML = `<style>${CSS}</style><ha-card><div class="card" id="root"></div></ha-card>`;
    this._root = this.shadowRoot.getElementById("root");
    this.shadowRoot.addEventListener("click", (e) => this._click(e));
    this.shadowRoot.addEventListener("input", (e) => this._input(e));
    this.shadowRoot.addEventListener("change", (e) => this._change(e));
  }

  setConfig(config) {
    this._config = {
      show_controls: true, show_scenes: true, show_schedule: true, show_info: true, ...config,
    };
    this._paint();
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    // Native controls (date, time, select) follow the theme's light or dark mode.
    const dark = hass.themes ? !!hass.themes.darkMode : window.matchMedia("(prefers-color-scheme: dark)").matches;
    this.toggleAttribute("dark", dark);
    if (first) this._load();
    const sig = this._signature();
    if (sig !== this._sigData) {
      this._sigData = sig;
      if (!first) this._load();
    }
    this._paint();
  }

  // What changes when scenes or events do, so the card asks for fresh data then.
  _signature() {
    const dev = this._device();
    if (!dev) return "";
    const sel = this._state("scene_select");
    const ev = this._state("scheduled_events");
    return JSON.stringify([sel && sel.attributes.options, ev && ev.attributes.events, ev && ev.state]);
  }

  async _load() {
    if (this._loading || !this._hass) return;
    this._loading = true;
    try {
      this._info = await this._hass.callWS({ type: "celebright/card_info" });
      this._error = null;
    } catch (err) {
      this._error = err && err.code === "unknown_command" ? t("notReady") : (err && err.message) || t("notReady");
    } finally {
      this._loading = false;
      this._paint();
    }
  }

  _device() {
    const list = (this._info && this._info.devices) || [];
    const want = this._config && this._config.device;
    return (want && list.find((d) => d.ha_device_id === want || d.device_id === want)) || list[0] || null;
  }

  _state(role) {
    const dev = this._device();
    const id = dev && dev.entities[role];
    return id ? this._hass.states[id] : undefined;
  }

  _call(domain, service, data) {
    return this._hass.callService(domain, service, data);
  }

  _lang() {
    return (this._hass && this._hass.locale && this._hass.locale.language) || navigator.language;
  }

  // ---- painting ----------------------------------------------------------

  _paint() {
    if (!this._config || !this._hass) return;
    if (this._dragging) return;
    const root = this._root;
    const dev = this._device();
    if (!this._info) {
      root.innerHTML = `<div class="msg">${esc(this._error || t("loading"))}</div>`;
      return;
    }
    if (!dev) {
      root.innerHTML = `<div class="msg">${esc(this._error || t("noDevice"))}</div>`;
      return;
    }
    const c = this._config;
    const html = [this._headHtml(dev)];
    // Two columns when the card is wide (controls and scenes | schedule and details).
    const left = [];
    const right = [];
    if (c.show_controls) left.push(`<section>${this._controlsHtml(dev)}</section>`);
    if (c.show_scenes) left.push(`<section id="scenes">${this._scenesHtml(dev)}</section>`);
    if (c.show_schedule) right.push(`<section>${this._scheduleHtml(dev)}</section>`);
    if (c.show_info) right.push(`<section>${this._infoHtml(dev)}</section>`);
    html.push(`<div class="cols"><div class="col">${left.join("")}</div><div class="col">${right.join("")}</div></div>`);
    const keep = this._root.querySelector("details")?.open;
    const search = this._root.querySelector(".search");
    const focused = !!search && this.shadowRoot.activeElement === search;
    const caret = focused ? search.selectionStart : 0;
    const scroll = this._root.querySelector(".grid")?.scrollTop || 0;
    const markup = html.join("");
    if (markup === this._markup) return;
    this._markup = markup;
    root.innerHTML = markup;
    const details = root.querySelector("details");
    if (details && keep) details.open = true;
    const grid = root.querySelector(".grid");
    if (grid) grid.scrollTop = scroll;
    if (focused) {
      const box = root.querySelector(".search");
      box.focus();
      box.setSelectionRange(caret, caret);
    }
  }

  _headHtml(dev) {
    const light = this._state("light");
    const online = light && light.state !== "unavailable";
    const source = this._state("active_source");
    const sourceText = source && !["unknown", "unavailable"].includes(source.state)
      ? (EN.source[source.state] || source.state) : null;
    const title = this._config.title || dev.name;
    return `<div class="head"><div class="title">${esc(title)}</div><div class="chips">
      <span class="chip ${online ? "ok" : "bad"}"><ha-icon icon="${online ? "mdi:cloud-check" : "mdi:cloud-off-outline"}"></ha-icon>${t(online ? "online" : "offline")}</span>
      ${sourceText ? `<span class="chip"><ha-icon icon="mdi:source-branch"></ha-icon>${esc(sourceText)}</span>` : ""}
    </div></div>`;
  }

  _controlsHtml(dev) {
    const light = this._state("light");
    if (!light) return "";
    const on = light.state === "on";
    const gone = light.state === "unavailable";
    const rgb = light.attributes.rgb_color;
    const glow = on && rgb ? rgbToHex(rgb) : "";
    const pct = Math.round(((light.attributes.brightness ?? 0) / 255) * 100);
    const selected = glow.toUpperCase();
    const current = this._state("current_display");
    const showing = current && !["unknown", "unavailable"].includes(current.state) ? current.state : "";
    return `<div class="row" ${glow ? `style="--glow:${glow}"` : ""}>
        <button class="power ${on ? "on" : ""}" data-act="power" title="${t("power")}" ${gone ? "disabled" : ""}><ha-icon icon="mdi:power"></ha-icon></button>
        <div class="slider">
          <div class="label"><span>${t("brightness")}${showing ? ` · ${esc(showing)}` : ""}</span><span id="pct">${on ? pct : 0}%</span></div>
          <input type="range" id="bri" min="1" max="255" value="${light.attributes.brightness ?? 255}" ${gone ? "disabled" : ""}>
        </div>
      </div>
      <div class="swatches" title="${t("color")}">
        ${SWATCHES.map(([hex, name]) => `<button class="swatch ${selected === hex ? "sel" : ""}" data-act="color" data-hex="${hex}" title="${name}" style="background:${hex}"></button>`).join("")}
        <label class="swatch custom" title="${t("customColor")}"><input type="color" id="picker" value="${glow || "#ffffff"}"></label>
      </div>`;
  }

  _scenesHtml(dev) {
    const select = this._state("scene_select");
    const active = select ? select.state : "";
    const q = this._search.trim().toLowerCase();
    const scenes = dev.scenes.filter((s) => !q || s.name.toLowerCase().includes(q));
    const grid = dev.scenes.length === 0
      ? `<div class="muted">${t("noScenes")}</div>`
      : scenes.length === 0
        ? `<div class="muted">${t("noMatch")}</div>`
        : `<div class="grid">${scenes.map((s) => `<button class="scene ${s.name === active ? "active" : ""}" data-act="scene" data-uuid="${esc(s.uuid)}" title="${esc(s.name)}"><span class="row">${s.name === active ? '<ha-icon icon="mdi:check-circle"></ha-icon>' : ""}<span>${esc(s.name)}</span></span>${previewHtml(s.preview)}</button>`).join("")}</div>`;
    return `<h3>${t("scenes")}</h3><div class="tools">
        ${dev.scenes.length > 6 ? `<input class="search" type="search" placeholder="${t("searchScenes")}" value="${esc(this._search)}">` : ""}
        ${dev.entities.scene_select ? `<button class="btn" data-act="resume"><ha-icon icon="mdi:calendar-sync"></ha-icon>${t("resume")}</button>` : ""}
        ${dev.entities.refresh ? `<button class="btn" data-act="refresh" title="${t("refresh")}"><ha-icon icon="mdi:refresh"></ha-icon></button>` : ""}
      </div>${grid}`;
  }

  _scheduleHtml(dev) {
    const running = this._state("schedule");
    const active = this._state("active_event");
    const next = this._state("next_event_start");
    const known = (s) => s && !["unknown", "unavailable"].includes(s.state);
    const nextText = known(next) ? formatNext(next.state, this._lang()) : null;
    const activeText = known(active) ? (active.state === "None" ? t("none") : active.state) : null;
    const sw = dev.entities.schedule_switch ? this._state("schedule_switch") : null;
    const facts = [
      activeText !== null ? `<dt>${t("activeNow")}</dt><dd>${esc(activeText)}</dd>` : "",
      `<dt>${t("nextStart")}</dt><dd>${esc(nextText || t("unknown"))}</dd>`,
    ].join("");
    const rows = dev.events.map((ev) => this._eventHtml(dev, ev)).join("");
    return `<h3>${t("schedule")}</h3>
      <div class="tools">
        ${running ? `<span class="chip ${running.state === "on" ? "ok" : ""}"><ha-icon icon="mdi:calendar-clock"></ha-icon>${t(running.state === "on" ? "scheduleOn" : "scheduleOff")}</span>` : ""}
        ${sw ? `<button class="toggle ${sw.state === "on" ? "on" : ""}" data-act="schedule-switch" title="${t("schedule")}"></button>` : ""}
      </div>
      <dl class="facts">${facts}</dl>
      <div class="events">${rows || `<div class="muted">${t("noEvents")}</div>`}</div>
      <div class="tools" style="margin-top:10px"><button class="btn primary" data-act="new-event"><ha-icon icon="mdi:plus"></ha-icon>${t("addEvent")}</button></div>`;
  }

  _eventHtml(dev, ev) {
    const what = ev.playlist ? `${t("playlistPrefix")}: ${ev.playlist.name || "?"}` : ev.scene || "?";
    const sub = [what, ev.when, ev.time].filter(Boolean).join(" · ");
    return `<div class="event ${ev.enabled ? "" : "off"}">
      <div class="dot" style="background:${PRIORITY_COLOR[ev.priority] || PRIORITY_COLOR[3]}" title="${t("priority")}: ${esc(EN.priorities[ev.priority] || ev.priority)}"></div>
      <div class="body"><div class="name">${esc(ev.name)}</div><div class="sub" title="${esc(sub)}">${esc(sub)}</div></div>
      ${dev.v3 ? `<button class="toggle ${ev.enabled ? "on" : ""}" data-act="event-toggle" data-uuid="${esc(ev.uuid)}" title="${t("enabled")}"></button>` : ""}
      ${ev.form ? `<button class="icon" data-act="event-edit" data-uuid="${esc(ev.uuid)}" title="${t("edit")}"><ha-icon icon="mdi:pencil"></ha-icon></button>` : ""}
      <button class="icon" data-act="event-delete" data-uuid="${esc(ev.uuid)}" title="${t("remove")}"><ha-icon icon="mdi:delete-outline"></ha-icon></button>
    </div>`;
  }

  _infoHtml(dev) {
    const read = (role) => {
      const s = this._state(role);
      return s && !["unknown", "unavailable"].includes(s.state) ? s.state : null;
    };
    const facts = [
      ["model", read("model")], ["firmware", read("firmware")], ["hardware", read("hw_version")],
      ["leds", read("led_count")], ["bulb", read("bulb_type")], ["order", read("color_order")],
      ["location", read("location")],
    ].filter(([, v]) => v);
    if (!facts.length) return "";
    return `<details><summary><h3><ha-icon icon="mdi:chevron-right"></ha-icon>${t("info")}</h3></summary>
      <dl class="facts">${facts.map(([k, v]) => `<dt>${t(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></details>`;
  }

  // ---- interaction -------------------------------------------------------

  async _run(promise) {
    try {
      await promise;
    } catch (err) {
      this._toast((err && err.message) || String(err));
    }
    setTimeout(() => this._load(), 2500);
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }

  _click(e) {
    const target = e.target.closest("[data-act]");
    if (!target) return;
    const dev = this._device();
    const act = target.dataset.act;
    const light = dev.entities.light;
    const uuidOf = () => dev.events.find((ev) => ev.uuid === target.dataset.uuid);
    switch (act) {
      case "power": {
        const on = this._state("light").state === "on";
        this._call("light", on ? "turn_off" : "turn_on", { entity_id: light });
        break;
      }
      case "color":
        this._call("light", "turn_on", { entity_id: light, rgb_color: hexToRgb(target.dataset.hex) });
        break;
      case "scene": {
        const scene = dev.scenes.find((s) => s.uuid === target.dataset.uuid);
        if (scene && scene.entity_id) this._call("scene", "turn_on", { entity_id: scene.entity_id });
        else if (scene) this._call("select", "select_option", { entity_id: dev.entities.scene_select, option: scene.name });
        break;
      }
      case "resume":
        this._call("select", "select_option", { entity_id: dev.entities.scene_select, option: "Off" });
        break;
      case "refresh":
        this._call("button", "press", { entity_id: dev.entities.refresh }).then(() => setTimeout(() => this._load(), 2500));
        break;
      case "schedule-switch":
        this._call("switch", this._state("schedule_switch").state === "on" ? "turn_off" : "turn_on", { entity_id: dev.entities.schedule_switch });
        break;
      case "event-toggle": {
        const ev = uuidOf();
        if (ev) this._run(this._call("celebright", "set_event_enabled", { device_id: dev.device_id, event_uuid: ev.uuid, enabled: !ev.enabled }));
        break;
      }
      case "new-event":
        this._openEvent(dev, null);
        break;
      case "event-edit":
        this._openEvent(dev, uuidOf());
        break;
      case "event-delete":
        this._openDelete(dev, uuidOf());
        break;
    }
  }

  _input(e) {
    if (e.target.id === "bri") {
      this._dragging = true;
      const pct = this._root.querySelector("#pct");
      if (pct) pct.textContent = `${Math.round((e.target.value / 255) * 100)}%`;
    } else if (e.target.classList.contains("search")) {
      this._search = e.target.value;
      this._markup = "";
      this._paint();
    }
  }

  _change(e) {
    const dev = this._device();
    if (e.target.id === "bri") {
      this._dragging = false;
      this._call("light", "turn_on", { entity_id: dev.entities.light, brightness: Number(e.target.value) });
    } else if (e.target.id === "picker") {
      this._call("light", "turn_on", { entity_id: dev.entities.light, rgb_color: hexToRgb(e.target.value) });
    }
  }

  // ---- dialogs -----------------------------------------------------------

  _closeModal() {
    if (this._modal) this._modal.remove();
    this._modal = null;
  }

  _showModal(html) {
    this._closeModal();
    const modal = document.createElement("div");
    modal.className = "modal";
    modal.innerHTML = `<div class="sheet">${html}</div>`;
    modal.addEventListener("click", (e) => { if (e.target === modal) this._closeModal(); });
    this.shadowRoot.appendChild(modal);
    this._modal = modal;
    return modal;
  }

  _openDelete(dev, ev) {
    if (!ev) return;
    const modal = this._showModal(`<h2>${t("confirmDelete")}</h2><div>${esc(ev.name)}</div>
      <div class="muted">${t("confirmDeleteBody")}</div><div class="err" id="err"></div>
      <div class="actions"><button class="btn" id="cancel">${t("cancel")}</button><button class="btn danger" id="ok">${t("remove")}</button></div>`);
    modal.querySelector("#cancel").onclick = () => this._closeModal();
    modal.querySelector("#ok").onclick = async (e) => {
      e.target.disabled = true;
      try {
        await this._call("celebright", "delete_event", { device_id: dev.device_id, event_uuid: ev.uuid });
        this._closeModal();
        setTimeout(() => this._load(), 2500);
      } catch (err) {
        modal.querySelector("#err").textContent = (err && err.message) || String(err);
        e.target.disabled = false;
      }
    };
  }

  _openEvent(dev, ev) {
    const today = isoDate(new Date());
    const form = formFromEvent(ev, today);
    const modes = [["daily", t("daily")], ["yearly_date", t("yearlyDate")], ["yearly_weekday", t("yearlyWeekday")]];
    if (dev.v3) modes.unshift(["once", t("once")]);
    if (!modes.some(([v]) => v === form.mode)) form.mode = "daily";
    const timeBlock = (key, label) => `<div class="field"><span>${label}</span>
        <div class="two"><select data-f="${key}_kind">
          <option value="sunset">${t("sunset")}</option><option value="sunrise">${t("sunrise")}</option><option value="time">${t("atTime")}</option></select>
        <input type="time" data-f="${key}_clock">
        ${dev.v3 ? `<div class="offset" data-o="${key}"><input type="number" data-f="${key}_offset" step="5" min="-720" max="720"><span>${t("minutes")}</span></div>` : ""}</div>
        ${dev.v3 ? `<span class="hint" data-h="${key}">${t("offset")}</span>` : ""}</div>`;
    // Playlists (firmware 3.x) are offered next to the scenes; an event that already plays one keeps it listed.
    const playlists = dev.v3 ? [...(dev.playlists || [])] : [];
    if (ev && ev.playlist && !playlists.some((p) => p.uuid === ev.playlist.uuid)) playlists.push({ uuid: ev.playlist.uuid, name: ev.playlist.name || t("playlistPrefix") });
    const sceneOptions = dev.scenes.map((s) => `<option value="${esc(s.uuid)}">${esc(s.name)}</option>`).join("");
    const modal = this._showModal(`<h2>${t(ev ? "editEvent" : "newEvent")}</h2>
      <label class="field"><span>${t("name")}</span><input type="text" data-f="name" maxlength="60"></label>
      <div class="two">
        <label class="field"><span>${t(playlists.length ? "sceneOrPlaylist" : "scene")}</span><select data-f="scene"><option value="">${t(playlists.length ? "chooseSceneOrPlaylist" : "chooseScene")}</option>
          ${playlists.length
            ? `<optgroup label="${t("scenesGroup")}">${sceneOptions}</optgroup><optgroup label="${t("playlistsGroup")}">${playlists.map((p) => `<option value="pl:${esc(p.uuid)}">${esc(p.name)}</option>`).join("")}</optgroup>`
            : sceneOptions}</select></label>
        <label class="field"><span>${t("priority")}</span><select data-f="priority">
          ${[1, 2, 3, 4].map((p) => `<option value="${p}">${p} · ${EN.priorities[p]}</option>`).join("")}</select></label>
      </div>
      <div class="two" id="pl-opts"><label class="field"><span>${t("evSeconds")}</span><input type="number" data-f="pl_seconds" min="1" max="3600" step="5"></label>
        <div class="checks"><label class="check"><input type="checkbox" data-f="pl_shuffle"> ${t("evShuffle")}</label>
          <label class="check"><input type="checkbox" data-f="pl_once"> ${t("evOnce")}</label></div></div>
      ${timeBlock("start", t("starts"))}${timeBlock("end", t("ends"))}
      <div class="two">
        <label class="field"><span>${t("firstNight")}</span><input type="date" data-f="start_date"></label>
        <label class="field"><span>${t("repeat")}</span><select data-f="mode">${modes.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
      </div>
      <label class="field" id="until-row"><span>${t("until")}</span><input type="date" data-f="until"></label>
      ${dev.v3 ? `<label class="check"><input type="checkbox" data-f="enabled"> ${t("enabled")}</label>` : ""}
      <div class="err" id="err"></div>
      <div class="actions"><button class="btn" id="cancel">${t("cancel")}</button><button class="btn primary" id="ok">${t("save")}</button></div>`);

    const fields = [...modal.querySelectorAll("[data-f]")];
    const sync = () => {
      for (const el of fields) {
        const key = el.dataset.f;
        el[el.type === "checkbox" ? "checked" : "value"] = form[key];
      }
      for (const key of ["start", "end"]) {
        const clock = modal.querySelector(`[data-f=${key}_clock]`);
        const offset = modal.querySelector(`[data-o=${key}]`);
        const hint = modal.querySelector(`[data-h=${key}]`);
        const fixed = form[`${key}_kind`] === "time";
        clock.style.display = fixed ? "" : "none";
        if (offset) offset.style.display = fixed ? "none" : "";
        if (hint) hint.style.display = fixed ? "none" : "";
      }
      modal.querySelector("#until-row").style.display = form.mode === "once" ? "none" : "";
      modal.querySelector("#pl-opts").style.display = String(form.scene).startsWith("pl:") ? "" : "none";
    };
    modal.addEventListener("input", (e) => {
      const key = e.target.dataset && e.target.dataset.f;
      if (!key) return;
      form[key] = e.target.type === "checkbox" ? e.target.checked : e.target.value;
      if (key.endsWith("_kind") || key === "mode" || key === "scene") sync();
    });
    sync();
    modal.querySelector("#cancel").onclick = () => this._closeModal();
    modal.querySelector("#ok").onclick = async (e) => {
      const err = modal.querySelector("#err");
      const problem = !form.name.trim() ? t("needName") : !form.scene ? t("needScene") : !form.start_date ? t("needDate") : "";
      if (problem) { err.textContent = problem; return; }
      err.textContent = "";
      const button = e.target;
      button.disabled = true;
      button.textContent = t("working");
      const data = eventData(form, dev);
      try {
        if (ev) await this._call("celebright", "update_event", { event_uuid: ev.uuid, ...data });
        else await this._call("celebright", "create_event", data);
        this._closeModal();
        setTimeout(() => this._load(), 2500);
      } catch (error) {
        err.textContent = (error && error.message) || String(error);
        button.disabled = false;
        button.textContent = t("save");
      }
    };
  }
}

class CelebrightCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) => ({
        device: "Controller", title: "Title", show_controls: "Power, brightness and colour",
        show_scenes: "Scenes", show_schedule: "Schedule", show_info: "Controller details",
      }[schema.name] || schema.name);
      this._form.addEventListener("value-changed", (e) => {
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: e.detail.value }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = [
      { name: "device", selector: { device: { integration: "celebright" } } },
      { name: "title", selector: { text: {} } },
      { name: "show_controls", selector: { boolean: {} } },
      { name: "show_scenes", selector: { boolean: {} } },
      { name: "show_schedule", selector: { boolean: {} } },
      { name: "show_info", selector: { boolean: {} } },
    ];
    this._form.data = { show_controls: true, show_scenes: true, show_schedule: true, show_info: true, ...this._config };
  }
}

// ---- Automations card ------------------------------------------------------
// Lists the automations built from the Celebright blueprints, grouped by blueprint, with
// switch / run / edit, and warns when two copies of a one-per-home blueprint are both on.

const BLUEPRINTS = [
  { file: "holiday_lighting_controller.yaml", icon: "mdi:calendar-star", single: true, superseded: true,
    title: "Holiday lighting controller", info: "One automation for every holiday and scheduled scene." },
  { file: "scene_in_date_range.yaml", icon: "mdi:calendar-range", superseded: true, title: "Scene for a date range",
    info: "A scene every night from sunset inside a yearly date range." },
  { file: "scene_for_holiday_week.yaml", icon: "mdi:calendar-week", superseded: true, title: "Scene for a holiday week",
    info: "A scene on every night of the week that contains a date." },
  { file: "scene_toggle.yaml", icon: "mdi:toggle-switch", superseded: true, title: "Scene on a toggle",
    info: "A scene while a switch is on; the schedule returns when it's off." },
  { file: "resume_schedule_at_time.yaml", icon: "mdi:calendar-sync", title: "Resume the schedule at a time",
    info: "Hands control back to the controller's schedule each day." },
  { file: "controller_offline_notify.yaml", icon: "mdi:lan-disconnect", title: "Controller offline notification",
    info: "Notifies you when the controller has been unavailable for a while." },
];

Object.assign(EN, {
  automations: "Automations",
  autoNone: "None yet.",
  autoRefresh: "Refresh",
  autoSuperseded: "Superseded",
  autoSupersededInfo: "The Holidays and Rules tabs replace this blueprint. Your automation keeps working.",
  autoCreate: "Create",
  autoAnother: "Create another",
  autoRun: "Run now",
  autoEdit: "Edit",
  autoAll: "All automations",
  autoBlueprints: "Blueprints",
  autoHint: "To create one, open Blueprints, pick it and choose Create automation. Open an existing one with Edit instead of creating a second.",
  autoNoSearch: "Couldn't group by blueprint; showing automations with Celebright in the name.",
  autoNothing: "No Celebright automations found.",
  autoDuplicate: "More than one is on. They will compete: turn all but one off.",
  autoNever: "never run",
  autoUnavailable: "Unavailable: open it to see what's wrong",
  lastRun: "last run",
});

// "2026-11-22T10:00:00+00:00" -> "3 hours ago"
function relativeTime(iso, lang, now) {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const secs = Math.round((then - now) / 1000);
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
  for (const [unit, size] of [["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (Math.abs(secs) >= size) return rtf.format(Math.round(secs / size), unit);
  }
  return rtf.format(0, "second");
}

const AUTO_CSS = `
  .rchip { font-size: 0.72rem; font-weight: 500; padding: 1px 8px; border-radius: 999px; background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .bp { display: grid; gap: 8px; padding-bottom: 14px; border-bottom: 1px solid var(--divider-color); }
  .bp:last-of-type { border-bottom: 0; }
  .bp-head { display: flex; align-items: center; gap: 10px; }
  .bp-head > ha-icon { --mdc-icon-size: 22px; color: var(--primary-color); flex: none; }
  .bp-head .body { flex: 1; min-width: 0; }
  .bp-head .name { font-weight: 500; }
  .bp-head .sub { font-size: 0.8rem; color: var(--secondary-text-color); }
  .rows { display: grid; gap: 6px; }
  .warn { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 10px; font-size: 0.85rem;
          color: var(--warning-color, #b26a00); background: color-mix(in srgb, var(--warning-color, #ff9800) 14%, transparent); }
  .warn ha-icon { --mdc-icon-size: 18px; flex: none; }
  .none { padding: 2px 4px; }
  .hint { font-size: 0.8rem; }
  .event .sub.err { color: var(--error-color, #c62828); white-space: normal; }
`;

class CelebrightAutomationsCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._related = null; // blueprint file -> automation entity ids (null: not loaded, or search unavailable)
    this._loaded = false;
    this._ids = "";
    this.shadowRoot.innerHTML = `<style>${CSS}${AUTO_CSS}</style><ha-card><div class="card" id="root"></div></ha-card>`;
    this._root = this.shadowRoot.getElementById("root");
    this.shadowRoot.addEventListener("click", (e) => this._click(e));
  }

  setConfig(config) {
    this._config = { ...config };
    this._paint();
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const dark = hass.themes ? !!hass.themes.darkMode : window.matchMedia("(prefers-color-scheme: dark)").matches;
    this.toggleAttribute("dark", dark);
    // Ask again only when automations appear or go; their on/off state is read live.
    const ids = Object.keys(hass.states).filter((id) => id.startsWith("automation.")).sort().join(",");
    if (first || ids !== this._ids) {
      this._ids = ids;
      this._load();
    }
    this._paint();
  }

  async _blueprintPaths() {
    const found = await blueprintPaths(this._hass, BLUEPRINTS.map((bp) => bp.file));
    this._guessed = found.guessed;
    return found.paths;
  }

  async _load() {
    if (this._loading || !this._hass) return;
    this._loading = true;
    try {
      const paths = await this._blueprintPaths();
      const results = await Promise.all(BLUEPRINTS.map(async (bp) => {
        const lists = await Promise.all(paths[bp.file].map((path) =>
          this._hass.callWS({ type: "search/related", item_type: "automation_blueprint", item_id: path })));
        return [bp.file, [...new Set(lists.flatMap((r) => (r && r.automation) || []))]];
      }));
      this._related = Object.fromEntries(results);
      // Guessed paths that matched nothing: group by name instead of showing an empty card.
      if (this._guessed && results.every(([, ids]) => !ids.length)) this._related = null;
    } catch (err) {
      this._related = null; // no search integration: fall back to a name match
    } finally {
      this._loading = false;
      this._loaded = true;
      this._paint();
    }
  }

  get _admin() {
    return !this._hass || !this._hass.user || this._hass.user.is_admin !== false;
  }

  _row(entityId, now) {
    const st = this._hass.states[entityId];
    if (!st) return null;
    const on = st.state === "on";
    const bad = st.state === "unavailable";
    const last = st.attributes.last_triggered ? relativeTime(st.attributes.last_triggered, this._hass.language, now) : null;
    const sub = bad ? t("autoUnavailable") : `${t("lastRun")} ${last || t("autoNever")}`;
    const name = st.attributes.friendly_name || entityId;
    const canEdit = this._admin && st.attributes.id;
    return { on, html: `<div class="event ${on ? "" : "off"}">
      <div class="body"><div class="name" title="${esc(name)}">${esc(name)}</div><div class="sub ${bad ? "err" : ""}">${esc(sub)}</div></div>
      <button class="toggle ${on ? "on" : ""}" data-act="toggle" data-eid="${esc(entityId)}" title="${on ? "On" : "Off"}"></button>
      <button class="icon" data-act="run" data-eid="${esc(entityId)}" title="${t("autoRun")}"><ha-icon icon="mdi:play"></ha-icon></button>
      ${canEdit ? `<button class="icon" data-act="edit" data-id="${esc(st.attributes.id)}" title="${t("autoEdit")}"><ha-icon icon="mdi:pencil"></ha-icon></button>` : ""}
    </div>` };
  }

  _groupHtml(bp, ids, now) {
    const rows = ids.map((id) => this._row(id, now)).filter(Boolean);
    const dup = bp.single && rows.filter((r) => r.on).length > 1;
    // A superseded blueprint (the Holidays and Rules tabs replace it) is only shown while you still have an automation from it.
    if (bp.superseded && rows.length === 0) return "";
    const create = !this._admin || bp.superseded ? "" : rows.length === 0
      ? `<button class="btn primary" data-act="nav" data-path="/config/blueprint/dashboard"><ha-icon icon="mdi:plus"></ha-icon>${t("autoCreate")}</button>`
      : bp.single ? "" : `<button class="icon" data-act="nav" data-path="/config/blueprint/dashboard" title="${t("autoAnother")}"><ha-icon icon="mdi:plus"></ha-icon></button>`;
    return `<section class="bp">
      <div class="bp-head"><ha-icon icon="${bp.icon}"></ha-icon>
        <div class="body"><div class="name">${esc(bp.title)}${bp.superseded ? ` <span class="rchip">${t("autoSuperseded")}</span>` : ""}</div><div class="sub">${esc(bp.superseded ? t("autoSupersededInfo") : bp.info)}</div></div>${create}</div>
      ${dup ? `<div class="warn"><ha-icon icon="mdi:alert-outline"></ha-icon>${t("autoDuplicate")}</div>` : ""}
      <div class="rows">${rows.length ? rows.map((r) => r.html).join("") : `<div class="muted none">${t("autoNone")}</div>`}</div>
    </section>`;
  }

  _paint() {
    if (!this._config || !this._hass) return;
    if (!this._loaded) {
      this._root.innerHTML = `<div class="msg">${t("loading")}</div>`;
      return;
    }
    const now = Date.now();
    let body;
    if (this._related) {
      body = BLUEPRINTS.map((bp) => this._groupHtml(bp, this._related[bp.file] || [], now)).join("");
    } else {
      const ids = Object.keys(this._hass.states).filter((id) => id.startsWith("automation.")
        && (id.includes("celebright") || String(this._hass.states[id].attributes.friendly_name || "").toLowerCase().includes("celebright")));
      const rows = ids.map((id) => this._row(id, now)).filter(Boolean);
      body = `<div class="muted">${t("autoNoSearch")}</div><div class="rows">${rows.length ? rows.map((r) => r.html).join("") : `<div class="muted none">${t("autoNothing")}</div>`}</div>`;
    }
    const nav = this._admin ? `<div class="tools">
        <button class="btn" data-act="nav" data-path="/config/automation/dashboard"><ha-icon icon="mdi:robot"></ha-icon>${t("autoAll")}</button>
        <button class="btn" data-act="nav" data-path="/config/blueprint/dashboard"><ha-icon icon="mdi:file-document-outline"></ha-icon>${t("autoBlueprints")}</button>
      </div><div class="muted hint">${t("autoHint")}</div>` : "";
    const markup = `<div class="head"><div class="title">${esc(this._config.title || t("automations"))}</div>
      <button class="icon" data-act="reload" title="${t("autoRefresh")}"><ha-icon icon="mdi:refresh"></ha-icon></button></div>${body}${nav}`;
    if (markup !== this._markup) {
      this._markup = markup;
      this._root.innerHTML = markup;
    }
  }

  _click(event) {
    const el = event.target.closest("[data-act]");
    if (!el || !this._hass) return;
    const eid = el.dataset.eid;
    switch (el.dataset.act) {
      case "toggle": this._hass.callService("automation", "toggle", { entity_id: eid }); break;
      case "run": this._hass.callService("automation", "trigger", { entity_id: eid }); break;
      case "edit": this._navigate(`/config/automation/edit/${encodeURIComponent(el.dataset.id)}`); break;
      case "nav": this._navigate(el.dataset.path); break;
      case "reload": this._load(); break;
    }
  }

  _navigate(path) {
    history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }
}

// ---- Holidays card -----------------------------------------------------------
// One tile per holiday: pick a scene, switch it on. Each holiday becomes a single event on the
// controller (see holidays.py), so it keeps running without Home Assistant; the integration
// updates it to next year's dates (in Home Assistant, not in the cloud).

Object.assign(EN, {
  holidays: "Holidays",
  holRefresh: "Refresh",
  holIntro: "Each holiday is one event on your controller, so it keeps running if Home Assistant is offline. Home Assistant checks every half hour and at startup, and moves it to next year's dates once the holiday has passed.",
  holNext: "Next",
  holNoScene: "Choose a scene",
  holOn: "On",
  holSwitchedOff: "Off",
  holSave: "Save",
  holSaving: "Saving to the controller…",
  holScene: "Scene",
  holBefore: "Extra days before",
  holAfter: "Extra days after",
  holAdd: "Add a holiday",
  holCustom: "Your holiday",
  holName: "Name",
  holStart: "First day",
  holEnd: "Last day",
  holRemove: "Delete holiday",
  holPickScene: "Pick a scene first.",
  holChecking: "Checking the holidays against the controller…",
  holPickPlaylist: "Pick a playlist first.",
  holKindScene: "A scene",
  holKindPlaylist: "A playlist",
  holPlaylistGone: "Playlist removed",
  holSeconds: "Time per scene (s)",
  holShuffle: "Shuffle",
  holPlaylistsNone: "No playlists yet. Make one on the Playlists tab.",
  holNeedName: "Give it a name.",
  holWillBe: "Lights on",
  holConflict: "The holiday lighting automation is on and will compete with these. Turn it off to let the controller handle holidays. If you use it for the aurora alert, recreate that on the Rules tab first.",
  holTurnOff: "Turn it off",
  holReadOnly: "Only an administrator can change holidays.",
  holLoadFail: "Couldn't load the holidays.",
});

const MONTHS_SHORT = (lang) => Array.from({ length: 12 }, (_, i) => new Date(2024, i, 1).toLocaleDateString(lang, { month: "short" }));
const isoToDate = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
const dateToIso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

// "2027-10-25", "2027-10-31" -> "Oct 25 – 31" (the year only when it isn't this one)
function spanText(start, end, lang) {
  const a = isoToDate(start), b = isoToDate(end);
  const month = (d) => d.toLocaleDateString(lang, { month: "short" });
  const first = `${month(a)} ${a.getDate()}`;
  const last = a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear() ? `${b.getDate()}` : `${month(b)} ${b.getDate()}`;
  const year = b.getFullYear() !== new Date().getFullYear() ? `, ${b.getFullYear()}` : "";
  return a.getTime() === b.getTime() ? `${first}${year}` : `${first} – ${last}${year}`;
}

// The saved window moved by the (unsaved) extra days, for the preview in the editor.
function adjustedSpan(row, before, after) {
  const start = isoToDate(row.next.start), end = isoToDate(row.next.end);
  start.setDate(start.getDate() + row.before - before);
  end.setDate(end.getDate() - row.after + after);
  if (end < start) end.setTime(start.getTime());
  return [dateToIso(start), dateToIso(end)];
}

// Where Home Assistant stored each Celebright blueprint (an import is filed under the GitHub
// owner's name), found by file name. {file: [paths]}; `guessed` when the list isn't readable.
async function blueprintPaths(hass, files) {
  let listed = null;
  try {
    listed = Object.keys(await hass.callWS({ type: "blueprint/list", domain: "automation" }));
  } catch (err) {
    listed = null;
  }
  const paths = {};
  files.forEach((file) => {
    const found = (listed || []).filter((p) => p.split("/").pop() === file);
    paths[file] = found.length ? found : [`celebright/${file}`];
  });
  return { paths, guessed: listed === null };
}

const HOLIDAY_BLUEPRINT = "holiday_lighting_controller.yaml";

class CelebrightHolidaysCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._info = null;
    this._rows = null;
    this._error = null;
    this._busy = new Set();
    this._conflicts = [];
    this._modal = null;
    this.shadowRoot.innerHTML = `<style>${CSS}${HOL_CSS}</style><ha-card><div class="card" id="root"></div></ha-card>`;
    this._root = this.shadowRoot.getElementById("root");
    this.shadowRoot.addEventListener("click", (e) => this._click(e));
    this.shadowRoot.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches(".hol")) { e.preventDefault(); this._click(e); }
    });
  }

  setConfig(config) {
    const changed = this._config && config.device !== this._config.device;
    this._config = { ...config };
    if (changed) this._load();
    this._paint();
  }

  getCardSize() { return 8; }
  getGridOptions() { return { columns: 12, min_columns: 6, rows: "auto" }; }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this.toggleAttribute("dark", hass.themes ? !!hass.themes.darkMode : window.matchMedia("(prefers-color-scheme: dark)").matches);
    if (first) this._load();
    this._paint();
  }

  get _admin() {
    return !this._hass || !this._hass.user || this._hass.user.is_admin !== false;
  }

  _device() {
    const list = (this._info && this._info.devices) || [];
    const want = this._config && this._config.device;
    return (want && list.find((d) => d.ha_device_id === want || d.device_id === want)) || list[0] || null;
  }

  // The refresh button: have Home Assistant check each holiday against the controller now (administrators), then reload.
  async _resync() {
    if (this._admin && !this._syncing) {
      this._syncing = true;
      this._notice = t("holChecking");
      this._paint();
      try { await this._hass.callWS({ type: "celebright/holidays_sync" }); } catch (err) { /* the tiles show any error */ }
      this._syncing = false;
      this._notice = "";
    }
    this._load();
  }

  async _load() {
    if (this._loading || !this._hass) return;
    this._loading = true;
    try {
      const [info, hol] = await Promise.all([
        this._hass.callWS({ type: "celebright/card_info" }),
        this._hass.callWS({ type: "celebright/holidays" }),
      ]);
      this._info = info;
      this._all = hol.devices || {};
      this._error = null;
    } catch (err) {
      this._error = (err && err.message) || t("holLoadFail");
    } finally {
      this._loading = false;
      this._paint();
    }
    this._checkConflict();
  }

  // The holiday lighting blueprint automation would fight these events.
  async _checkConflict() {
    try {
      const { paths } = await blueprintPaths(this._hass, [HOLIDAY_BLUEPRINT]);
      const lists = await Promise.all(paths[HOLIDAY_BLUEPRINT].map((p) =>
        this._hass.callWS({ type: "search/related", item_type: "automation_blueprint", item_id: p })));
      this._conflicts = [...new Set(lists.flatMap((r) => (r && r.automation) || []))]
        .filter((id) => this._hass.states[id] && this._hass.states[id].state === "on");
    } catch (err) {
      this._conflicts = [];
    }
    this._paint();
  }

  _rowsFor(dev) {
    return (this._all && this._all[dev.device_id]) || [];
  }

  _scene(dev, uuid) {
    return dev.scenes.find((s) => s.uuid === uuid) || null;
  }

  _paint() {
    if (!this._config || !this._hass) return;
    if (!this._info || !this._all) {
      this._root.innerHTML = `<div class="msg">${esc(this._error || t("loading"))}</div>`;
      return;
    }
    const dev = this._device();
    if (!dev) { this._root.innerHTML = `<div class="msg">${t("noDevice")}</div>`; return; }
    const lang = this._hass.language;
    const conflict = this._conflicts.length && this._admin
      ? `<div class="warn"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${t("holConflict")}</span>
          <button class="btn" data-act="conflict-off">${t("holTurnOff")}</button></div>` : "";
    const tiles = this._rowsFor(dev).map((row) => this._tileHtml(dev, row, lang)).join("");
    const add = this._admin ? `<button class="hol add" data-act="hol-add"><ha-icon icon="mdi:plus"></ha-icon>${t("holAdd")}</button>` : "";
    const markup = `<div class="head"><div class="title">${t("holidays")}</div>
        <button class="icon" data-act="hol-reload" title="${t("holRefresh")}"><ha-icon icon="mdi:refresh"></ha-icon></button></div>
      <div class="muted">${t("holIntro")}</div>${this._notice ? `<div class="notice">${esc(this._notice)}</div>` : ""}${conflict}
      ${this._admin ? "" : `<div class="muted">${t("holReadOnly")}</div>`}
      <div class="hols">${tiles}${add}</div>`;
    if (markup !== this._markup) {
      this._markup = markup;
      this._root.innerHTML = markup;
    }
  }

  _tileHtml(dev, row, lang) {
    const scene = this._scene(dev, row.scene);
    const playlist = row.playlist ? (dev.playlists || []).find((p) => p.uuid === row.playlist) || null : null;
    const busy = this._busy.has(row.id);
    const status = row.status || {};
    const nice = (x) => (x === "sunset" ? t("sunset") : x === "sunrise" ? t("sunrise") : x === "00:00" ? t("midnight") : x);
    const when = row.times && row.times.length === 2 ? ` · ${nice(row.times[0])} → ${nice(row.times[1])}` : "";
    const sub = row.enabled
      ? `${t("holNext")}: ${spanText(row.next.start, row.next.end, lang)}${when}`
      : row.info;
    return `<div class="hol ${row.enabled ? "on" : ""}" role="button" tabindex="0" data-act="hol-open" data-id="${esc(row.id)}">
      <div class="hol-head"><div class="name" title="${esc(row.name)}">${esc(row.name)}</div>
        ${this._admin ? `<button class="toggle ${row.enabled ? "on" : ""}" data-act="hol-toggle" data-id="${esc(row.id)}" title="${row.enabled ? t("holOn") : t("holSwitchedOff")}" ${busy ? "disabled" : ""}></button>` : ""}</div>
      <div class="sub">${esc(sub)}</div>
      ${row.playlist
        ? (playlist
          ? `<div class="hol-scene">${playlist.scenes.slice(0, 2).map((x) => previewHtml(x.preview)).join("")}<span class="sname"><ha-icon icon="mdi:playlist-play"></ha-icon> ${esc(playlist.name)} · ${fmtSeconds(row.seconds || 30)}${row.shuffle ? " · " + t("holShuffle").toLowerCase() : ""}</span></div>`
          : `<div class="hol-scene err">${t("holPlaylistGone")}</div>`)
        : scene ? `<div class="hol-scene">${previewHtml(scene.preview)}<span class="sname">${esc(scene.name)}</span></div>`
        : `<div class="hol-scene muted">${t("holNoScene")}</div>`}
      ${busy ? `<div class="sub">${t("holSaving")}</div>` : status.state === "error" ? `<div class="err">${esc(status.message)}</div>` : ""}
    </div>`;
  }

  // ---- actions ----------------------------------------------------------

  _click(event) {
    const el = event.target.closest("[data-act]");
    if (!el || !this._hass) return;
    const dev = this._device();
    const id = el.dataset.id;
    switch (el.dataset.act) {
      case "hol-reload": this._resync(); break;
      case "conflict-off":
        this._conflicts.forEach((eid) => this._hass.callService("automation", "turn_off", { entity_id: eid }));
        this._conflicts = [];
        this._paint();
        break;
      case "hol-toggle": event.stopPropagation(); this._toggle(dev, id); break;
      case "hol-open": if (this._admin) this._openEditor(dev, this._rowsFor(dev).find((r) => r.id === id)); break;
      case "hol-add": this._openEditor(dev, null); break;
    }
  }

  async _toggle(dev, id) {
    const row = this._rowsFor(dev).find((r) => r.id === id);
    if (!row) return;
    if (!row.enabled && !row.scene && !row.playlist) { this._openEditor(dev, row); return; }
    await this._save(dev, row, { scene: row.scene, playlist: row.playlist, seconds: row.seconds, shuffle: row.shuffle, enabled: !row.enabled, before: row.before, after: row.after });
  }

  async _save(dev, row, values) {
    this._busy.add(row.id);
    this._paint();
    try {
      const updated = await this._hass.callWS({
        type: "celebright/holiday_set", device_id: dev.device_id, holiday_id: row.id,
        scene: values.scene || null, enabled: values.enabled, before: values.before, after: values.after,
        ...(values.playlist ? { playlist: values.playlist, seconds: values.seconds || 30, shuffle: !!values.shuffle } : {}),
      });
      const list = this._all[dev.device_id];
      list[list.findIndex((r) => r.id === row.id)] = updated;
      return null;
    } catch (err) {
      return (err && err.message) || "Failed";
    } finally {
      this._busy.delete(row.id);
      this._paint();
    }
  }

  // ---- the editor sheet --------------------------------------------------

  _closeModal() { if (this._modal) this._modal.remove(); this._modal = null; }

  _showModal(html) {
    this._closeModal();
    const modal = document.createElement("div");
    modal.className = "modal";
    modal.innerHTML = `<div class="sheet">${html}</div>`;
    modal.addEventListener("click", (e) => { if (e.target === modal) this._closeModal(); });
    this.shadowRoot.appendChild(modal);
    this._modal = modal;
    return modal;
  }

  _openEditor(dev, row) {
    const lang = this._hass.language;
    const custom = !row || row.custom;
    const playlists = dev.v3 ? dev.playlists || [] : [];
    const draft = {
      scene: row ? row.scene : null, before: row ? row.before : 0, after: row ? row.after : 0,
      kind: row && row.playlist ? "playlist" : "scene", playlist: row ? row.playlist : null,
      seconds: row && row.seconds ? row.seconds : 30, shuffle: !!(row && row.shuffle),
      name: row ? row.name : "", start: row && row.start ? row.start : "12-20", end: row && row.end ? row.end : "01-05",
    };
    const months = MONTHS_SHORT(lang);
    const monthDay = (field, value) => {
      const [m, d] = value.split("-").map(Number);
      return `<div class="two"><select data-f="${field}-m">${months.map((n, i) => `<option value="${i + 1}" ${i + 1 === m ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
        <select data-f="${field}-d">${Array.from({ length: 31 }, (_, i) => `<option value="${i + 1}" ${i + 1 === d ? "selected" : ""}>${i + 1}</option>`).join("")}</select></div>`;
    };
    const modal = this._showModal(`<h2>${esc(row ? row.name : t("holCustom"))}</h2>
      ${row && !row.custom ? `<div class="muted">${esc(row.info)}</div>` : ""}
      ${custom ? `<label class="field"><span>${t("holName")}</span><input data-f="name" maxlength="60" value="${esc(draft.name)}"></label>
        <div class="two"><div class="field"><span>${t("holStart")}</span>${monthDay("start", draft.start)}</div>
        <div class="field"><span>${t("holEnd")}</span>${monthDay("end", draft.end)}</div></div>` : ""}
      ${playlists.length || draft.kind === "playlist" ? `<div class="two kinds"><button class="btn" data-kind="scene">${t("holKindScene")}</button><button class="btn" data-kind="playlist">${t("holKindPlaylist")}</button></div>` : ""}
      <div class="field" id="scene-box"><span>${t("holScene")}</span><div class="grid pick" id="scenes"></div></div>
      <div id="playlist-box" hidden>
        <div class="field"><span>${t("playlists")}</span><div class="grid pick" id="pls"></div></div>
        <div class="two"><label class="field"><span>${t("holSeconds")}</span><input type="number" min="1" max="3600" step="5" data-f="seconds" value="${draft.seconds}"></label>
          <div class="checks"><label class="check"><input type="checkbox" data-f="shuffle" ${draft.shuffle ? "checked" : ""}> ${t("holShuffle")}</label></div></div></div>
      <div class="two"><label class="field"><span>${t("holBefore")}</span><input type="number" min="-14" max="14" data-f="before" value="${draft.before}"></label>
        <label class="field"><span>${t("holAfter")}</span><input type="number" min="-14" max="14" data-f="after" value="${draft.after}"></label></div>
      <div class="muted" id="preview"></div><div class="err" id="err"></div>
      <div class="actions">${row && row.custom ? `<button class="btn danger" id="remove">${t("holRemove")}</button>` : ""}
        <button class="btn" id="cancel">${t("cancel")}</button><button class="btn primary" id="save">${t("holSave")}</button></div>`);

    const $ = (sel) => modal.querySelector(sel);
    const paintScenes = () => {
      $("#scenes").innerHTML = dev.scenes.map((s) => `<button class="scene ${s.uuid === draft.scene ? "active" : ""}" data-uuid="${esc(s.uuid)}" title="${esc(s.name)}">
        <span class="row">${s.uuid === draft.scene ? '<ha-icon icon="mdi:check-circle"></ha-icon>' : ""}<span>${esc(s.name)}</span></span>${previewHtml(s.preview)}</button>`).join("");
    };
    const paintPreview = () => {
      if (row && !row.custom) {
        const [a, b] = adjustedSpan(row, draft.before, draft.after);
        $("#preview").textContent = `${t("holWillBe")}: ${spanText(a, b, lang)}`;
      } else {
        $("#preview").textContent = "";
      }
    };
    const paintKind = () => {
      $("#scene-box").hidden = draft.kind !== "scene";
      $("#playlist-box").hidden = draft.kind !== "playlist";
      modal.querySelectorAll("[data-kind]").forEach((b) => b.classList.toggle("primary", b.dataset.kind === draft.kind));
    };
    const paintPlaylists = () => {
      $("#pls").innerHTML = playlists.length ? playlists.map((p) => `<button class="scene ${p.uuid === draft.playlist ? "active" : ""}" data-pl="${esc(p.uuid)}" title="${esc(p.name)}">
        <span class="row">${p.uuid === draft.playlist ? '<ha-icon icon="mdi:check-circle"></ha-icon>' : ""}<span>${esc(p.name)}</span></span>${p.scenes.slice(0, 1).map((x) => previewHtml(x.preview)).join("")}</button>`).join("")
        : `<div class="muted">${t("holPlaylistsNone")}</div>`;
    };
    paintScenes(); paintPlaylists(); paintKind(); paintPreview();
    $("#scenes").addEventListener("click", (e) => {
      const b = e.target.closest("[data-uuid]");
      if (b) { draft.scene = b.dataset.uuid; paintScenes(); }
    });
    $("#pls").addEventListener("click", (e) => {
      const b = e.target.closest("[data-pl]");
      if (b) { draft.playlist = b.dataset.pl; paintPlaylists(); }
    });
    modal.querySelectorAll("[data-kind]").forEach((b) => { b.onclick = () => { draft.kind = b.dataset.kind; paintKind(); }; });
    modal.addEventListener("input", (e) => {
      const f = e.target.dataset.f;
      if (f === "before" || f === "after") { draft[f] = Math.max(-14, Math.min(14, parseInt(e.target.value, 10) || 0)); paintPreview(); }
      if (f === "name") draft.name = e.target.value;
      if (f === "seconds") draft.seconds = Math.max(1, Math.min(3600, parseInt(e.target.value, 10) || 30));
      if (f === "shuffle") draft.shuffle = e.target.checked;
    });
    modal.addEventListener("change", (e) => {
      const f = e.target.dataset.f || "";
      const m = /^(start|end)-(m|d)$/.exec(f);
      if (!m) return;
      const [mm, dd] = draft[m[1]].split("-").map(Number);
      const month = m[2] === "m" ? +e.target.value : mm, day = m[2] === "d" ? +e.target.value : dd;
      draft[m[1]] = `${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    });
    $("#cancel").onclick = () => this._closeModal();
    if ($("#remove")) {
      $("#remove").onclick = async () => {
        $("#remove").disabled = true; $("#err").textContent = t("holSaving");
        try {
          await this._hass.callWS({ type: "celebright/holiday_custom_remove", device_id: dev.device_id, holiday_id: row.id });
          this._closeModal(); await this._load();
        } catch (err) { $("#err").textContent = (err && err.message) || "Failed"; $("#remove").disabled = false; }
      };
    }
    $("#save").onclick = async () => {
      const err = $("#err"); err.textContent = "";
      if (custom && !draft.name.trim()) { err.textContent = t("holNeedName"); return; }
      if (draft.kind === "playlist" ? !draft.playlist : !draft.scene) { err.textContent = t(draft.kind === "playlist" ? "holPickPlaylist" : "holPickScene"); return; }
      $("#save").disabled = true; err.className = "muted"; err.textContent = t("holSaving");
      try {
        let id = row && row.id;
        if (custom) {
          const res = await this._hass.callWS({ type: "celebright/holiday_custom_save", device_id: dev.device_id,
            ...(id ? { holiday_id: id } : {}), name: draft.name.trim(), start: draft.start, end: draft.end });
          id = res.holiday_id;
          if (!row) await this._load();   // the new holiday needs to be in the list before it is switched on
        }
        const current = (this._all[dev.device_id] || []).find((r) => r.id === id) || { id, before: 0, after: 0 };
        const failed = await this._save(dev, current, draft.kind === "playlist"
          ? { scene: null, playlist: draft.playlist, seconds: draft.seconds, shuffle: draft.shuffle, enabled: true, before: draft.before, after: draft.after }
          : { scene: draft.scene, enabled: true, before: draft.before, after: draft.after });
        if (failed) { err.className = "err"; err.textContent = failed; $("#save").disabled = false; return; }
        this._closeModal();
      } catch (e) {
        err.className = "err"; err.textContent = (e && e.message) || "Failed"; $("#save").disabled = false;
      }
    };
  }
}

const HOL_CSS = `
  .hols { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
  .hol { display: grid; gap: 6px; align-content: start; padding: 12px; border-radius: 14px; border: 1px solid var(--divider-color); background: var(--card-background-color);
         text-align: left; cursor: pointer; min-width: 0; }
  .hol:hover { background: var(--secondary-background-color); }
  .hol.on { border-color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 10%, transparent); }
  .hol-head { display: flex; align-items: center; gap: 8px; }
  .hol-head .name { flex: 1; min-width: 0; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hol .sub { font-size: 0.8rem; color: var(--secondary-text-color); }
  .hol-scene { display: grid; gap: 4px; font-size: 0.85rem; min-height: 32px; align-content: center; }
  .hol-scene .sname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--secondary-text-color); font-size: 0.8rem; }
  .notice { padding: 8px 12px; border-radius: 10px; font-size: 0.9rem; background: color-mix(in srgb, var(--primary-color) 14%, transparent); }
  .hol.add { place-content: center; justify-items: center; color: var(--secondary-text-color); border-style: dashed; min-height: 110px; }
  .hol.add ha-icon { --mdc-icon-size: 28px; }
  .grid.pick { max-height: 260px; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
  .warn { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 10px; border-radius: 10px; font-size: 0.85rem;
          color: var(--warning-color, #b26a00); background: color-mix(in srgb, var(--warning-color, #ff9800) 14%, transparent); }
  .warn span { flex: 1; min-width: 160px; }
  .warn ha-icon { --mdc-icon-size: 18px; flex: none; }
`;

// ---- Rules card --------------------------------------------------------------
// "Show this scene while something is true, then go back to the schedule": aurora, a switch, a
// sensor. Home Assistant watches the entities (see rule_engine.py), so rules only act while it runs.

Object.assign(EN, {
  rules: "Rules",
  ruleRefresh: "Refresh",
  ruleIntro: "Show a scene while something is true; the controller goes back to its schedule when it stops. The first rule in the list that is true wins. Home Assistant watches for these, so they only act while it is running.",
  ruleAdd: "Add a rule",
  ruleNone: "No rules yet. Start with the aurora alert below.",
  ruleStartFrom: "Start from",
  ruleName: "Name",
  ruleWhen: "When",
  ruleSensorAbove: "A sensor is above",
  ruleSensorBelow: "A sensor is below",
  ruleEntityState: "An entity is",
  ruleEntity: "Entity",
  ruleEntitySearch: "Search by name or entity id",
  ruleEntityShow: "Show entities",
  ruleNoMatch: "No match. You can still type an entity id.",
  ruleMore: "{n} more: keep typing to narrow it down",
  ruleNumber: "Number",
  ruleState: "State",
  ruleOnlyDark: "Only after dark",
  ruleDates: "Only between dates",
  ruleTimes: "Only between times",
  ruleMax: "Stop after (hours)",
  ruleScene: "Scene",
  ruleSave: "Save",
  ruleDelete: "Delete rule",
  ruleNow: "Now",
  ruleShowing: "Showing now",
  ruleWaiting: "Waiting",
  ruleUp: "Move up",
  ruleDown: "Move down",
  rulePresetAurora: "Aurora alert",
  rulePresetSwitch: "A switch is on",
  rulePresetSensor: "A sensor",
  ruleSaving: "Saving…",
  ruleLoadFail: "Couldn't load the rules.",
  ruleFrom: "From",
  ruleTo: "to",
});

const RULE_CSS = `
  .rule { display: flex; align-items: center; gap: 8px; padding: 10px; border-radius: 14px; border: 1px solid var(--divider-color); background: var(--card-background-color); cursor: pointer; }
  .rule:hover { background: var(--secondary-background-color); }
  .rule.off .body { opacity: .55; }
  .rule .body { flex: 1; min-width: 0; display: grid; gap: 4px; }
  .rule .name { font-weight: 500; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .rule .sub { font-size: 0.8rem; color: var(--secondary-text-color); overflow-wrap: anywhere; }
  .rule .hol-scene { max-width: 360px; }
  .rule .movers { display: grid; flex: none; }
  .rule .movers button { width: 28px; height: 24px; border: 0; background: transparent; color: var(--secondary-text-color); display: grid; place-items: center; padding: 0; }
  .rule .movers button[disabled] { opacity: .25; }
  .rule .movers ha-icon { --mdc-icon-size: 18px; }
  .rules { display: grid; gap: 8px; }
  .rchip { font-size: 0.72rem; font-weight: 500; padding: 1px 8px; border-radius: 999px; background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .combo { position: relative; }
  .combo input { padding-right: 40px; }
  .combo-btn { position: absolute; right: 2px; top: 0; width: 40px; height: 42px; border: 0; background: transparent; color: var(--secondary-text-color); display: grid; place-items: center; padding: 0; }
  .combo-list { position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 6; max-height: 260px; overflow: auto; overscroll-behavior: contain;
                background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 10px; box-shadow: 0 6px 20px rgba(0, 0, 0, .3); }
  .combo-list[hidden] { display: none; }
  .copt { display: grid; grid-template-columns: 1fr auto; gap: 0 10px; width: 100%; min-height: 44px; padding: 6px 12px; border: 0; background: transparent; color: var(--primary-text-color); text-align: left; align-items: center; }
  .copt.active, .copt:hover { background: var(--secondary-background-color); }
  .copt .cn { grid-column: 1; font-size: 0.95rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .copt .ci { grid-column: 1; font-size: 0.75rem; color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .copt .cs { grid-column: 2; grid-row: 1 / span 2; font-size: 0.82rem; color: var(--secondary-text-color); white-space: nowrap; max-width: 110px; overflow: hidden; text-overflow: ellipsis; }
  .cnone { padding: 10px 12px; color: var(--secondary-text-color); font-size: 0.88rem; }
  .rchip.applied { background: color-mix(in srgb, var(--success-color, #2e7d32) 18%, transparent); color: var(--success-color, #2e7d32); }
  .rchip.error { background: color-mix(in srgb, var(--error-color, #c62828) 15%, transparent); color: var(--error-color, #c62828); }
  .chips2 { display: flex; flex-wrap: wrap; gap: 6px; }
  .chips2 .btn { min-height: 34px; padding: 4px 12px; font-size: 0.85rem; }
  .sub-field { display: grid; gap: 8px; padding-left: 4px; }
  .checkline { display: flex; align-items: center; gap: 8px; font-size: 0.95rem; color: var(--primary-text-color); min-height: 34px; }
  .checkline input { width: 18px; height: 18px; flex: none; }
`;

class CelebrightRulesCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._info = null;
    this._all = null;
    this._presets = [];
    this._error = null;
    this._fetched = 0;
    this._modal = null;
    this.shadowRoot.innerHTML = `<style>${CSS}${HOL_CSS}${RULE_CSS}</style><ha-card><div class="card" id="root"></div></ha-card>`;
    this._root = this.shadowRoot.getElementById("root");
    this.shadowRoot.addEventListener("click", (e) => this._click(e));
    this.shadowRoot.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches(".rule")) { e.preventDefault(); this._click(e); }
    });
  }

  setConfig(config) {
    const changed = this._config && config.device !== this._config.device;
    this._config = { ...config };
    if (changed) this._load();
    this._paint();
  }

  getCardSize() { return 6; }
  getGridOptions() { return { columns: 12, min_columns: 6, rows: "auto" }; }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this.toggleAttribute("dark", hass.themes ? !!hass.themes.darkMode : window.matchMedia("(prefers-color-scheme: dark)").matches);
    if (first) this._load();
    // Whether a rule is showing changes as sensors do: ask again now and then while it is on screen.
    else if (!this.hidden && !this._modal && Date.now() - this._fetched > 20000) this._load();
    this._paint();
  }

  get _admin() {
    return !this._hass || !this._hass.user || this._hass.user.is_admin !== false;
  }

  _device() {
    const list = (this._info && this._info.devices) || [];
    const want = this._config && this._config.device;
    return (want && list.find((d) => d.ha_device_id === want || d.device_id === want)) || list[0] || null;
  }

  async _load() {
    if (this._loading || !this._hass) return;
    this._loading = true;
    this._fetched = Date.now();
    try {
      const [info, rules] = await Promise.all([
        this._hass.callWS({ type: "celebright/card_info" }),
        this._hass.callWS({ type: "celebright/rules" }),
      ]);
      this._info = info;
      this._all = rules.devices || {};
      this._presets = rules.presets || [];
      this._error = null;
    } catch (err) {
      this._error = (err && err.message) || t("ruleLoadFail");
    } finally {
      this._loading = false;
      this._paint();
    }
  }

  _rules(dev) {
    return (this._all && this._all[dev.device_id]) || [];
  }

  // The entity's current reading, for the list and the editor.
  _reading(entityId) {
    const s = this._hass.states[entityId];
    if (!s) return null;
    const unit = s.attributes && s.attributes.unit_of_measurement ? ` ${s.attributes.unit_of_measurement}` : "";
    return `${s.state}${["unknown", "unavailable"].includes(s.state) ? "" : unit}`;
  }

  _paint() {
    if (!this._config || !this._hass) return;
    if (!this._info || !this._all) {
      this._root.innerHTML = `<div class="msg">${esc(this._error || t("loading"))}</div>`;
      return;
    }
    const dev = this._device();
    if (!dev) { this._root.innerHTML = `<div class="msg">${t("noDevice")}</div>`; return; }
    const rules = this._rules(dev);
    const list = rules.length
      ? rules.map((r, i) => this._ruleHtml(dev, r, i, rules.length)).join("")
      : `<div class="muted">${t("ruleNone")}</div>`;
    const starters = this._admin
      ? `<div class="chips2">${rules.length ? "" : `<button class="btn primary" data-act="rule-new" data-preset="aurora"><ha-icon icon="mdi:weather-night"></ha-icon>${t("rulePresetAurora")}</button>`}
          <button class="btn ${rules.length ? "primary" : ""}" data-act="rule-new"><ha-icon icon="mdi:plus"></ha-icon>${t("ruleAdd")}</button></div>` : "";
    const markup = `<div class="head"><div class="title">${t("rules")}</div>
        <button class="icon" data-act="rule-reload" title="${t("ruleRefresh")}"><ha-icon icon="mdi:refresh"></ha-icon></button></div>
      <div class="muted">${t("ruleIntro")}</div><div class="rules">${list}</div>${starters}`;
    if (markup !== this._markup) {
      this._markup = markup;
      this._root.innerHTML = markup;
    }
  }

  _ruleHtml(dev, rule, index, total) {
    const scene = dev.scenes.find((s) => s.uuid === rule.scene);
    const st = rule.status || {};
    const chip = st.state === "applied" ? `<span class="rchip applied">${t("ruleShowing")}</span>`
      : st.state === "met" ? `<span class="rchip">${t("ruleWaiting")}</span>`
      : st.state === "error" ? `<span class="rchip error">${esc(st.message)}</span>` : "";
    const reading = this._reading(rule.when.entity_id);
    const moves = this._admin && total > 1
      ? `<div class="movers"><button data-act="rule-up" data-id="${esc(rule.id)}" title="${t("ruleUp")}" ${index === 0 ? "disabled" : ""}><ha-icon icon="mdi:chevron-up"></ha-icon></button>
          <button data-act="rule-down" data-id="${esc(rule.id)}" title="${t("ruleDown")}" ${index === total - 1 ? "disabled" : ""}><ha-icon icon="mdi:chevron-down"></ha-icon></button></div>` : "";
    return `<div class="rule ${rule.enabled ? "" : "off"}" role="button" tabindex="0" data-act="rule-open" data-id="${esc(rule.id)}">
      ${moves}
      <div class="body"><div class="name">${esc(rule.name)} ${chip}</div>
        <div class="sub">${esc(rule.summary)}${reading != null ? ` · ${t("ruleNow")}: ${esc(reading)}` : ""}</div>
        ${scene ? `<div class="hol-scene">${previewHtml(scene.preview)}<span class="sname">${esc(scene.name)}</span></div>` : ""}</div>
      ${this._admin ? `<button class="toggle ${rule.enabled ? "on" : ""}" data-act="rule-toggle" data-id="${esc(rule.id)}"></button>` : ""}
    </div>`;
  }

  // ---- actions ----------------------------------------------------------

  _click(event) {
    const el = event.target.closest("[data-act]");
    if (!el || !this._hass) return;
    const dev = this._device();
    const id = el.dataset.id;
    const rule = id ? this._rules(dev).find((r) => r.id === id) : null;
    switch (el.dataset.act) {
      case "rule-reload": this._load(); break;
      case "rule-toggle": event.stopPropagation(); this._save(dev, { ...rule, enabled: !rule.enabled }); break;
      case "rule-up": case "rule-down": event.stopPropagation(); this._move(dev, id, el.dataset.act === "rule-up" ? "up" : "down"); break;
      case "rule-open": if (this._admin && rule) this._openEditor(dev, rule); break;
      case "rule-new": this._openEditor(dev, null, el.dataset.preset); break;
    }
  }

  async _call(msg) {
    try {
      return [await this._hass.callWS(msg), null];
    } catch (err) {
      return [null, (err && err.message) || "Failed"];
    }
  }

  async _save(dev, rule) {
    const [updated, err] = await this._call({ type: "celebright/rule_save", device_id: dev.device_id, rule });
    if (err) return err;
    const list = this._all[dev.device_id];
    const at = list.findIndex((r) => r.id === updated.id);
    if (at >= 0) list[at] = updated; else list.push(updated);
    this._paint();
    this._load();   // other rules' status may have changed with this one
    return null;
  }

  async _move(dev, id, direction) {
    const [, err] = await this._call({ type: "celebright/rule_move", device_id: dev.device_id, rule_id: id, direction });
    if (!err) this._load();
  }

  // ---- the editor sheet --------------------------------------------------

  _closeModal() { if (this._modal) this._modal.remove(); this._modal = null; }

  _showModal(html) {
    this._closeModal();
    const modal = document.createElement("div");
    modal.className = "modal";
    modal.innerHTML = `<div class="sheet">${html}</div>`;
    modal.addEventListener("click", (e) => { if (e.target === modal) this._closeModal(); });
    this.shadowRoot.appendChild(modal);
    this._modal = modal;
    return modal;
  }

  _auroraEntity() {
    return Object.keys(this._hass.states).find((id) => id.startsWith("sensor.")
      && (/aurora/i.test(id) || /aurora/i.test(this._hass.states[id].attributes.friendly_name || ""))) || "";
  }

  _entityIds(type) {
    const numeric = ["sensor", "input_number", "number", "counter"];
    return Object.keys(this._hass.states)
      .filter((id) => type === "entity_state" ? !id.startsWith("automation.") && !id.startsWith("script.") && !id.startsWith("scene.") : numeric.includes(id.split(".")[0]))
      .sort();
  }

  _draftFrom(rule, presetId) {
    if (rule) {
      return {
        id: rule.id, name: rule.name, enabled: rule.enabled, scene: rule.scene, type: rule.when.type, entity_id: rule.when.entity_id,
        value: String(rule.when.value), only_dark: rule.only_dark,
        useDates: !!rule.dates, start: rule.dates ? rule.dates.start : "10-25", end: rule.dates ? rule.dates.end : "10-31",
        useTimes: !!rule.times, tstart: rule.times ? rule.times.start : "22:00", tend: rule.times ? rule.times.end : "06:00",
        useMax: !!rule.max_hours, hours: rule.max_hours ? String(rule.max_hours) : "3",
      };
    }
    const preset = this._presets.find((p) => p.id === presetId) || { name: "", when: { type: "sensor_above", value: 50 }, only_dark: false };
    return {
      id: null, name: preset.name, enabled: true, scene: null, type: preset.when.type,
      entity_id: presetId === "aurora" ? this._auroraEntity() : "", value: String(preset.when.value), only_dark: !!preset.only_dark,
      useDates: false, start: "10-25", end: "10-31", useTimes: false, tstart: "22:00", tend: "06:00", useMax: false, hours: "3",
    };
  }

  _openEditor(dev, rule, presetId) {
    const lang = this._hass.language;
    const draft = this._draftFrom(rule, presetId);
    const months = MONTHS_SHORT(lang);
    const monthDay = (field, value) => {
      const [m, d] = value.split("-").map(Number);
      return `<div class="two"><select data-f="${field}-m">${months.map((n, i) => `<option value="${i + 1}" ${i + 1 === m ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
        <select data-f="${field}-d">${Array.from({ length: 31 }, (_, i) => `<option value="${i + 1}" ${i + 1 === d ? "selected" : ""}>${i + 1}</option>`).join("")}</select></div>`;
    };
    const check = (field, label, on) => `<label class="checkline"><input type="checkbox" data-f="${field}" ${on ? "checked" : ""}>${label}</label>`;

    const modal = this._showModal("");
    const sheet = modal.querySelector(".sheet");

    const render = () => {
      const top = sheet.scrollTop;
      const sensorType = draft.type !== "entity_state";
      sheet.innerHTML = `<h2>${esc(rule ? rule.name : t("ruleAdd"))}</h2>
        ${rule ? "" : `<div class="field"><span>${t("ruleStartFrom")}</span><div class="chips2">
          <button class="btn" data-preset="aurora">${t("rulePresetAurora")}</button><button class="btn" data-preset="switch">${t("rulePresetSwitch")}</button><button class="btn" data-preset="sensor">${t("rulePresetSensor")}</button></div></div>`}
        <label class="field"><span>${t("ruleName")}</span><input data-f="name" maxlength="60" value="${esc(draft.name)}"></label>
        <label class="field"><span>${t("ruleWhen")}</span><select data-f="type">
          <option value="sensor_above" ${draft.type === "sensor_above" ? "selected" : ""}>${t("ruleSensorAbove")}</option>
          <option value="sensor_below" ${draft.type === "sensor_below" ? "selected" : ""}>${t("ruleSensorBelow")}</option>
          <option value="entity_state" ${draft.type === "entity_state" ? "selected" : ""}>${t("ruleEntityState")}</option></select></label>
        <div class="field"><span>${t("ruleEntity")}</span>
          <div class="combo" id="combo"><input data-f="entity_id" role="combobox" aria-autocomplete="list" aria-expanded="false" autocomplete="off" spellcheck="false" placeholder="${t("ruleEntitySearch")}" value="${esc(draft.entity_id)}">
            <button type="button" class="combo-btn" data-combo="toggle" tabindex="-1" aria-label="${t("ruleEntityShow")}"><ha-icon icon="mdi:menu-down"></ha-icon></button>
            <div class="combo-list" id="clist" role="listbox" hidden></div></div>
          <span class="hint" id="reading"></span></div>
        <label class="field"><span>${sensorType ? t("ruleNumber") : t("ruleState")}</span>
          <input data-f="value" ${sensorType ? 'type="number" step="any"' : 'placeholder="on"'} value="${esc(draft.value)}"></label>
        ${check("only_dark", t("ruleOnlyDark"), draft.only_dark)}
        ${check("useDates", t("ruleDates"), draft.useDates)}
        ${draft.useDates ? `<div class="two sub-field"><div class="field"><span>${t("ruleFrom")}</span>${monthDay("start", draft.start)}</div><div class="field"><span>${t("ruleTo")}</span>${monthDay("end", draft.end)}</div></div>` : ""}
        ${check("useTimes", t("ruleTimes"), draft.useTimes)}
        ${draft.useTimes ? `<div class="two sub-field"><label class="field"><span>${t("ruleFrom")}</span><input type="time" data-f="tstart" value="${esc(draft.tstart)}"></label>
          <label class="field"><span>${t("ruleTo")}</span><input type="time" data-f="tend" value="${esc(draft.tend)}"></label></div>` : ""}
        ${check("useMax", t("ruleMax"), draft.useMax)}
        ${draft.useMax ? `<div class="sub-field"><input type="number" min="0.25" max="48" step="any" data-f="hours" value="${esc(draft.hours)}"></div>` : ""}
        <div class="field"><span>${t("ruleScene")}</span><div class="grid pick" id="scenes">${dev.scenes.map((s) => `<button class="scene ${s.uuid === draft.scene ? "active" : ""}" data-uuid="${esc(s.uuid)}" title="${esc(s.name)}">
          <span class="row">${s.uuid === draft.scene ? '<ha-icon icon="mdi:check-circle"></ha-icon>' : ""}<span>${esc(s.name)}</span></span>${previewHtml(s.preview)}</button>`).join("")}</div></div>
        <div class="err" id="err"></div>
        <div class="actions">${rule ? `<button class="btn danger" id="remove">${t("ruleDelete")}</button>` : ""}
          <button class="btn" id="cancel">${t("cancel")}</button><button class="btn primary" id="save">${t("ruleSave")}</button></div>`;
      sheet.scrollTop = top;
      paintReading();
    };

    const paintReading = () => {
      const el = sheet.querySelector("#reading");
      if (!el) return;
      const reading = this._reading(draft.entity_id.trim().toLowerCase());
      el.textContent = reading == null ? "" : `${t("ruleNow")}: ${reading}`;
    };

    // ---- the searchable entity list: matches the id or the friendly name, shows the live state ----
    let active = -1;
    const combo = () => ({ input: sheet.querySelector('[data-f="entity_id"]'), list: sheet.querySelector("#clist") });
    const closeCombo = () => {
      const { input, list } = combo();
      if (list) list.hidden = true;
      if (input) input.setAttribute("aria-expanded", "false");
      active = -1;
    };
    const openCombo = (showAll) => {
      const { input, list } = combo();
      if (!input || !list) return;
      const q = showAll ? "" : input.value.trim().toLowerCase();
      const tokens = q.split(/\s+/).filter(Boolean);
      const rows = this._entityIds(draft.type).map((id) => {
        const name = (this._hass.states[id].attributes && this._hass.states[id].attributes.friendly_name) || "";
        return { id, name, hay: `${id} ${name}`.toLowerCase() };
      }).filter((c) => tokens.every((tk) => c.hay.includes(tk)));
      rows.sort((a, b) => (Number(b.id.startsWith(q)) - Number(a.id.startsWith(q))) || (a.name || a.id).localeCompare(b.name || b.id));
      const shown = rows.slice(0, 60);
      list.innerHTML = shown.length
        ? shown.map((c) => `<button type="button" class="copt" role="option" data-pick="${esc(c.id)}"><span class="cn">${esc(c.name || c.id)}</span><span class="ci">${esc(c.id)}</span><span class="cs">${esc(this._reading(c.id) || "")}</span></button>`).join("")
          + (rows.length > shown.length ? `<div class="cnone">${t("ruleMore").replace("{n}", rows.length - shown.length)}</div>` : "")
        : `<div class="cnone">${t("ruleNoMatch")}</div>`;
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      active = -1;
    };
    const pickEntity = (id) => {
      draft.entity_id = id;
      const { input } = combo();
      if (input) input.value = id;
      closeCombo();
      paintReading();
    };
    const moveActive = (step) => {
      const opts = [...sheet.querySelectorAll(".copt")];
      if (!opts.length) return;
      active = (active + step + opts.length) % opts.length;
      opts.forEach((o, i) => o.classList.toggle("active", i === active));
      opts[active].scrollIntoView({ block: "nearest" });
    };

    render();
    // An entity that is already chosen shows the whole list on focus (to change it); typing narrows the list.
    sheet.addEventListener("focusin", (e) => {
      if (e.target.matches && e.target.matches('[data-f="entity_id"]')) openCombo(!!this._hass.states[e.target.value.trim().toLowerCase()]);
    });
    sheet.addEventListener("keydown", (e) => {
      if (!e.target.matches || !e.target.matches('[data-f="entity_id"]')) return;
      const list = combo().list;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); if (list.hidden) openCombo(false); moveActive(e.key === "ArrowDown" ? 1 : -1); }
      else if (e.key === "Enter" && !list.hidden && active >= 0) { e.preventDefault(); pickEntity(sheet.querySelectorAll(".copt")[active].dataset.pick); }
      else if (e.key === "Escape" && !list.hidden) { e.preventDefault(); e.stopPropagation(); closeCombo(); }
      else if (e.key === "Tab") closeCombo();
    });
    sheet.addEventListener("input", (e) => {
      const f = e.target.dataset.f;
      if (!f) return;
      if (f === "name" || f === "entity_id" || f === "value" || f === "hours" || f === "tstart" || f === "tend") draft[f] = e.target.value;
      if (f === "entity_id") { paintReading(); openCombo(false); }
    });
    sheet.addEventListener("change", (e) => {
      const f = e.target.dataset.f || "";
      if (f === "type") { draft.type = e.target.value; if (draft.type === "entity_state" && !isNaN(parseFloat(draft.value))) draft.value = "on"; if (draft.type !== "entity_state" && isNaN(parseFloat(draft.value))) draft.value = "50"; render(); return; }
      if (["only_dark", "useDates", "useTimes", "useMax"].includes(f)) { draft[f] = e.target.checked; render(); return; }
      const m = /^(start|end)-(m|d)$/.exec(f);
      if (m) {
        const [mm, dd] = draft[m[1]].split("-").map(Number);
        const month = m[2] === "m" ? +e.target.value : mm, day = m[2] === "d" ? +e.target.value : dd;
        draft[m[1]] = `${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      }
    });
    sheet.addEventListener("click", async (e) => {
      const choice = e.target.closest("[data-pick]");
      if (choice) { pickEntity(choice.dataset.pick); return; }
      if (e.target.closest('[data-combo="toggle"]')) {
        const { input, list } = combo();
        if (list.hidden) { openCombo(true); input.focus({ preventScroll: true }); } else closeCombo();
        return;
      }
      if (!e.target.closest("#combo")) closeCombo();
      const preset = e.target.closest("[data-preset]");
      const scene = e.target.closest("[data-uuid]");
      if (preset) {
        const fresh = this._draftFrom(null, preset.dataset.preset);
        fresh.scene = draft.scene;
        Object.assign(draft, fresh);
        render();
        return;
      }
      if (scene) { draft.scene = scene.dataset.uuid; render(); return; }
      if (e.target.closest("#cancel")) { this._closeModal(); return; }
      if (e.target.closest("#remove")) {
        const btn = sheet.querySelector("#remove"); btn.disabled = true;
        const [, err] = await this._call({ type: "celebright/rule_delete", device_id: dev.device_id, rule_id: rule.id });
        if (err) { sheet.querySelector("#err").textContent = err; btn.disabled = false; return; }
        this._closeModal(); this._load();
        return;
      }
      if (e.target.closest("#save")) {
        const errEl = sheet.querySelector("#err"), btn = sheet.querySelector("#save");
        errEl.className = "muted"; errEl.textContent = t("ruleSaving"); btn.disabled = true;
        const payload = {
          id: draft.id || undefined, name: draft.name, enabled: draft.enabled, scene: draft.scene,
          when: { type: draft.type, entity_id: draft.entity_id, value: draft.value },
          only_dark: draft.only_dark,
          dates: draft.useDates ? { start: draft.start, end: draft.end } : null,
          times: draft.useTimes ? { start: draft.tstart, end: draft.tend } : null,
          max_hours: draft.useMax ? draft.hours : null,
        };
        const err = await this._save(dev, payload);
        if (err) { errEl.className = "err"; errEl.textContent = err; btn.disabled = false; return; }
        this._closeModal();
      }
    });
  }
}

// ---- Sidebar page ------------------------------------------------------------
// The page Home Assistant shows when "Show Celebright in the sidebar" is on: a header with
// three tabs (Control, Holidays, Rules) and, with several controllers, a picker.

Object.assign(EN, { control: "Control", panelTitle: "Celebright", menu: "Menu", controller: "Controller" });

// ---- Playlists card ----------------------------------------------------------
// Scene playlists (firmware 3.x): the controller cycles through a list of scenes. Play one with a
// time per scene, shuffle and an optional turn-off timer; make, edit and delete them here too.

Object.assign(EN, {
  playlists: "Playlists",
  plIntro: "A playlist cycles through several of your scenes. Play one now, or choose it for a scheduled event in the Celebright app.",
  plRefresh: "Refresh",
  plNone: "No playlists yet.",
  plAdd: "New playlist",
  plCount: "{n} scenes",
  plCountOne: "1 scene",
  plMore: "+{n} more",
  plNew: "New playlist",
  plName: "Name",
  plDescription: "Description (optional)",
  plScenes: "Scenes, in order",
  plAddScene: "Add a scene",
  plNoScenesYet: "No scenes yet. Add the first one below.",
  plMissing: "Removed scene",
  plDropped: "Scenes that no longer exist were taken out.",
  plPlayTitle: "Play",
  plSeconds: "Time per scene",
  plShuffle: "Shuffle",
  plTimer: "Turn off after",
  plTimerOff: "Runs until the next scheduled event",
  plTimerOn: "Turns off after the time below",
  plMinutes: "minutes",
  plNeedName: "Give the playlist a name.",
  plNeedScenes: "Add at least one scene.",
  plSaving: "Saving…",
  plStarting: "Starting…",
  plPlaying: "Playing",
  plDelete: "Delete playlist",
  plDeleteSure: "Tap again to delete",
  plNeedV3: "Playlists need a controller on firmware 3.x.",
  plReadOnly: "Only administrators can play or change playlists.",
  plLoadFail: "Couldn't load the playlists.",
  plUp: "Move up",
  plDown: "Move down",
  plRemoveScene: "Remove from the playlist",
});

const PL_CSS = `
  .pls { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
  .pl { display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; align-content: start; padding: 12px; border-radius: 14px; border: 1px solid var(--divider-color); background: var(--card-background-color);
        text-align: left; cursor: pointer; min-width: 0; }
  .pl:hover { background: var(--secondary-background-color); }
  .pl-head { display: flex; align-items: center; gap: 4px; }
  .pl-head .name { flex: 1; min-width: 0; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pl-head .icon { width: 34px; height: 34px; margin: -4px -6px -4px 0; }
  .pl .sub { font-size: 0.8rem; color: var(--secondary-text-color); }
  .pl-strips { display: grid; gap: 4px; }
  .pl.add { place-content: center; justify-items: center; color: var(--secondary-text-color); border-style: dashed; min-height: 110px; }
  .pl.add ha-icon { --mdc-icon-size: 28px; }
  .pllist { display: grid; gap: 6px; }
  .plrow { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 6px; align-items: center; padding: 6px 6px 8px 10px; border-radius: 10px; background: var(--secondary-background-color); }
  .plrow .pn { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.9rem; }
  .plrow .strip { grid-column: 1 / -1; }
  .plrow .btns { display: flex; }
  .plrow .btns .icon { width: 36px; height: 36px; }
  .offset[hidden] { display: none; }
  .range-row { display: flex; align-items: center; gap: 10px; }
  .range-row input[type=range] { flex: 1; }
  .notice { padding: 8px 12px; border-radius: 10px; font-size: 0.9rem; background: color-mix(in srgb, var(--primary-color) 14%, transparent); }
  .grid.pick { max-height: 220px; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
`;

const fmtSeconds = (n) => (n >= 60 ? `${Math.floor(n / 60)}m${n % 60 ? ` ${n % 60}s` : ""}` : `${n}s`);

class CelebrightPlaylistsCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._info = null;
    this._error = null;
    this._notice = "";
    this._modal = null;
    this.shadowRoot.innerHTML = `<style>${CSS}${PL_CSS}</style><ha-card><div class="card" id="root"></div></ha-card>`;
    this._root = this.shadowRoot.getElementById("root");
    this.shadowRoot.addEventListener("click", (e) => this._click(e));
    this.shadowRoot.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches(".pl")) { e.preventDefault(); this._click(e); }
    });
  }

  setConfig(config) {
    const changed = this._config && config.device !== this._config.device;
    this._config = { ...config };
    if (changed) this._load();
    this._paint();
  }

  getCardSize() { return 6; }
  getGridOptions() { return { columns: 12, min_columns: 6, rows: "auto" }; }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this.toggleAttribute("dark", hass.themes ? !!hass.themes.darkMode : window.matchMedia("(prefers-color-scheme: dark)").matches);
    if (first) this._load();
    this._paint();
  }

  get _admin() {
    return !this._hass || !this._hass.user || this._hass.user.is_admin !== false;
  }

  _device() {
    const list = (this._info && this._info.devices) || [];
    const want = this._config && this._config.device;
    return (want && list.find((d) => d.ha_device_id === want || d.device_id === want)) || list[0] || null;
  }

  async _load() {
    if (this._loading || !this._hass) return;
    this._loading = true;
    try {
      this._info = await this._hass.callWS({ type: "celebright/card_info" });
      this._error = null;
    } catch (err) {
      this._error = (err && err.message) || t("plLoadFail");
    } finally {
      this._loading = false;
      this._paint();
    }
  }

  _count(n) { return n === 1 ? t("plCountOne") : t("plCount").replace("{n}", n); }

  _paint() {
    if (!this._config || !this._hass) return;
    if (!this._info) {
      this._root.innerHTML = `<div class="msg">${esc(this._error || t("loading"))}</div>`;
      return;
    }
    const dev = this._device();
    if (!dev) { this._root.innerHTML = `<div class="msg">${t("noDevice")}</div>`; return; }
    if (!dev.v3) { this._root.innerHTML = `<div class="msg">${t("plNeedV3")}</div>`; return; }
    const list = dev.playlists || [];
    const add = this._admin ? `<button class="pl add" data-act="pl-add"><ha-icon icon="mdi:plus"></ha-icon>${t("plAdd")}</button>` : "";
    const markup = `<div class="head"><div class="title">${t("playlists")}</div>
        <button class="icon" data-act="pl-reload" title="${t("plRefresh")}"><ha-icon icon="mdi:refresh"></ha-icon></button></div>
      <div class="muted">${t("plIntro")}</div>
      ${this._notice ? `<div class="notice">${esc(this._notice)}</div>` : ""}
      ${this._admin ? "" : `<div class="muted">${t("plReadOnly")}</div>`}
      ${list.length || this._admin ? "" : `<div class="muted">${t("plNone")}</div>`}
      <div class="pls">${list.map((pl) => this._tileHtml(pl)).join("")}${add}</div>`;
    if (markup !== this._markup) {
      this._markup = markup;
      this._root.innerHTML = markup;
    }
  }

  _tileHtml(pl) {
    const strips = pl.scenes.slice(0, 4).map((s) => previewHtml(s.preview)).join("");
    const more = pl.scenes.length > 4 ? `<div class="sub">${t("plMore").replace("{n}", pl.scenes.length - 4)}</div>` : "";
    return `<div class="pl" role="button" tabindex="0" data-act="pl-open" data-id="${esc(pl.uuid)}">
      <div class="pl-head"><div class="name" title="${esc(pl.name)}">${esc(pl.name)}</div>
        ${this._admin ? `<button class="icon" data-act="pl-edit" data-id="${esc(pl.uuid)}" title="${t("edit")}"><ha-icon icon="mdi:pencil"></ha-icon></button>` : ""}</div>
      <div class="sub">${this._count(pl.scenes.length)}${pl.description ? ` · ${esc(pl.description)}` : ""}</div>
      <div class="pl-strips">${strips}</div>${more}
    </div>`;
  }

  _click(event) {
    const el = event.target.closest("[data-act]");
    if (!el || !this._hass) return;
    const dev = this._device();
    const pl = ((dev && dev.playlists) || []).find((p) => p.uuid === el.dataset.id);
    switch (el.dataset.act) {
      case "pl-reload": this._load(); break;
      case "pl-open": if (this._admin && pl) this._openPlay(dev, pl); break;
      case "pl-edit": event.stopPropagation(); if (pl) this._openEditor(dev, pl); break;
      case "pl-add": this._openEditor(dev, null); break;
    }
  }

  _closeModal() { if (this._modal) this._modal.remove(); this._modal = null; }

  _showModal(html) {
    this._closeModal();
    const modal = document.createElement("div");
    modal.className = "modal";
    modal.innerHTML = `<div class="sheet">${html}</div>`;
    modal.addEventListener("click", (e) => { if (e.target === modal) this._closeModal(); });
    this.shadowRoot.appendChild(modal);
    this._modal = modal;
    return modal;
  }

  // ---- play: time per scene, shuffle, optional turn-off timer ----

  _openPlay(dev, pl) {
    const draft = { secs: 30, shuffle: false, timer: false, mins: 60 };
    const modal = this._showModal(`<h2>${t("plPlayTitle")} “${esc(pl.name)}”</h2>
      <div class="field"><span>${t("plSeconds")}: <b id="secs-l">${fmtSeconds(draft.secs)}</b></span>
        <div class="range-row"><input type="range" min="5" max="300" step="5" data-f="secs" value="${draft.secs}"></div></div>
      <label class="check"><input type="checkbox" data-f="shuffle"> ${t("plShuffle")}</label>
      <label class="check"><input type="checkbox" data-f="timer"> ${t("plTimer")}</label>
      <div class="offset" id="timer-row" hidden><input type="number" min="5" max="1440" step="5" data-f="mins" value="${draft.mins}"><span>${t("plMinutes")}</span></div>
      <div class="muted" id="hint">${t("plTimerOff")}</div><div class="err" id="err"></div>
      <div class="actions"><button class="btn" id="cancel">${t("cancel")}</button><button class="btn primary" id="go">${t("plPlayTitle")}</button></div>`);
    const $ = (sel) => modal.querySelector(sel);
    modal.addEventListener("input", (e) => {
      const f = e.target.dataset.f;
      if (f === "secs") { draft.secs = parseInt(e.target.value, 10) || 30; $("#secs-l").textContent = fmtSeconds(draft.secs); }
      if (f === "mins") draft.mins = Math.max(1, Math.min(1440, parseInt(e.target.value, 10) || 60));
      if (f === "shuffle") draft.shuffle = e.target.checked;
      if (f === "timer") {
        draft.timer = e.target.checked;
        $("#timer-row").hidden = !draft.timer;
        $("#hint").textContent = draft.timer ? t("plTimerOn") : t("plTimerOff");
      }
    });
    $("#cancel").onclick = () => this._closeModal();
    $("#go").onclick = async () => {
      $("#go").disabled = true; $("#err").className = "muted"; $("#err").textContent = t("plStarting");
      try {
        await this._hass.callWS({
          type: "celebright/playlist_play", device_id: dev.device_id, playlist_id: pl.uuid,
          seconds: draft.secs, shuffle: draft.shuffle, ...(draft.timer ? { sleep_minutes: draft.mins } : {}),
        });
        this._closeModal();
        this._notice = `${t("plPlaying")} “${pl.name}”`;
        this._paint();
        clearTimeout(this._noticeTimer);
        this._noticeTimer = setTimeout(() => { this._notice = ""; this._paint(); }, 6000);
      } catch (err) {
        $("#err").className = "err"; $("#err").textContent = (err && err.message) || "Failed"; $("#go").disabled = false;
      }
    };
  }

  // ---- make and edit: a name, and the scenes in the order they play ----

  _openEditor(dev, pl) {
    const known = new Set(dev.scenes.map((s) => s.uuid));
    const kept = pl ? pl.scenes.map((s) => s.uuid).filter((u) => known.has(u)) : [];
    const draft = { name: pl ? pl.name : "", desc: pl && pl.description ? pl.description : "", scenes: kept };
    const dropped = pl ? pl.scenes.length - kept.length : 0;
    let sure = false;
    const modal = this._showModal(`<h2>${esc(pl ? pl.name : t("plNew"))}</h2>
      <label class="field"><span>${t("plName")}</span><input data-f="name" maxlength="60" value="${esc(draft.name)}"></label>
      <label class="field"><span>${t("plDescription")}</span><input data-f="desc" maxlength="200" value="${esc(draft.desc)}"></label>
      <div class="field"><span>${t("plScenes")}</span><div class="pllist" id="list"></div>${dropped ? `<span class="hint">${t("plDropped")}</span>` : ""}</div>
      <div class="field"><span>${t("plAddScene")}</span><div class="grid pick" id="pool"></div></div>
      <div class="err" id="err"></div>
      <div class="actions">${pl ? `<button class="btn danger" id="remove">${t("plDelete")}</button>` : ""}
        <button class="btn" id="cancel">${t("cancel")}</button><button class="btn primary" id="save">${t("save")}</button></div>`);
    const $ = (sel) => modal.querySelector(sel);
    const byUuid = (u) => dev.scenes.find((s) => s.uuid === u);
    const paintList = () => {
      $("#list").innerHTML = draft.scenes.length ? draft.scenes.map((u, i) => {
        const s = byUuid(u);
        return `<div class="plrow"><span class="pn" title="${esc(s.name)}">${i + 1}. ${esc(s.name)}</span>
          <span class="btns"><button class="icon" data-i="${i}" data-m="up" title="${t("plUp")}" ${i === 0 ? "disabled" : ""}><ha-icon icon="mdi:arrow-up"></ha-icon></button>
          <button class="icon" data-i="${i}" data-m="down" title="${t("plDown")}" ${i === draft.scenes.length - 1 ? "disabled" : ""}><ha-icon icon="mdi:arrow-down"></ha-icon></button>
          <button class="icon" data-i="${i}" data-m="del" title="${t("plRemoveScene")}"><ha-icon icon="mdi:close"></ha-icon></button></span>${previewHtml(s.preview)}</div>`;
      }).join("") : `<div class="muted">${t("plNoScenesYet")}</div>`;
    };
    const paintPool = () => {
      $("#pool").innerHTML = dev.scenes.map((s) => `<button class="scene" data-uuid="${esc(s.uuid)}" title="${esc(s.name)}">
        <span class="row"><span>${esc(s.name)}</span></span>${previewHtml(s.preview)}</button>`).join("");
    };
    paintList(); paintPool();
    $("#pool").addEventListener("click", (e) => {
      const b = e.target.closest("[data-uuid]");
      if (b) { draft.scenes.push(b.dataset.uuid); paintList(); $("#list").lastElementChild.scrollIntoView({ block: "nearest" }); }
    });
    $("#list").addEventListener("click", (e) => {
      const b = e.target.closest("[data-m]");
      if (!b) return;
      const i = +b.dataset.i;
      if (b.dataset.m === "del") draft.scenes.splice(i, 1);
      else {
        const j = b.dataset.m === "up" ? i - 1 : i + 1;
        if (j >= 0 && j < draft.scenes.length) [draft.scenes[i], draft.scenes[j]] = [draft.scenes[j], draft.scenes[i]];
      }
      paintList();
    });
    modal.addEventListener("input", (e) => {
      if (e.target.dataset.f === "name") draft.name = e.target.value;
      if (e.target.dataset.f === "desc") draft.desc = e.target.value;
    });
    $("#cancel").onclick = () => this._closeModal();
    if ($("#remove")) {
      $("#remove").onclick = async () => {
        if (!sure) { sure = true; $("#remove").textContent = t("plDeleteSure"); return; }
        $("#remove").disabled = true; $("#err").className = "muted"; $("#err").textContent = t("plSaving");
        try {
          await this._hass.callWS({ type: "celebright/playlist_delete", device_id: dev.device_id, playlist_id: pl.uuid });
          this._closeModal(); await this._load();
        } catch (err) {
          $("#err").className = "err"; $("#err").textContent = (err && err.message) || "Failed"; $("#remove").disabled = false;
        }
      };
    }
    $("#save").onclick = async () => {
      const err = $("#err"); err.className = "err"; err.textContent = "";
      if (!draft.name.trim()) { err.textContent = t("plNeedName"); return; }
      if (!draft.scenes.length) { err.textContent = t("plNeedScenes"); return; }
      $("#save").disabled = true; err.className = "muted"; err.textContent = t("plSaving");
      try {
        await this._hass.callWS({
          type: "celebright/playlist_save", device_id: dev.device_id, ...(pl ? { playlist_id: pl.uuid } : {}),
          name: draft.name.trim(), description: draft.desc.trim() || null, scenes: draft.scenes,
        });
        this._closeModal(); await this._load();
      } catch (e) {
        err.className = "err"; err.textContent = (e && e.message) || "Failed"; $("#save").disabled = false;
      }
    };
  }
}

const PANEL_CSS = `
  :host { display: block; min-height: 100%; background: var(--primary-background-color); color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif); }
  :host([dark]) { color-scheme: dark; }
  *, *::before, *::after { box-sizing: border-box; }
  header { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; gap: 4px 8px; flex-wrap: wrap;
           padding: calc(env(safe-area-inset-top, 0px) + 6px) calc(env(safe-area-inset-right, 0px) + 12px) 0 calc(env(safe-area-inset-left, 0px) + 12px);
           background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, var(--text-primary-color, #fff)); }
  header .title { font-size: 1.25rem; font-weight: 500; margin-right: 8px; flex: none; }
  header button, header select { font: inherit; color: inherit; }
  .menu { width: 44px; height: 44px; border: 0; border-radius: 50%; background: transparent; display: grid; place-items: center; flex: none; }
  .menu:hover { background: rgba(255, 255, 255, .15); }
  .tabs { display: flex; gap: 4px; flex: 1 1 auto; min-width: 0; }
  .tab { min-height: 44px; padding: 0 16px; border: 0; border-bottom: 3px solid transparent; background: transparent; opacity: .75; cursor: pointer; }
  .tab.active { opacity: 1; border-bottom-color: currentColor; }
  .pick { min-height: 36px; margin-bottom: 4px; padding: 0 10px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, .5); background: rgba(0, 0, 0, .15); max-width: 100%; }
  .pick option { color: #000; }
  main { padding: 16px calc(env(safe-area-inset-right, 0px) + 16px) calc(env(safe-area-inset-bottom, 0px) + 16px) calc(env(safe-area-inset-left, 0px) + 16px); }
  main > [hidden] { display: none; }
  @media (max-width: 600px) {
    header .title { flex: 1; }
    .pick { order: 2; }
    .tabs { order: 3; flex: 1 0 100%; overflow-x: auto; scrollbar-width: none; }
    .tab { flex: 1 0 auto; padding: 0 6px; font-size: 0.9rem; white-space: nowrap; }
  }
  @media (max-width: 600px) { main { padding: 8px calc(env(safe-area-inset-right, 0px) + 8px) calc(env(safe-area-inset-bottom, 0px) + 8px) calc(env(safe-area-inset-left, 0px) + 8px); } }
`;

class CelebrightPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._narrow = false;
    this._devices = [];
    this._tab = "control";
    try { const saved = localStorage.getItem("celebright-panel-tab"); this._tab = ["holidays", "rules", "playlists"].includes(saved) ? saved : "control"; } catch (e) { /* storage blocked */ }
    this.shadowRoot.innerHTML = `<style>${PANEL_CSS}</style><header id="head"></header><main id="main"></main>`;
    this._head = this.shadowRoot.getElementById("head");
    this._main = this.shadowRoot.getElementById("main");
    this._card = document.createElement("celebright-card");
    this._hol = document.createElement("celebright-holidays-card");
    this._rules = document.createElement("celebright-rules-card");
    this._pl = document.createElement("celebright-playlists-card");
    this._card.setConfig({});
    this._hol.setConfig({});
    this._rules.setConfig({});
    this._pl.setConfig({});
    this._main.append(this._card, this._hol, this._rules, this._pl);
    this.shadowRoot.addEventListener("click", (e) => this._click(e));
    this.shadowRoot.addEventListener("change", (e) => this._change(e));
    this._paintHead();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this.toggleAttribute("dark", hass.themes ? !!hass.themes.darkMode : window.matchMedia("(prefers-color-scheme: dark)").matches);
    this._card.hass = hass;
    this._hol.hass = hass;
    this._rules.hass = hass;
    this._pl.hass = hass;
    if (first) this._loadDevices();
  }

  set narrow(narrow) {
    this._narrow = !!narrow;
    this._paintHead();
  }

  set panel(_panel) { /* no configuration */ }
  set route(_route) { /* a single page */ }

  async _loadDevices() {
    try {
      const info = await this._hass.callWS({ type: "celebright/card_info" });
      this._devices = (info && info.devices) || [];
    } catch (err) {
      this._devices = []; // the card shows its own message about this
    }
    if (this._devices.length > 1) {
      let saved = null;
      try { saved = localStorage.getItem("celebright-panel-device"); } catch (e) { /* storage blocked */ }
      this._device = this._devices.some((d) => d.device_id === saved) ? saved : this._devices[0].device_id;
      this._card.setConfig({ device: this._device });
      this._hol.setConfig({ device: this._device });
      this._rules.setConfig({ device: this._device });
      this._pl.setConfig({ device: this._device });
    }
    this._paintHead();
  }

  // Playlists exist on firmware 3.x only, so the tab appears only for such a controller.
  _hasPlaylists() {
    const dev = this._devices.find((d) => d.device_id === this._device) || this._devices[0];
    return !!(dev && dev.v3);
  }

  _paintHead() {
    const picker = this._devices.length > 1
      ? `<select class="pick" data-f="device" aria-label="${t("controller")}">${this._devices.map((d) =>
        `<option value="${esc(d.device_id)}" ${d.device_id === this._device ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select>`
      : "";
    const playlists = this._hasPlaylists();
    const active = this._tab === "playlists" && !playlists ? "control" : this._tab;
    const tab = (id, label) => `<button class="tab ${active === id ? "active" : ""}" data-act="tab" data-tab="${id}">${esc(label)}</button>`;
    this._head.innerHTML = `${this._narrow ? `<button class="menu" data-act="menu" title="${t("menu")}"><ha-icon icon="mdi:menu"></ha-icon></button>` : ""}
      <div class="title">${t("panelTitle")}</div>
      <div class="tabs">${tab("control", t("control"))}${tab("holidays", t("holidays"))}${tab("rules", t("rules"))}${playlists ? tab("playlists", t("playlists")) : ""}</div>${picker}`;
    this._card.hidden = active !== "control";
    this._hol.hidden = active !== "holidays";
    this._rules.hidden = active !== "rules";
    this._pl.hidden = active !== "playlists";
  }

  _click(event) {
    const el = event.target.closest("[data-act]");
    if (!el) return;
    if (el.dataset.act === "menu") {
      this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
    } else if (el.dataset.act === "tab") {
      this._tab = el.dataset.tab;
      try { localStorage.setItem("celebright-panel-tab", this._tab); } catch (e) { /* storage blocked */ }
      this._paintHead();
    }
  }

  _change(event) {
    if (event.target.dataset.f !== "device") return;
    this._device = event.target.value;
    try { localStorage.setItem("celebright-panel-device", this._device); } catch (e) { /* storage blocked */ }
    this._card.setConfig({ device: this._device });
    this._hol.setConfig({ device: this._device });
    this._rules.setConfig({ device: this._device });
    this._pl.setConfig({ device: this._device });
    this._paintHead();
  }
}

if (!customElements.get("celebright-card")) customElements.define("celebright-card", CelebrightCard);
if (!customElements.get("celebright-automations-card")) customElements.define("celebright-automations-card", CelebrightAutomationsCard);
if (!customElements.get("celebright-holidays-card")) customElements.define("celebright-holidays-card", CelebrightHolidaysCard);
if (!customElements.get("celebright-playlists-card")) customElements.define("celebright-playlists-card", CelebrightPlaylistsCard);
if (!customElements.get("celebright-rules-card")) customElements.define("celebright-rules-card", CelebrightRulesCard);
if (!customElements.get("celebright-panel")) customElements.define("celebright-panel", CelebrightPanel);
if (!customElements.get("celebright-card-editor")) customElements.define("celebright-card-editor", CelebrightCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "celebright-card")) {
  window.customCards.push({
    type: "celebright-card",
    name: "Celebright",
    description: "Power, colour, scenes and the schedule of a Celebright controller.",
    preview: false,
    documentationURL: "https://github.com/MrToast99/Celebright_ha",
  });
}
if (!window.customCards.some((c) => c.type === "celebright-holidays-card")) {
  window.customCards.push({
    type: "celebright-holidays-card",
    name: "Celebright holidays",
    description: "Pick a scene for each holiday; it runs on the controller, and Home Assistant updates it to next year's dates.",
    preview: false,
    documentationURL: "https://github.com/MrToast99/Celebright_ha",
  });
}
if (!window.customCards.some((c) => c.type === "celebright-rules-card")) {
  window.customCards.push({
    type: "celebright-rules-card",
    name: "Celebright rules",
    description: "Show a scene while something is true (aurora, a switch, a sensor), then go back to the schedule.",
    preview: false,
    documentationURL: "https://github.com/MrToast99/Celebright_ha",
  });
}
if (!window.customCards.some((c) => c.type === "celebright-playlists-card")) {
  window.customCards.push({
    type: "celebright-playlists-card",
    name: "Celebright playlists",
    description: "Play, make and edit scene playlists (controllers on firmware 3.x).",
    preview: false,
    documentationURL: "https://github.com/MrToast99/Celebright_ha",
  });
}
if (!window.customCards.some((c) => c.type === "celebright-automations-card")) {
  window.customCards.push({
    type: "celebright-automations-card",
    name: "Celebright automations",
    description: "Your Celebright blueprint automations: switch, run and edit them.",
    preview: false,
    documentationURL: "https://github.com/MrToast99/Celebright_ha",
  });
}
console.info(`%c CELEBRIGHT-CARD %c ${CARD_VERSION} `, "color:#fff;background:#ff5a1f;font-weight:700", "color:#ff5a1f");
