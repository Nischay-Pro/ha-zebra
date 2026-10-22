# Zebra Printer for Home Assistant

Monitor a networked Zebra label printer, manage its print method and
resettable label counters, and send raw ZPL label jobs from Home Assistant. The
integration connects locally using Zebra Set-Get-Do (SGD) commands over the
printer's raw TCP print port.

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
> settings or counters. Print jobs are sent as raw ZPL over the local TCP port.

## Features

- **Live operating status:** decodes Zebra's pause, error, and warning flags,
  including media/ribbon faults, open printhead, temperature faults, and media
  calibration warnings. Simultaneous conditions appear as sensor attributes.
- **Printer statistics:** lifetime and resettable label counts, total media
  fed, estimated media remaining, printhead lifetime usage, firmware, and
  printhead temperature.
- **Media status:** ribbon cartridge status and remaining length, low-ribbon
  warning threshold, and paper-supply values reported by the printer.
- **Print controls:** print method, darkness, speed, and media type; resettable
  counter buttons; media calibration and a one-label test print; and raw ZPL
  through the `zebra_printer.print` action.
- **Home Assistant device:** one device per configured printer, with a link to
  its web configuration page and included icon and logo assets.
- **Automatic discovery:** searches for Zebra printers when the setup flow
  opens, with manual host and port entry as a fallback.
- **Local polling:** reads the printer every 60 seconds; no cloud account is
  required.
- **Optional printer alerts:** selected printer conditions can be sent to a
  local-only Home Assistant webhook when the printer reports HTTP-POST alert
  support.

The lifetime label count cannot be reset; each reset button affects only its
matching resettable counter.

## 1. Installation

### HACS

1. In HACS, search for **Zebra Printer** and install it.
2. Restart Home Assistant.

If **Zebra Printer** does not appear in the search results, add the repository
as a custom repository:

1. In HACS, open the menu and choose **Custom repositories**.
2. Enter `https://github.com/Nischay-Pro/ha-zebra` and choose
   **Integration** as the category.
3. Add the repository, then search for **Zebra Printer** and install it.
4. Restart Home Assistant.

### Manual

Copy `custom_components/zebra_printer` into
`/config/custom_components/zebra_printer` on your Home Assistant system, then
restart Home Assistant.

## 2. Getting started

Go to **Settings → Devices & services → Add integration → Zebra Printer**.
The setup flow searches enabled Home Assistant IPv4 networks using Zebra's UDP
network-discovery service on port 4201. Select a verified printer from the
results, or choose **Search again** to repeat the scan. If discovery has no
results, the form also lets you retry or enter the printer's hostname or IP
address and raw TCP print port (usually `9100`). The flow checks the printer's
SGD response before creating the device. Discovery requires local broadcast
traffic between Home Assistant and the printer. A bind or network-interface
error is shown separately from a scan where no printer replied.

To change a configured printer's host or port, open its config entry and choose
**Reconfigure**. The flow checks the printer's required SGD settings before it
saves the new address. If the printer reports `device.unique_id`, the
integration uses it for config-entry and device identity, migrating an older
host-based identity while keeping the existing device and entity IDs. Printers
that do not report this variable continue using the host as their identity.

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
| Estimated media remaining | Approximate remaining length from a configured roll and the lifetime media-fed counter |
| Firmware | Printer firmware version |
| Printhead temperature | Current printhead temperature |
| Printhead lifetime usage | Lifetime count of dots printed by the printhead |
| Ribbon cartridge | Whether a ribbon cartridge is loaded |
| Ribbon remaining | Remaining cartridge ribbon length in meters |
| Low ribbon warning | Select the cartridge's warning threshold |
| Paper supply | Printer-reported media status |
| Print method | Select Direct Thermal or Thermal Transfer |
| Print darkness | Set darkness from 0.0 to 30.0 |
| Print speed | Set speed within the ZD420's resolution-specific range |
| Media type | Select continuous, gap/web, or mark/notch media |
| Reset label counter 1 | Set resettable counter 1 to zero |
| Reset label counter 2 | Set resettable counter 2 to zero |
| Calibrate media | Run media and ribbon sensor calibration |
| Print test label | Print one diagnostic label |

Thermal Transfer selection requires the printer to report an inserted ribbon
cartridge. Use appropriate thermal-transfer media as well. Each reset button
changes only its corresponding resettable counter; neither affects lifetime
labels or the other resettable counter. Optional controls become available
when their printer readings support them.

## 4. Printing labels

Use the `zebra_printer.print` action and select one configured Zebra Printer
device. The `zpl` field accepts raw ZPL text encoded as UTF-8. The integration
sends it as supplied without checking its size or ZPL syntax. This example
sends one label:

