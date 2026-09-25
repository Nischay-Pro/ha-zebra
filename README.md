# Zebra Printer for Home Assistant

Monitor a networked Zebra label printer and manage its print method and
resettable label counter from Home Assistant. The integration connects locally
using Zebra Set-Get-Do (SGD) commands over the printer's raw TCP print port.

<p align="center">
  <img src="custom_components/zebra_printer/brand/zebra-logo-horizontal.svg" alt="Zebra Technologies" width="360">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=Nischay-Pro&amp;repository=ha-zebra&amp;category=integration">
    <img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open Zebra Printer in HACS">
  </a>
</p>

> [!NOTE]
> Tested with a Zebra ZD420. Other Zebra models may expose different SGD
> settings or counters. This integration does not send print jobs.

## Features

- **Live operating status:** decodes Zebra's pause, error, and warning flags,
  including media/ribbon faults, open printhead, temperature faults, and media
  calibration warnings. Simultaneous conditions appear as sensor attributes.
- **Printer statistics:** lifetime and resettable label counts, total media
  fed, firmware, and printhead temperature.
- **Media status:** ribbon cartridge and paper-supply values reported by the
  printer.
- **Print controls:** switch between Direct Thermal and Thermal Transfer, and
  reset either resettable label counter when the printer reports it.
- **Home Assistant device:** one device per configured printer, with a link to
  its web configuration page and included icon and logo assets.
- **Local polling:** reads the printer every 60 seconds; no cloud account is
  required.

The integration does not estimate labels remaining on a roll. The lifetime
label count cannot be reset; each reset button affects only its matching
resettable counter.

## 1. Installation

### HACS

This repository must be published on GitHub before it can be installed through
HACS. It is not currently a default HACS repository. Once published, the badge
above opens its page in HACS, including for a custom repository.

1. In HACS, open the menu and choose **Custom repositories**.
2. Enter `https://github.com/Nischay-Pro/ha-zebra` and choose
   **Integration** as the category.
3. Download **Zebra Printer** and restart Home Assistant.

### Manual

Copy `custom_components/zebra_printer` into
`/config/custom_components/zebra_printer` on your Home Assistant system, then
restart Home Assistant.

## 2. Getting started

Go to **Settings → Devices & services → Add integration → Zebra Printer**.
Enter the printer's hostname or IP address and its raw TCP print port (usually
`9100`). The setup flow checks that the printer responds to the required SGD
commands before creating the device.

Open the new Zebra device page to see its entities. The integration supplies
local PNG branding for Home Assistant versions that support it. The device page
also links to the printer's own web configuration page.

| Setting | What to enter |
| --- | --- |
| Host | Printer hostname or IP address, without `http://` |
| Port | Raw TCP print port; default `9100` |

The printer's web page may ask for an administrator password. This integration
does not use that password: it talks to the raw TCP SGD port. Whether setting
changes are allowed depends on the printer's security configuration. A change
is reported as successful only after the printer confirms its new value.

## 3. Entities

| Entity | Description |
| --- | --- |
| Operating status | Printer-reported state; attributes list all active errors and warnings |
| Lifetime labels | Nonresettable number of labels printed |
| Labels since reset 1 / 2 | The two resettable label counters |
| Lifetime media fed | Total media length fed through the printer, in inches |
| Firmware | Printer firmware version |
| Printhead temperature | Current printhead temperature |
| Ribbon cartridge | Whether a ribbon cartridge is loaded |
| Paper supply | Printer-reported media status |
| Print method | Select Direct Thermal or Thermal Transfer |
| Reset label counter 1 | Set resettable counter 1 to zero |
| Reset label counter 2 | Set resettable counter 2 to zero |

Thermal Transfer selection requires the printer to report an inserted ribbon
cartridge. Use appropriate thermal-transfer media as well. Each reset button
changes only its corresponding resettable counter; neither affects lifetime
labels or the other resettable counter. A reset button is created only when
the printer reports that counter.

## 4. Dashboard controls

Add the **Print method** select entity to an Entities card, or use a Tile card
with the **Select options** feature.

For the reset button, a confirmation on the dashboard helps prevent accidental
presses. This example uses the entity ID from a ZD420; replace it if Home
Assistant assigned a different ID:

```yaml
type: button
entity: button.zebra_zd420_reset_label_counter_1
name: Reset label counter 1
tap_action:
  action: perform-action
  perform_action: button.press
  target:
    entity_id: button.zebra_zd420_reset_label_counter_1
  confirmation:
    text: Reset label counter 1 to zero? Lifetime labels will not change.
```

Use the matching entity ID to reset counter 2:

```yaml
type: button
entity: button.zebra_zd420_reset_label_counter_2
name: Reset label counter 2
tap_action:
  action: perform-action
  perform_action: button.press
  target:
    entity_id: button.zebra_zd420_reset_label_counter_2
  confirmation:
    text: Reset label counter 2 to zero? Lifetime labels will not change.
```

The confirmation applies to each card. A direct `button.press` service call
does not show a confirmation.

## 5. Troubleshooting

| Symptom | Check |
| --- | --- |
| Printer shows Paused while an SNMP sensor says idle | The Zebra operating-status sensor reads the printer's pause and fault flags. SNMP may expose a different status value. |
| Printer cannot be added | Confirm its address, port, network reachability, and SGD support. |
| Values show as unknown | Some SGD variables are unavailable on certain models or firmware versions. |
| Thermal Transfer is rejected | Insert a ribbon cartridge and check the printer's ribbon status. |
| A setting change fails | Check whether the printer allows SGD writes through its raw print port. |

## Development

The integration uses Python's standard library and Home Assistant's native
entity and polling APIs. Run `python -m unittest discover -s tests -v` to
test the SGD client. GitHub Actions are configured to run those tests, HACS
validation, and hassfest when changes are pushed.

Home Assistant setup and entity names are currently available in English via
`custom_components/zebra_printer/translations/en.json`.

Connection details are entered during Home Assistant setup. No printer
address, serial number, password, or access key is stored in this repository.
The integration branding uses Zebra's [official horizontal logo asset](https://medialibrary.zebra.com/content/experience-fragments/zebra1/us/en/footer/master/_jcr_content/root/container_499331825/container/col1par/image.coreimg.svg/1757099817446/zebra-logo-horizontal.svg)
for hardware identification. Zebra and the Zebra logo are trademarks of Zebra
Technologies Corp. This independent integration is not affiliated with or
endorsed by Zebra Technologies.

Zebra references: [printer settings](https://docs.zebra.com/us/en/printers/desktop/bm-zd620-and-zd420-desktop-printers-user-guide-ditamap/c-zd620-420-printer-configuration-menus/r-zd620-zd420-ug-settings-menu.html)
and [resettable counters](https://docs.zebra.com/us/en/printers/software/zpl-pg/c-sgd-commands-from-a-to-d/r-sgd-odometer-user-label-count-12-.html).

Copyright (C) 2026 Zebra Printer contributors. Licensed under the
[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0-only).
