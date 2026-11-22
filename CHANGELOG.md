# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [0.4.1] - 2026-11-22

### Upgrading
**From 0.4.0:** update, restart Home Assistant, refresh your browser once. Nothing else to do.

**From 0.3.3 or older:** follow the **migration guide in the 0.4.0 entry below**. It still applies, and 0.4.1 includes everything in 0.4.0.

### Changed
- **The Holidays tab explains when the dates move.** It now says that Home Assistant checks every few hours and at startup, and moves each holiday's event to next year's dates once the holiday has passed. The wording before could be read as the Celebright cloud doing it. The README explains the same, including that Home Assistant only has to be running at some point after each holiday, not during it.
- **Rules: the Entity field is a searchable dropdown.** Click it (or its arrow) to see your sensors, switches and other entities with their live state, type to narrow the list by name or entity id, and pick with the mouse, a tap or the arrow keys and Enter. A sensor rule lists numeric entities only; an entity-state rule lists everything. You can still type an entity id that isn't listed.

## [0.4.0] - 2026-11-22

### Migration guide: 0.3.3 → 0.4.0

**Short version:** update, restart Home Assistant, refresh your browser. Your entities, login, automations and scenes carry over untouched. Everything new is optional, and nothing is removed from your Home Assistant.

#### Before you update
- **Home Assistant 2024.10 or newer is required** (the blueprints already needed it). On an older version the update isn't offered.
- If you edited `celebright_dashboard.yaml` and want to keep your edits, copy the file somewhere safe. Nothing overwrites it until *you* regenerate the dashboard.

#### Update
1. **Marketplace (Home Assistant 2026.11+):** **Settings → Updates → Celebright → Install**. **HACS (2026.10 and older):** update **Celebright** in HACS.
2. **Restart Home Assistant** (a repair offers a button).
3. **Refresh your browser** once (Ctrl+F5, or clear the app cache in the Companion app) so it loads the new card.

#### After you update
| What | What to do |
|---|---|
| **Sidebar page** | New installs get a **Celebright** item in the sidebar. Yours keeps it **off**; turn it on at **Settings → Devices & services → Celebright → Configure → Show Celebright in the sidebar**. This is the easiest way to get everything below. |
| **Holidays** (new) | Set your holidays on the sidebar page's **Holidays** tab. If you use the *holiday lighting controller* blueprint, **switch it off** once you've set the same holidays there, or the two will compete. |
| **Aurora and other "while something is true" scenes** | The blueprint's aurora alert and the *scene on a toggle* blueprint are replaced by the **Rules** tab (its **Aurora alert** starter takes a minute). Recreate them there *before* you switch the blueprint off. |
| **Your dashboard** | Unchanged. To get the new cards on a generated dashboard, run **Developer Tools → Actions → `Celebright: Generate dashboard`** again (it rewrites `celebright_dashboard.yaml`). A YAML dashboard has no card picker: add `type: custom:celebright-card` yourself, ideally in a **panel** view. The generated dashboard is now three full-width views (**Control**, **Holidays**, **Rules**); the old **Lights**, **Schedule** and **Automations** views are gone. |
| **Old YAML** | If you still use `celebright_automations.yaml` or the old dashboard file, see "Removing the old YAML" in the README. Don't run the old holiday YAML next to the Holidays tab. |
| **Blueprints and the Automations tab** | Your blueprint automations still work and stay in **Settings → Automations & Scenes**. The *holiday lighting controller*, *date range*, *holiday week* and *scene on a toggle* blueprints are superseded by Holidays and Rules but not removed. There is no Automations tab on the sidebar page any more (a saved Automations tab choice falls back to Control). |

#### If something goes wrong
- The card doesn't show: open `/celebright_static/celebright-card.js` on your Home Assistant address (it should show JavaScript), hard-refresh, then check the README's "The card isn't showing up?" steps.
- You can go back: in the Marketplace or HACS, open Celebright, choose the version menu and pick **0.3.3**. New data (holiday and rule settings) is kept in Home Assistant's storage and simply ignored by 0.3.3. Delete the `Holiday: …` events from the Celebright app if you no longer want them. Also remove the `/celebright_static/celebright-card.js` resource under **Settings → Dashboards → Resources** (0.4.0 added it; 0.3.3 doesn't serve it).

### Added
- **The Celebright card** (`custom:celebright-card`), see the README:
  - Power, brightness and colour.
  - A searchable scene list with **colour previews** (solid colour, pattern palette or individual bulbs) and **Resume schedule**.
  - The schedule, with a form to add, edit, delete and switch events on and off.
  - Light and dark themes, two columns when wide, and a phone layout where the editor becomes a bottom sheet.