```yaml
action: zebra_printer.print
target:
  device_id: YOUR_ZEBRA_DEVICE_ID
data:
  zpl: |-
    ^XA
    ^FO40,40^A0N,40,40^FDHello from Home Assistant^FS
    ^XZ
```

The action sends the supplied bytes once and does not retry. Zebra printers do
not acknowledge that the label was physically printed, so a successful action
only confirms that Home Assistant handed the data to the TCP connection. If a
connection fails during transmission, some or all of the job may have reached
the printer; check the printer before manually retrying to avoid duplicate
labels. For non-ASCII text, use a matching Zebra character encoding command
such as `^CI28` in the ZPL.

### Calibration, test label, and print settings

The **Calibrate media** button runs Zebra's manual calibration for the media
and ribbon sensors. Calibration can feed media. The **Print test label** button
sends one small diagnostic label and consumes media.

The print darkness control uses Zebra's 0.0–30.0 range. Print speed is limited
by the ZD420 printhead resolution: 2–6 ips at 203 dpi and 2–4 ips at 300 dpi.
The media type selector offers continuous, gap/web, and mark/notch. These
settings change printer behavior and can affect label quality or feed
registration; use values appropriate for the loaded media.

## 5. Media roll estimate

After loading a roll, open **Settings → Devices & services**, select the Zebra
Printer entry, choose **Configure**, then **Set media roll estimate**. Enter the
roll's full nominal length in inches. Leave the remaining length blank for a
new full roll; for a partly used roll, enter the estimated media remaining.
Saving refreshes the printer's lifetime media-fed counter and uses that reading
as the new estimate baseline.

The `zebra_printer.set_media_roll` action is also available for automations:

```yaml
action: zebra_printer.set_media_roll
target:
  device_id: YOUR_ZEBRA_DEVICE_ID
data:
  roll_length_inches: 1000
```

The sensor estimates remaining media as the configured starting remainder minus
additional media fed by the printer, and clamps the result to zero. The printer
does not directly measure roll length. This estimate can drift because the
counter includes media used for calibration, test labels, and waste, and it may
not account for media removed outside the printer. If the lifetime counter
drops below the saved baseline, the sensor becomes unavailable. Use **Set media
roll estimate** again to establish a new baseline.

## 6. Dashboard controls

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

## 7. Printer event alerts

Printer-originated alerts are disabled by default. Open the Zebra Printer
config entry and choose **Configure** to enable them. Select the conditions to
forward and enter an HTTP base URL that the printer can reach, such as
`http://192.168.1.10:8123`. Home Assistant appends its webhook path and creates
a secret webhook ID. The webhook accepts local-network POST requests only.

The setup checks that the printer reports both the selected conditions through
`alerts.conditions` and the `HTTP-POST` destination through
`alerts.destinations`. The integration then configures both condition-set and
condition-clear alerts. It checks the callback's printer identity against
`device.unique_id` when the printer reports that value. For each matching
callback it fires the
`zebra_printer_alert` event with `config_entry_id`, `condition`, and the
printer's `message`. Automations can filter on the event type and condition.
Only the selected, printer-reported conditions are forwarded.

Use an HTTP address on the same network the printer can reach. The callback
must reach Home Assistant directly enough to be recognized as local; a public
or cloud-only address is not suitable for this local-only webhook. Do not share
the generated webhook ID. Disabling alerts, unloading the entry, or deleting
it sends Zebra's documented remove command for these exact conditions and
callback URL. If Home Assistant cannot connect to the printer during cleanup,
the printer may retain a rule pointing to the retired webhook. The integration
does not retain failed cleanup data for an automatic retry; remove a stale rule
through the printer configuration after reconnecting.

Zebra references: [HTTP POST alert payload](https://docs.zebra.com/us/en/printers/software/zpl-pg/http-post-alerts/configuring-alerts-where-the-alert-destination-is-http-post.html), [alerts.add and rule removal](https://docs.zebra.com/content/tcm/us/en/printers/software/zpl-pg/sgd-command-reference/alerts-add.html), and [available alert conditions](https://docs.zebra.com/content/tcm/us/en/printers/software/zpl-pg/sgd-command-reference/alerts-conditions.html).

## 8. Troubleshooting

| Symptom | Check |
| --- | --- |
| Printer shows Paused while an SNMP sensor says idle | The Zebra operating-status sensor reads the printer's pause and fault flags. SNMP may expose a different status value. |
| Printer cannot be added | Confirm its address, port, network reachability, and SGD support. |
| Values show as unknown | Some SGD variables are unavailable on certain models or firmware versions. |
| Thermal Transfer is rejected | Insert a ribbon cartridge and check the printer's ribbon status. |
| A setting change fails | Check whether the printer allows SGD writes through its raw print port. |

## 9. Development

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
