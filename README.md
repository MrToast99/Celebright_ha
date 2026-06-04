# Celebright for Home Assistant

A custom [Home Assistant](https://www.home-assistant.io/) integration for **Celebright** permanent / architectural LED lighting (CLC-series controllers).

Control your lights, activate saved scenes, view your built-in lighting schedule, and drive everything from Home Assistant automations.

> **Status:** early release (`0.2.0`). Cloud-based. Tested against the `app.celebright.ca` backend and a CLC-03 controller.

![GitHub Downloads (all assets, latest release)](https://img.shields.io/github/downloads/MrToast99/Celebright_ha/latest/total)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/MrToast99/Celebright_ha/total?label=downloads%40total)

Like the work? Help keep me Caffeinated!
[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/mrtoast99)

---

## Features

| Capability | Entity | Notes |
|---|---|---|
| On / off | `light.*` | "Off" resumes the controller's schedule |
| Solid colour | `light.*` | RGB colour picker |
| Brightness | `light.*` | 0–255, scales the active colour |
| Scene selection | `select.*` | All saved scenes from your account + **Off** |
| Current display | `sensor.*` | Live — shows the active scene or "Off" |
| Schedule status | `binary_sensor.*` | On when the device schedule is enabled |
| Schedule events | `sensor.*` | Count + full decoded event list in attributes |
| Device info | `sensor.*` | Model, firmware, hardware rev, LED count (+ per‑string), bulb type, colour order, location |

Plus a ready-to-use **3‑view dashboard** and **example automations**.

---

## How it works

Celebright has no local API — control flows through their AWS cloud:

```
Home Assistant
   │
   ├─ Auth ........ AWS Cognito (email + password) → ID token + temp AWS creds
   │
   ├─ State ....... REST poll to app-api.celebright.com  (every 30 s)
   │                 • getUserData            → devices, scenes, schedule
   │                 • getUserDeviceStatuses  → on/off, current display
   │
   └─ Control ..... AWS IoT MQTT over WebSocket (SigV4-signed)
                     • setColor          {"color": "RRGGBB"}
                     • loadSavedScene    {"savedSceneUuid": "..."}
                     • setResumeSchedule {}
```

Because it is cloud-based, the integration is `iot_class: cloud_polling` and requires an internet connection.

---

## Requirements

- Home Assistant **2024.1** or newer
- A Celebright account (the same email/password you use in the Celebright app)
- Your Celebright controller online and registered to that account

---

## Installation

### Option A — HACS (custom repository)

1. In Home Assistant, open **HACS → Integrations**.
2. Click the **⋮** menu (top right) → **Custom repositories**.
3. Add the repository URL `https://github.com/MrToast99/Celebright_ha` with category **Integration**.
4. Find **Celebright** in the list and click **Download**.
5. **Restart Home Assistant.**

### Option B — Manual

1. Download or clone this repository.
2. Copy the folder `custom_components/celebright` into your Home Assistant
   config directory so the path is:
   ```
   <config>/custom_components/celebright/
   ```
   On a typical install `<config>` is `/config` (Home Assistant OS / Container)
   or `~/.homeassistant` (Core).
3. **Restart Home Assistant.**

After restarting, the folder should look like:

```
<config>/custom_components/celebright/
├── __init__.py
├── manifest.json
├── config_flow.py
├── coordinator.py
├── const.py
├── entity.py
├── light.py
├── select.py
├── sensor.py
├── binary_sensor.py
├── strings.json
├── brand/                 (icon.png, logo.png, @2x variants)
└── api/
    ├── auth.py            (Cognito authentication)
    ├── cloud.py           (REST polling + schedule decoding)
    ├── mqtt.py            (AWS IoT MQTT control)
    └── base.py            (shared data types)
```

---

## Configuration

1. Go to **Settings → Devices & Services → + Add Integration**.
2. Search for **Celebright**.
3. Enter the **email** and **password** for your Celebright account.
4. Click **Submit**.

The integration validates the credentials against Cognito, then creates one
Home Assistant **device** per Celebright controller on the account, each with
its light, scene selector, schedule, and info entities.

> Credentials are stored by Home Assistant in its encrypted config entry store.
> They are sent only to Celebright/AWS endpoints, exactly as the official app does.

---

## Entities

For a controller named **House**, you get:

| Entity ID | Type | Purpose |
|---|---|---|
| `light.house` | light | On/off, RGB colour, brightness |
| `select.house_scene` | select | Pick a saved scene, or **Off** |
| `sensor.house_current_display` | sensor | Active scene / "Off" |
| `binary_sensor.house_schedule` | binary_sensor | Schedule enabled? |
| `sensor.house_scheduled_events` | sensor | Event count (+ list in attributes) |
| `sensor.house_model` | sensor | e.g. `CLC-03` |
| `sensor.house_firmware` | sensor | e.g. `2.05` |
| `sensor.house_hardware_version` | sensor | e.g. `Rev 4` |
| `sensor.house_led_count` | sensor | e.g. `125` (per-string counts in attributes) |
| `sensor.house_bulb_type` | sensor | e.g. `SC24-GEN1` |
| `sensor.house_color_order` | sensor | e.g. `RGBW (24V Natural White)` |
| `sensor.house_location` | sensor | e.g. `Springfield, Illinois` |

> Replace `house` with your device's slug if it is named differently. Find the
> exact IDs under **Settings → Devices & Services → Entities**.

---

## Dashboard setup

A complete dashboard is provided in [`celebright_dashboard.yaml`](celebright_dashboard.yaml).

1. In Home Assistant: **Settings → Dashboards → + Add Dashboard** → name it
   "Celebright", choose **New dashboard from scratch**.
2. Open it → **⋮ (top right) → Edit Dashboard → ⋮ → Raw configuration editor**.
3. Delete the placeholder content, paste the entire contents of
   `celebright_dashboard.yaml`, and **Save**.

The dashboard has three views:

- **Lights** — status, device info, colour/brightness picker, and a scene dropdown.
- **Schedule** — schedule on/off, a live table of every scheduled event (event, scene, when, time window), and a *Resume Schedule* button.
- **Automations** — deep-link buttons to create/manage automations in HA's editor.

The scene list, schedule table, and device info are all **read live from your
account** — nothing is hard-coded, so the dashboard works as-is for any
Celebright user. The default dashboard uses **only built-in cards** (no HACS
required).

> **Entity names:** the YAML assumes the device slug `house` (`light.house`,
> `select.house_scene`, …). If your device is named differently, search-replace
> `house` in the YAML with your slug.

### Optional dynamic cards (require HACS frontend cards)

These are **not** in the default dashboard (to keep it dependency-free). Add them
only if you have the corresponding HACS card installed — otherwise a card showing
`Custom element doesn't exist` means that card isn't installed.

**One-tap scene buttons** — a button per scene, generated live from your account.
Needs [`config-template-card`](https://github.com/iantrich/config-template-card).
Add to the **Lights** view:

```yaml
- type: custom:config-template-card
  entities:
    - select.house_scene
  variables:
    options: states['select.house_scene'].attributes.options || []
  card:
    type: grid
    columns: 4
    cards: >
      ${ options.map(o => ({
           type: 'button', name: o,
           icon: o === 'Off' ? 'mdi:calendar-clock' : 'mdi:lightbulb-on',
           tap_action: { action: 'perform-action',
             perform_action: 'select.select_option',
             target: { entity_id: 'select.house_scene' },
             data: { option: o } }
         })) }
```

**Live list of your Celebright automations** — auto-lists every automation whose
entity ID starts with `automation.celebright_` (all the bundled examples do, since
their aliases begin with "Celebright"). Needs
[`auto-entities`](https://github.com/thomasloven/lovelace-auto-entities). Add to
the **Automations** view:

```yaml
- type: custom:auto-entities
  card:
    type: entities
    title: Celebright Automations
    state_color: true
  filter:
    include:
      - entity_id: automation.celebright_*
  show_empty: false
```

> **Why not hard-code automation entities?** An automation's `entity_id` is
> derived from its **alias** (e.g. alias "Celebright Halloween in October" →
> `automation.celebright_halloween_in_october`), not from its `id`. Renaming an
> automation changes its entity ID, so a hard-coded list goes stale — which is
> why the default Automations view links to the editor instead.

---

## Automations

Five examples are in [`celebright_automations.yaml`](celebright_automations.yaml):

| Automation | What it does |
|---|---|
| Scene at sunset | A holiday scene at sunset during December |
| Lights off late night | Resumes schedule at 11:30 PM |
| Halloween in October | A scene at sunset, second half of October |
| Party toggle | Flips to a scene from an `input_boolean` helper |
| Offline notify | Notifies if the controller goes unavailable |

> The scene names in the file are **placeholders** (`REPLACE WITH YOUR SCENE
> NAME`) — set them to your own saved scenes (the names in the scene dropdown).

There are two ways to add them, and they need **different formats**:

### Option A — File include (use the file as-is)

`celebright_automations.yaml` is a YAML **list**, which is exactly what an
`!include` expects.

**1. Put the file in your config directory** — the same folder as
`configuration.yaml` (this is `/config/` on Home Assistant OS / Container, or
`~/.homeassistant/` on Core). The result must be:

```
/config/configuration.yaml
/config/celebright_automations.yaml      ← right next to it, NOT in a subfolder
```

> The filename must be **exactly** `celebright_automations.yaml` — all lowercase,
> ending in `.yaml` with **no** hidden `.txt` (Windows often adds one). The path
> in the `!include` is relative to `configuration.yaml`, so the file has to sit
> beside it. The easiest way to avoid copy/encoding problems is to create the
> file directly with the **File editor** add-on (📄+ icon) and paste the contents
> in.

**2. Add the include to `configuration.yaml`** (at the far left, column 0). If you
already have an `automation:` line, add this on the next line — the word after
`automation` is just a unique label:

```yaml
automation: !include automations.yaml            # may already exist
automation celebright: !include celebright_automations.yaml
```

**3. Apply it:** Developer Tools → YAML → **Check Configuration** (must pass),
then **Reload Automations**.

> Getting `Unable to read file /config/celebright_automations.yaml`? The file
> isn't where the include expects it — re-check step 1 (wrong folder, a hidden
> `.txt`, or a capitalised name).

### Option B — Paste a single automation in the UI

> ⚠️ **Do not paste the whole file** into the automation editor — it's a list,
> and you'll get `Message malformed: extra keys not allowed @ data['0']`.

Settings → Automations → **Create automation → ⋮ → Edit in YAML**, then paste a
**single** automation as a plain mapping — **no leading `-`, no `id:` line**:

```yaml
alias: Celebright scene at sunset
description: ""
triggers:
  - trigger: sun
    event: sunset
conditions:
  - condition: template
    value_template: "{{ now().month == 12 }}"
actions:
  - action: select.select_option
    target:
      entity_id: select.house_scene
    data:
      option: "REPLACE WITH YOUR SCENE NAME"
mode: single
```

---

## The schedule

Your Celebright schedule runs on the controller itself. This integration
**reads** it for display *and* can **create** new scheduled events.

- Time codes are decoded for readability: `Sunset`, `Sunrise`, `Midnight`, or `HH:MM`.
- Recurrence is shown in plain English: *"Every December 31"*, *"1st Sunday of November"*, *"Oct 27 – Oct 28 (seasonal)"*.
- Selecting a scene in HA temporarily **overrides** the schedule; **Off / Resume Schedule** hands control back to it.

### Creating events — `celebright.create_event` service

Add a scheduled event from Home Assistant (Developer Tools → Actions, or an automation):

```yaml
action: celebright.create_event
data:
  name: Christmas
  scene: "Candy Cane"        # a saved scene name (or its UUID)
  start_date: "2026-12-01"
  end_date: "2026-12-02"
  start_time: sunset          # sunset | sunrise | midnight | HH:MM
  end_time: sunrise
  priority: 3                 # 1–4, higher wins on overlap
  frequency: 1                # 1 = one-time/seasonal, 4 = yearly
  repeat_until: "2026-12-30"  # optional seasonal window end
```

For a **yearly event on a fixed date** add `by_month` + `by_month_day`
(e.g. December 31). For a **yearly nth-weekday** event (e.g. 1st Sunday of
November) add `by_month`, `by_day: SU`, and `by_set_pos: 1`.

The event appears in the Celebright app and on the controller exactly as if you
had created it there — the integration computes the same content hash the app
uses, so it syncs cleanly.

### Updating and deleting events

```yaml
# Update an existing event in place (identify by event_name or event_uuid)
action: celebright.update_event
data:
  event_name: "Christmas"        # or: event_uuid: "<uuid>"
  name: "Christmas"
  scene: "Candy Cane"
  start_date: "2026-12-01"
  end_date: "2026-12-31"
  start_time: sunset
  end_time: "23:00"
```

```yaml
# Delete an event
action: celebright.delete_event
data:
  event_name: "Christmas"        # or: event_uuid: "<uuid>"
```

Event UUIDs are listed in the **`sensor.<device>_scheduled_events`** attributes
if you prefer to target them precisely.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **Invalid authentication** during setup | Re-check email/password in the Celebright app. The account must already exist. |
| Entities show **Unavailable** | Controller is offline, or the cloud is unreachable. Check the device in the Celebright app. |
| Dashboard shows **"Entity not found"** | Your device slug isn't `house`. Check **Settings → Entities** and update the entity IDs in the YAML. |
| Turn-on / scene change fails with **403** | A transient AWS credential/clock issue; it should refresh on the next attempt. Open an issue if it persists. |
| Automations view lists missing automations | Import `celebright_automations.yaml`, or edit the list in the dashboard YAML. |

To get detailed logs, add to `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.celebright: debug
```

---

## Limitations

- **Cloud-only** — requires internet; there is no local control path.
- **Schedule:** events can be **created, updated, and deleted** from HA. Toggling the whole schedule on/off isn't wired up yet.
- **Solid colour** uses the `setColor` command; advanced per-bulb patterns are activated via **saved scenes**, not built ad-hoc from HA.
- Unofficial: this integration is **not affiliated with or endorsed by Celebright** and was built by inspecting the app's own network traffic. The cloud API may change without notice.

---

## Contributing

Issues and pull requests are welcome at
<https://github.com/MrToast99/Celebright_ha>.

If you hit a feature the app supports but this integration doesn't (e.g. editing
schedules, custom patterns), a HAR capture of the action from the
Celebright web app is the fastest way to add it.

---

## Disclaimer

This is a community project provided **as-is**, with no warranty. Use at your
own risk. "Celebright" and related marks belong to their respective owners.