- **The automations card** (`custom:celebright-automations-card`, same file): your blueprint-based automations grouped by blueprint, each with a switch, **Run now**, last run and **Edit**, a **Create** button for blueprints you haven't used (not for the superseded ones, which show only if you still have an automation from them), and a warning when two holiday controllers are both on. It is for dashboards of your own; it isn't on the sidebar page or the generated dashboard.
- **Holidays** (`custom:celebright-holidays-card`, and a tab on the sidebar page): a tile for each holiday with a scene picker and colour previews, extra days before and after, and your own holidays. Each holiday is one event on the controller named `Holiday: <name>` holding the next occurrence's real dates (nightly, sunset to midnight), and the same event is updated to next year's dates by the integration (in Home Assistant, not the cloud) once its window has passed. This replaces the controller's yearly repeat rules, which can't express a moving holiday (Thanksgiving, Easter Monday) or a window around the date. It keeps working if Home Assistant is offline, only touches events it created, and warns if the holiday lighting blueprint is also on. Settings are stored in Home Assistant; commands `celebright/holidays`, `holiday_set`, `holiday_custom_save` and `holiday_custom_remove`.
- **Rules** (`custom:celebright-rules-card`, and a tab on the sidebar page): show a scene while something is true, then return to the schedule. When: a sensor is above or below a number, or an entity is in a state. Limits: only after dark, between dates, between times, stop after N hours. Rules are a priority list; an **Aurora alert** starter finds your aurora sensor and presets 75 and "only after dark". The scene a rule set is released only if it is still showing, so a scene picked by hand is never cleared. Runs in Home Assistant; stored in Home Assistant. Commands `celebright/rules`, `rule_save`, `rule_delete`, `rule_move`.
- **A Celebright page in the sidebar** (`celebright-panel`, same file): Control, Holidays and Rules as three tabs, a controller picker when there are several, a phone layout with the sidebar's menu button. Turn it on or off in the integration's **Configure** options (no restart). It is on for new installs only; an existing install keeps it off until you switch it on.
- **Regenerate this dashboard** button under the card on the generated dashboard's Control view: it runs `celebright.generate_dashboard` for you (it asks first, and rewrites the default `celebright_dashboard.yaml`).
- The integration serves the card and adds it to Lovelace's resources itself. With YAML-mode resources it loads the card on every page instead.
- A `celebright/card_info` websocket command that tells the card each controller's entities, scenes (with their colours) and editable events.

### Fixed
- Reloading the only Celebright entry (which a password re-authentication does) removed the card's Lovelace resource until the next restart. The resource is now removed only when the last entry is deleted, and added again when a new one is set up.

### Changed
- **The generated dashboard is three full-width views:** **Control** (the card), **Holidays** and **Rules**, matching the sidebar page. The **Lights**, **Schedule** and **Automations** views are gone, since the cards do what they did and more. The README has a stock-card snippet if you want one, and no longer lists the one-tap scene-button extra (the card's scene tiles replace it).
- `frontend`, `http`, `lovelace`, `panel_custom` and `websocket_api` are now declared manifest dependencies, and `hacs.json` requires Home Assistant 2024.10.
- **HACS and the Home Assistant Marketplace** (built into Home Assistant 2026.11 and newer, with the same catalog and `hacs.json`): the README explains installing from the Marketplace or HACS and has "Open in Marketplace / HACS" badges, with the install parts hidden from the Marketplace page. `hacs.json` now holds only documented keys (`name`, `homeassistant`), the manifest declares an integration category (`lighting.led_strips_controllers`), and the validation workflows use the documented HACS action inputs and can be started by hand.
- **README:** screenshots (control, holidays, rules, the editors, automations and a phone view), a full features table, a "what runs where" table, current entities and services, an examples section, and troubleshooting for the new tabs.

## [0.3.3] - 2026-10-27

### Upgrading from 0.3.2
Update in HACS and restart. Nothing else to do.

### Fixed
- **Scene "Off" (resume the schedule) did nothing on firmware 3.x:** the controller rejects `setResumeSchedule`, so a manual scene stayed on, e.g. holiday lights left on after sunrise. On v3, **Off** now turns off a manual display (the schedule's next event then starts as usual). Scene-select failures now fail the calling automation instead of only logging.
- **Deprecation warning:** the "Scenes" sub-device is now linked to its controller with `via_device_id`, as Home Assistant 2027.8 will require.

## [0.3.2] - 2026-10-26

### Upgrading from 0.3.1
Update in HACS and restart. Nothing needs re-creating: existing holiday automations keep working, and the new inputs use their defaults until you set them. To use them, re-import the blueprint (**Blueprints → ⋮ → Re-import blueprint**) and edit your existing automation; don't create a new one.

### Added
- **Holiday controller:** built-in **Halloween** (Oct 25–31), four **custom holidays** (a scene plus any start and end date, may cross New Year), and optional **timing adjustments** (up to 14 extra days before or after each week-long holiday, and Halloween's first and last day).
- **`celebright_automations.yaml` is back**, with its manual guide in the README (include it, or paste one automation), for those who prefer plain YAML to blueprints.

## [0.3.1] - 2026-10-26

### Upgrading from 0.3.0
Update in HACS and restart. Automations made from the Celebright blueprints need their inputs updated (see below): re-import each blueprint (**Settings → Automations & Scenes → Blueprints → ⋮ → Re-import blueprint**), then open your existing automation, pick the scenes from the new dropdowns and save. Don't use *Create automation* again, or you'll have two. Nothing else changes; the new scene entities appear on their own.

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