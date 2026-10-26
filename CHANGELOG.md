# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [0.3.2] - pending

### Upgrading from 0.3.1
Update in HACS and restart. Nothing needs re-creating: existing holiday automations keep working, and the new inputs use their defaults until you set them (edit the automation to use them).

### Added
- **Holiday controller:** built-in **Halloween** (Oct 25–31), four **custom holidays** (a scene plus any start and end date, may cross New Year), and optional **timing adjustments** (up to 14 extra days before or after each week-long holiday, and Halloween's first and last day).
- **`celebright_automations.yaml` is back**, with its manual guide in the README (include it, or paste one automation), for those who prefer plain YAML to blueprints.

## [0.3.1] - 2026-10-26

### Upgrading from 0.3.0
Update in HACS and restart. Automations made from the Celebright blueprints need re-creating: their inputs changed (see below). Import the blueprints again, create the automation, and delete the old one. Nothing else changes; the new scene entities appear on their own.

### Added
- **Scene entities:** every saved scene gets a `scene.*` entity (activate it from automations, scripts, dashboards or voice). They follow the scenes in your account: new ones appear and deleted ones go on the next refresh. They sit on a "<device> Scenes" sub-device, so the controller's page shows one *Connected device* link instead of a long list; they are named after the controller (e.g. `scene.house_candy_cane`).

### Changed
- **Blueprints pick scenes from dropdowns** (the scene entities) instead of asking you to type scene names. The *Resume-schedule option* input is gone; resuming always uses the scene dropdown's **Off**.
- **The holiday controller's rules and triggers are named** (e.g. "Canada Day week", "Sunset"), so the automation editor and traces no longer show "Option 1, Option 2…".

## [0.3.0] - 2026-10-26

### Upgrading from 0.2.x
**Quick steps**
1. In HACS, update **Celebright** to 0.3.0 and restart Home Assistant. Nothing else is required; your entities, login and automations carry over.
2. If Home Assistant asks you to re-authenticate (**Settings → Devices & services → Celebright**), enter your Celebright password.
3. *Optional, to get the new sensors:* run **Developer Tools → Actions → `Celebright: Generate dashboard`** and use the file it writes as your dashboard (see **Dashboard** in the README). Back up your edited `celebright_dashboard.yaml` first.
4. *Optional:* swap copied automations for the blueprints (see **Automations** in the README). Disable the old automation first.

Existing dashboards and automations keep working: entity IDs, the saved login and the services are unchanged, and your copied YAML files aren't touched. Things to know:
- **New entities** (Active Event, Next Event Start, Active Source, and a Schedule switch on firmware 2.x) don't appear on a copied dashboard. Run `celebright.generate_dashboard` to get them; it writes `celebright_dashboard.yaml` in your config folder, so back up an edited copy or pass another `filename`.
- **`binary_sensor.<device>_schedule`** on firmware 3.x now reads *on* when the account has scheduled events (it was always *off*). Check any automation that depends on it.
- **The scene dropdown follows the controller's real scene**, and updates within seconds. Automations triggered by it or by `Current Display` can now fire when you change the scene in the Celebright app.
- **Firmware 3.x** controllers now work. `light.turn_off` there turns the lights off; to hand control back to the schedule, pick **Off** in the scene dropdown. Firmware 2.x is unchanged (`turn_off` resumes the schedule).
- **Schedule services** now raise real errors (no response, change not applied, login rejected) instead of failing quietly.
- `celebright_automations.yaml` and `celebright_dashboard.yaml` are gone from the repository, replaced by blueprints and `generate_dashboard`. Disable an old copied holiday automation before using the holiday blueprint, or the two will compete.

### Added
- **Automation blueprints** replace `celebright_automations.yaml`: holiday lighting controller (holiday scenes and the aurora alert optional), scene in a date range, scene for a holiday week, scene on a toggle, resume the schedule at a time, and controller-offline notification. Pick your controller and type scene names in a form; no slug or placeholders to edit. Import from the README.
- **`celebright.generate_dashboard`:** writes the dashboard with your real entity IDs and device name (found by unique ID, so renamed entities work). The `house` find-and-replace is gone; after an update, run the action again. The dashboard template now ships inside the integration, replacing the root `celebright_dashboard.yaml`.
- **Re-authentication prompt** when Celebright rejects the saved login (e.g. a changed password), at startup or while running. Only a rejected login triggers it. Adds `translations/en.json`.
- **Schedule editing on v3 (firmware 3.x):** `create_event`, `update_event` and `delete_event` use the app's event format and checksum. Each write waits for the controller's `databaseWrite` ack and is then confirmed by reading the event back from your account; a change that didn't take effect is reported as an error. Verified against the app's own traffic. v2 is unchanged.
- **`celebright.set_event_enabled`**, plus optional `start_offset_minutes`, `end_offset_minutes` and `enabled` on create/update (v3). `frequency: 0` means once.
- The **Scheduled Events** sensor reads v3 events (anchors, offsets, RRULE, per-event `enabled`) and falls back to the legacy list.
- **Schedule switch** (`switch.<device>_schedule_enabled`) for firmware 2.x. Firmware 3.x rejects `setEnableSchedule` ("Unrecognized topic"), so the switch isn't created there (an earlier one is removed) and the dashboard leaves it out; use `celebright.set_event_enabled` per event instead.
- Chunked controller replies (`msgChunk`) are reassembled. v3 commands are confirmed from `commandAck`, and a `failure` ack is reported with the controller's detail. A command the controller reports as unrecognized (`logDeviceError`) fails immediately with its message.
- **AppSync (GraphQL) status**, the app's own status call: one request per poll gives live colour, active scene, active event and next event time, so the scene dropdown follows the controller's real scene. MQTT `systemState` is the automatic fallback (5-minute back-off). The access token is tried first, then the id token; failures are logged with the real message.
- Sensors **Active Event**, **Next Event Start** and **Active Source**; the dashboard shows the next event.
- Status refreshes ~1.5 s after a command so it sees the new state.

### Changed
- Setup errors are logged with the underlying cause, not just `cannot_connect`.

### Fixed
- **Write confirmation** follows the real acks: event writes wait for the `databaseWrite` phase, so a failure after "accepted" is reported. A first-phase ack alone still counts as success.
- **Pattern brightness:** v3 patterns have no colour, so their brightness was dropped. It is now read for every look (0–255).
- **Unacknowledged commands** (brightness, resume schedule) are checked against the controller's reported state where possible, raise if it contradicts them, and otherwise warn once per command. An online-but-silent controller no longer causes a false error; an offline one still does.
- **Startup:** a connection error during setup makes HA retry automatically, a rejected login stops retrying, and any failure after connecting closes the HTTP session instead of leaking it.
- **`frequency`:** `1` means *daily* (until `repeat_until`, or forever), not "one-time"; service descriptions corrected. On v3, omitting it gives a once-only event, or daily until `repeat_until`.
- **"Off" on v3:** the scene dropdown's *Off* sends `setResumeSchedule` (as the app does); the light's turn-off uses `turnOff`. v2 is unchanged.
- **Brightness on v3** is sent as its own value: dimming a scene keeps the scene, a colour change keeps the brightness, and turn-on restores both. v2 still bakes it into the colour.
- **Scene selection on v3** uses the payload the app sends (confirmed from its code).
- **Setup failed with `cannot_connect` for everyone** ([#1](https://github.com/MrToast99/Celebright_ha/issues/1)): Celebright disabled `USER_PASSWORD_AUTH`. Login now uses `USER_SRP_AUTH` like the app (pure stdlib, no new dependencies).
- **Lights couldn't be turned on, with nothing logged:** firmware 3.x uses `v3` MQTT topics and silently ignores `v2`. The protocol is now detected per controller (v3, then v2), so old and new firmware both work.
- **v3 commands no longer fail silently:** the integration waits for the controller's reply and raises "the controller did not respond…" otherwise. `setColor` sends the `source` field, and v3 `systemState` is parsed for colour and brightness.
- **Service schema rejected GUI input:** the `frequency` selector submits strings; `frequency`, `priority` and the `by_*` fields now coerce to int.
- **hassfest:** removed `aiohttp` from the manifest `requirements`; it ships with Home Assistant itself.
- **Integration failed to load:** `button.py` imported a non-existent `ButtonEntityClass` (now `ButtonDeviceClass`).
- **Light colour/brightness were never reported:** MQTT state is now read for powered-on devices, and a slow device no longer fails the poll.
- **Scene dropdown ignored the device's real scene:** the device-reported scene now wins over the local selection.
- **MQTT receive loops** spun until their timeout on a dropped connection; they now stop immediately.
- Stale device info after a refresh, a leaked HTTP session on failed setup, and a blocking-import warning on first load.
- **Schedule binary sensor** works on newer firmware (reads *on* when the controller has events).
- **Holiday controller:** the sunset trigger could pick the daytime branch and hand control back to the device schedule until midnight. A 30-minute re-check also stops the device's own schedule overriding the active scene overnight.
- Schedule service failures surface as normal Home Assistant errors.

## [0.2.2] - 2026-09-04

### Fixed
- Corrected MQTT bug.



## [0.2.1]

### Added
- **Schedule management:** `celebright.create_event`, `update_event` and `delete_event` write events over MQTT as the app does, including its checksum.
- `celebright.refresh_scenes` service and a **Refresh Scenes** button; scenes and schedule also refresh every 30 minutes.
- Scheduled events exposed as a sensor with per-event `uuid`, scene, recurrence and time window.
- Account-agnostic dashboard (`celebright_dashboard.yaml`, no custom cards) and example automations.
- GitHub workflows for HACS validation, hassfest and release packaging.

### Changed
- Scene lists are built from your account on first login instead of shipped with the integration.

## [0.1.0] - 2026-06-03

### Added
- Initial release: the CLC-03 controller as a light (on/off, RGB, brightness), scene selector, status/diagnostic sensors and a schedule binary sensor. REST polling with control over AWS IoT MQTT.