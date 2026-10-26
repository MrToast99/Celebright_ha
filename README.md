# Celebright for Home Assistant

A custom [Home Assistant](https://www.home-assistant.io/) integration for **Celebright** permanent / architectural LED lighting (CLC-series controllers). Control your lights, activate saved scenes, manage the built-in schedule, and automate it all from Home Assistant.

> **Status:** `0.3.2`, cloud-based. Tested against the `app.celebright.ca` backend and a CLC-03 controller.

![GitHub Downloads (all assets, latest release)](https://img.shields.io/github/downloads/MrToast99/Celebright_ha/latest/total)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/MrToast99/Celebright_ha/total?label=downloads%40total)

Like the work? Help keep me Caffeinated!
[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/mrtoast99)

---

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
  - [HACS (custom repository)](#hacs-custom-repository)
  - [Manual](#manual)
- [Configuration](#configuration)
- [Entities](#entities)
- [Dashboard](#dashboard)
  - [Optional cards (need HACS frontend cards)](#optional-cards-need-hacs-frontend-cards)
- [Automations](#automations)
  - [Manual automations (YAML)](#manual-automations-yaml)
- [The schedule](#the-schedule)
  - [Create an event](#create-an-event)
  - [Update, delete, enable/disable](#update-delete-enabledisable)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer)

---

## Features

| Capability | Entity | Notes |
|---|---|---|
| On / off | `light.*` | |
| Solid colour, brightness | `light.*` | RGB picker, 0–255 |
| Scene selection | `select.*`, `scene.*` | Your saved scenes (a dropdown and one scene entity each), plus **Off** (resume the schedule) |
| Current display, active event, next event | `sensor.*` | Live |
| Schedule on/off | `switch.*`, `binary_sensor.*` | |
| Schedule events | `sensor.*` | Count + decoded list; create / edit / delete / enable via services |
| Device info | `sensor.*` | Model, firmware, hardware, LED count, bulb type, colour order, location |

Plus a generated **dashboard** and ready-made automation **blueprints**.

---

## How it works

Celebright has no local API; everything goes through its AWS cloud:

```
Home Assistant
  ├─ Login ...... AWS Cognito (SRP; your password is never sent) → tokens + temporary AWS credentials
  ├─ Status ..... REST (devices, scenes, schedule) + AppSync GraphQL (live state), polled every 30 s
  └─ Control .... AWS IoT MQTT over WebSocket
```

Newer controllers (firmware 3.x) use a newer MQTT protocol ("v3"); older ones use "v2". The integration detects which one each controller speaks. It is `cloud_polling` and needs an internet connection.

---

## Requirements

- Home Assistant **2024.1** or newer
- A Celebright account (the email and password you use in the Celebright app)
- A controller that is online and registered to that account

---

## Installation

### HACS (custom repository)

1. **HACS → Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/MrToast99/Celebright_ha` with category **Integration**.
3. Find **Celebright**, click **Download**, then **restart Home Assistant**.

### Manual

Copy `custom_components/celebright` into your config folder (`<config>/custom_components/celebright/`; `<config>` is `/config` on Home Assistant OS / Container) and restart.

---

## Configuration

1. **Settings → Devices & Services → + Add Integration → Celebright**.
2. Enter your Celebright email and password.

One Home Assistant **device** is created per controller. Credentials are stored in Home Assistant's config entry store and sent only to Celebright/AWS endpoints, as the official app does. If the password later stops working, Home Assistant shows a **Re-authenticate** prompt.

---

## Entities

For a controller named **House**:

| Entity ID | Purpose |
|---|---|
| `light.house` | On/off, RGB colour, brightness |
| `select.house_scene` | Pick a saved scene, or **Off** (resume the schedule) |
| `scene.house_<scene name>` | One per saved scene: activate it from automations, scripts, dashboards or voice. Listed on a separate "Scenes" sub-device, not the main device page. Appears and disappears as you add and delete scenes in the app |
| `sensor.house_current_display` | Active scene, or "Off" |
| `sensor.house_active_event` | Scheduled event playing now (`None` if none) |
| `sensor.house_next_event_start` | When the next event starts (controller's local time) |
| `sensor.house_active_source` | What drives the lights: `off`, `user_display`, … (diagnostic) |
| `switch.house_schedule_enabled` | Turn the built-in schedule on / off (firmware 2.x only) |
| `binary_sensor.house_schedule` | Schedule on: the controller's flag, or "has scheduled events" on newer firmware |
| `sensor.house_scheduled_events` | Event count; the list is in the attributes |
| `sensor.house_model`, `_firmware`, `_hardware_version`, `_led_count`, `_bulb_type`, `_color_order`, `_location` | Device info |
| `button.house_refresh_scenes` | Re-pull scenes and schedule from your account |

Replace `house` with your device's slug if it is named differently (see **Settings → Devices & Services → Entities**).

---

## Dashboard

The integration generates a ready-made dashboard (built-in cards only) with **your** entity IDs and device name, so there is nothing to edit.

1. **Developer Tools → Actions → `Celebright: Generate dashboard`** → run. It writes `celebright_dashboard.yaml` to your config folder (`filename` changes the name; with several controllers pass `device_id`).
2. Use it one of two ways:
   - **YAML dashboard (recommended).** Add this to `configuration.yaml`, restart, and open **Celebright** in the sidebar (the key needs a hyphen, e.g. `celebright-lights`):

     ```yaml
     lovelace:
       dashboards:
         celebright-lights:
           mode: yaml
           title: Celebright
           icon: mdi:string-lights
           show_in_sidebar: true
           filename: celebright_dashboard.yaml
     ```

   - **Storage dashboard.** **Settings → Dashboards → + Add Dashboard → New dashboard from scratch**, open it → **⋮ → Edit Dashboard → ⋮ → Raw configuration editor**, paste the file's contents, **Save**.
3. After updating the integration, run the action again (a YAML dashboard shows the new file on refresh). Nothing to find-and-replace.

Views: **Lights** (status, colour/brightness, scene dropdown), **Schedule** (next event, on/off, event table, resume button) and **Automations** (links to HA's editor). Scenes, schedule and device info are read live from your account.

### Optional cards (need HACS frontend cards)

Not in the default dashboard. A card showing `Custom element doesn't exist` means that card isn't installed.

**One-tap scene buttons** ([`config-template-card`](https://github.com/iantrich/config-template-card)), added to the Lights view (replace `house` with your device's slug: **Settings → Devices & Services → Entities**, the part before `_scene`):

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

**Live list of your Celebright automations** ([`auto-entities`](https://github.com/thomasloven/lovelace-auto-entities)), added to the Automations view. It lists every `automation.celebright_*`; an automation's entity ID follows its alias, which is why the default view links to the editor instead.

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

---

## Automations

Automations come as **blueprints**: you pick your controller and scenes from dropdowns, with nothing to edit (needs Home Assistant 2024.10+). Click **Import**, then **Settings → Automations & Scenes → Blueprints →** the blueprint **→ Create automation**. Re-import a blueprint to get updates.

| Blueprint | What it does | |
|---|---|---|
| **Holiday lighting controller** | One automation for New Year fireworks, an optional aurora alert, Halloween (Oct 25–31), December and week-long holidays (St. Patrick's, Canada Day, Canadian Thanksgiving, Remembrance Day, Easter Monday, Truth and Reconciliation), plus four **custom holidays** of your own (any date range, even across New Year). Leave a holiday's scene empty to skip it. | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMrToast99%2FCelebright_ha%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fcelebright%2Fholiday_lighting_controller.yaml) |
| **Scene at sunset during a date range** | A scene every night from sunset inside a yearly date range (may cross New Year); resumes the schedule at sunrise. | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMrToast99%2FCelebright_ha%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fcelebright%2Fscene_in_date_range.yaml) |
| **Scene for a holiday week** | A scene dusk to dawn for the Monday-Sunday week containing a date, every year. | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMrToast99%2FCelebright_ha%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fcelebright%2Fscene_for_holiday_week.yaml) |
| **Scene on a toggle** | A scene while an `input_boolean` is on; resumes the schedule when it turns off. | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMrToast99%2FCelebright_ha%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fcelebright%2Fscene_toggle.yaml) |
| **Resume the schedule at a time** | Hands control back to the schedule at a set time each day. | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMrToast99%2FCelebright_ha%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fcelebright%2Fresume_schedule_at_time.yaml) |
| **Controller offline notification** | Runs an action (a notification by default) when the controller has been unavailable for a while. | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMrToast99%2FCelebright_ha%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fcelebright%2Fcontroller_offline_notify.yaml) |

- **Timing:** a week-long holiday runs Monday to Sunday around its date. Under **Adjust holiday timing** you can extend each by up to 14 days before or after, and move Halloween's first and last day. To shorten or move a holiday, leave its scene empty and use a custom holiday. Overlapping holidays resolve by priority: New Year, aurora, custom 1–4, Halloween, December, then the week-long ones.
- Scenes are picked from your saved scenes (each one is a `scene.*` entity). Resuming the schedule uses the controller's scene dropdown, so pick it too.
- Use the holiday controller **instead of** the date-range / holiday-week blueprints for the same lights; they would compete.
- No import button? Paste the blueprint's GitHub URL into **Blueprints → Import Blueprint**. The files are in [`blueprints/automation/celebright`](blueprints/automation/celebright).

### Manual automations (YAML)

Prefer plain YAML to blueprints? [`celebright_automations.yaml`](celebright_automations.yaml) holds the same ideas as a list of automations: a holiday lighting controller, scene at sunset, Halloween, holiday week, party toggle, offline notification and lights off late at night. Two edits first:

- **Slug:** the entity IDs use `house` (`select.house_scene`, `light.house`) because the reference controller is named House. Find and replace `house` with your own slug: **Settings → Devices & services → Entities**, search `celebright`, and take the part between the dot and `_scene` (`select.front_yard_scene` → `front_yard`).
- **Scene names:** replace every `REPLACE WITH YOUR SCENE NAME` with a scene exactly as it appears in the scene dropdown.

Then add it one of two ways (they need different formats):

**A. Include the file (use it as-is).** Put it next to `configuration.yaml` (e.g. `/config/celebright_automations.yaml`, lowercase, ending in `.yaml`), then add this at the far left of `configuration.yaml`. If you already have an `automation:` line, add it on the next line; the word after `automation` is just a label:

```yaml
automation: !include automations.yaml            # may already exist
automation celebright: !include celebright_automations.yaml
```

Run **Developer Tools → YAML → Check Configuration**, then **Reload Automations**. `Unable to read file …` means the file isn't beside `configuration.yaml` (wrong folder, a hidden `.txt`, or a capital letter).

**B. Paste one automation into the UI.** The file is a list, so pasting all of it gives `extra keys not allowed @ data['0']`. In **Create automation → ⋮ → Edit in YAML**, paste a single automation as a plain mapping, with no leading `-` and no `id:` line:

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

Use the file's holiday controller **instead of** its simpler seasonal examples for the same lights; they would compete.

---

## The schedule

The schedule runs on the controller itself. The integration shows it and can **create, edit, delete and enable/disable** events.

- Times read as `Sunset`, `Sunrise` (with an offset like `Sunset +30 min` on newer controllers), `Midnight` or `HH:MM`; recurrence reads as *"Every December 31"* or *"1st Sunday of November"*.
- Selecting a scene overrides the schedule; **Off** resumes it.
- Features marked **v3** need a newer (firmware 3.x) controller: event offsets, per-event enable/disable, and "once" events.

### Create an event

```yaml
action: celebright.create_event
data:
  name: Christmas
  scene: "Candy Cane"          # a saved scene name or UUID
  start_date: "2026-12-01"
  end_date: "2026-12-02"
  start_time: sunset            # sunset | sunrise | midnight | HH:MM
  end_time: sunrise
  priority: 3                   # 1–4, higher wins on overlap
  repeat_until: "2026-12-30"    # repeat daily until this date
  # frequency: 1                # 0 = once (v3), 1 = daily (until repeat_until or forever), 4 = yearly
  # start_offset_minutes: 30    # v3: shift a sunset/sunrise time
  # enabled: false              # v3: create it switched off
```

- **Frequency:** if omitted, you get a once-only event on v3, or daily until `repeat_until` when that is set. Older controllers repeat daily (until `repeat_until`, or forever).
- **Yearly:** a fixed date needs `by_month` + `by_month_day`; an nth weekday (e.g. 1st Sunday of November) needs `by_month`, `by_day: SU`, `by_set_pos: 1`.
- **Time zone:** dates and times use **Home Assistant's** time zone; keep it the same as the controller's.
- The event appears in the Celebright app as if created there (same content hash).

### Update, delete, enable/disable

```yaml
action: celebright.update_event     # keeps the enabled state unless you pass `enabled`
data:
  event_name: "Christmas"           # or event_uuid: "<uuid>"
  name: "Christmas"
  scene: "Candy Cane"
  start_date: "2026-12-01"
  end_date: "2026-12-31"
  start_time: sunset
  end_time: "23:00"
```

```yaml
action: celebright.delete_event
data:
  event_name: "Christmas"           # or event_uuid: "<uuid>"
```

```yaml
action: celebright.set_event_enabled   # v3
data:
  event_name: "Christmas"
  enabled: false
```

Event UUIDs are in the `sensor.<device>_scheduled_events` attributes. On v3 each service confirms the result by reading the event back from your account, so a change that didn't take effect is reported as an error.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **Invalid authentication** | Re-check the email/password in the Celebright app. |
| **Re-authenticate** prompt | Your password changed; enter the new one. |
| Entities **Unavailable** | The controller is offline or the cloud is unreachable; check it in the Celebright app. |
| **"Entity not found"** on the dashboard | Re-run **Generate dashboard**. In the manual automations file, replace the `house` slug (see **Manual automations**). |
| Commands do nothing | Enable debug logging (below); the log names the failing command. A *"not acknowledged"* warning means the controller is online but didn't confirm it. |
| **403** on a command | A transient AWS credential/clock issue; it retries. Open an issue if it persists. |

Debug logging:

```yaml
logger:
  default: warning
  logs:
    custom_components.celebright: debug
```

---

## Limitations

- **Cloud-only**: there is no local control path.
- **Newer (v3) controllers:** no schedule switch (the firmware has no such command; switch individual events with `celebright.set_event_enabled`), and scene create/delete isn't supported yet.
- **Patterns:** advanced per-bulb patterns are started from **saved scenes**, not built from HA.
- **Unofficial:** not affiliated with or endorsed by Celebright; built from the app's own network traffic, so the cloud API may change without notice.

---

## Contributing

Issues and pull requests are welcome at <https://github.com/MrToast99/Celebright_ha>. If the app does something this integration doesn't, a HAR capture of that action is the fastest way to add it (it holds live tokens, so share it privately).

---

## Disclaimer

A community project provided **as-is**, with no warranty. "Celebright" and related marks belong to their owners.
