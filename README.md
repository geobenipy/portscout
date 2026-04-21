# PortScout

**Serial COM Port Scanner with NMEA 0183 Detection**  
*By Beni*

---

PortScout scans every serial COM port on your machine, probes common baud rates, and tells you exactly which port is sending NMEA 0183 data — and which sentence types it contains. No GUI, no nonsense. Runs entirely in the terminal.

---

## Features

- **Automatic port enumeration** — finds all available COM ports via pyserial
- **Multi-baud probing** — tries 4800, 9600, 19200, 38400, 57600, 115200 (or any custom list)
- **NMEA 0183 detection** — recognises all standard talker IDs and sentence formatters
- **Checksum validation** — every sentence is verified with its XOR checksum
- **Sentence classification** — maps sentence codes to human-readable descriptions (GGA, RMC, GSA, GSV, VTG, AIS VDM/VDO, and 40+ more)
- **Multi-constellation support** — GPS (`GP`), GLONASS (`GL`), Galileo (`GA`), BeiDou (`GB`), multi (`GN`), and more
- **Early exit** — stops probing a port as soon as NMEA is found (saves time)
- **tqdm progress bar** — real-time scan feedback (optional, degrades gracefully)
- **Colour terminal output** — clean ANSI-coloured report, auto-disabled when piping
- **File report export** — write a plain-text copy with `--output report.txt`
- **Verbose mode** — dump every raw sentence found
- **Zero runtime dependencies beyond pyserial and tqdm**

---

## Installation

```bash
# Clone the repository
git clone https://github.com/beni/portscout.git
cd portscout

# Install dependencies
pip install -r requirements.txt
```

> **Python 3.8+** is required.  
> Works on **Windows**, **Linux**, and **macOS**.

---

## Usage

```bash
# Basic scan (default baud rates, 4 s read window per baud)
python portscout.py

# Custom baud rates
python portscout.py --baudrates 4800,9600

# Longer read window (useful for slow devices)
python portscout.py --duration 8

# Save report to a file
python portscout.py --output scan_report.txt

# Verbose: print every raw sentence found
python portscout.py --verbose

# Disable colour output
python portscout.py --no-color

# Combine options
python portscout.py --baudrates 4800,9600,38400 --duration 6 --output report.txt -v
```

### All options

| Option | Default | Description |
|---|---|---|
| `-b / --baudrates` | `4800,9600,19200,38400,57600,115200` | Comma-separated baud rates to probe |
| `-t / --timeout` | `3` | pyserial read timeout per attempt (seconds) |
| `-d / --duration` | `4` | Read window per baud rate attempt (seconds) |
| `-o / --output` | — | Write plain-text report to file |
| `--no-color` | — | Disable ANSI colour output |
| `--skip-empty` | — | Hide ports with zero bytes received |
| `-v / --verbose` | — | Print all raw NMEA sentences |
| `-h / --help` | — | Show help |

---

## Example output

```
  PortScout  —  starting up …

  Found 3 port(s): COM3, COM4, COM8
  Probing baud rates: 4800, 9600, 19200, 38400, 57600, 115200
  Max scan time: ~72 s (stops early when NMEA is found)

  Scanning: 100%|██████████████████████████████| 3/3 [00:09<00:00] [elapsed<remaining]

══════════════════════════════════════════════════════════════════════════
  PORTSCOUT  —  Serial COM Port & NMEA Scanner
  By Beni  |  https://github.com/beni/portscout
══════════════════════════════════════════════════════════════════════════
  Scan started : 2024-11-15 14:32:07
  Scan ended   : 2024-11-15 14:32:16
  Duration     : 9.3 s
  Baud rates   : 4800, 9600, 19200, 38400, 57600, 115200
  Read window  : 4 s per baud rate
══════════════════════════════════════════════════════════════════════════

  SUMMARY
  ────────────────────────────────────────────────────────────────────────
  Total COM ports found  : 3
  Ports with NMEA data   : 1
  ────────────────────────────────────────────────────────────────────────

  [01] COM3    ✔ NMEA DETECTED
       Description : USB-SERIAL CH340
       Hardware ID : USB VID:PID=1A86:7523 SER=
       Best baud    : 9600 baud
       NMEA sentences found : 42

       Sentence           Talker   Description                                Cksum OK
       ────────────────── ──────── ────────────────────────────────────────── ────────────────
       $GPRMC             GPS      Recommended Minimum Specific GNSS Data     14/14 (100%)
       $GPGGA             GPS      Global Positioning System Fix Data          14/14 (100%)
       $GPGSV             GPS      GNSS Satellites in View                     10/10 (100%)
       $GPGSA             GPS      GNSS DOP and Active Satellites               4/4 (100%)

  [02] COM4    · no NMEA
       No data received on any baud rate.

  [03] COM8    · no NMEA
       Received 128 bytes but no valid NMEA sentences detected.

══════════════════════════════════════════════════════════════════════════
  NMEA PORT QUICK-REFERENCE
  ────────────────────────────────────────────────────────────────────────
  COM3               9600 baud   $GPGGA, $GPGSA, $GPGSV, $GPRMC

══════════════════════════════════════════════════════════════════════════
  SCAN COMPLETE
══════════════════════════════════════════════════════════════════════════
```

---

## Supported NMEA sentence types

PortScout knows and classifies 40+ sentence formatters, including:

| Code | Description |
|---|---|
| `GGA` | Global Positioning System Fix Data |
| `RMC` | Recommended Minimum Specific GNSS Data |
| `GSA` | GNSS DOP and Active Satellites |
| `GSV` | GNSS Satellites in View |
| `GLL` | Geographic Position – Latitude/Longitude |
| `VTG` | Course Over Ground and Ground Speed |
| `ZDA` | Time and Date |
| `GNS` | GNSS Fix Data (multi-constellation) |
| `HDT` | Heading – True |
| `HDG` | Heading – Deviation and Variation |
| `MWV` | Wind Speed and Angle |
| `DPT` | Depth |
| `VDM` | AIS VHF Data-link Message (other vessels) |
| `VDO` | AIS VHF Data-link Message (own vessel) |
| … | And many more |

All standard talker IDs are recognised: `GP` (GPS), `GL` (GLONASS), `GA` (Galileo), `GB` (BeiDou), `GN` (multi-constellation), `II`, `IN`, `HC`, `HE`, and more.

---

## Troubleshooting

**Port access denied / in use**  
Another application (e.g. a charting program) is holding the port open. Close it first.

**No data received**  
- Check that the device is powered and connected.
- NMEA GPS receivers typically use 4800 or 9600 baud. Try `--baudrates 4800,9600 --duration 8`.
- Some devices need RTS/CTS or DTR signals – these can be added inside `probe_port()`.

**`No serial ports found`**  
Install the device driver for your USB-to-serial adapter (CP210x, CH340, FTDI, etc.).

**tqdm not found**  
```bash
pip install tqdm
```
PortScout works without it, just without progress bars.

---

## Dependencies

| Package | Purpose | Required |
|---|---|---|
| [pyserial](https://pypi.org/project/pyserial/) | Serial port access | ✅ Yes |
| [tqdm](https://pypi.org/project/tqdm/) | Progress bars | ⬜ Optional |

---

## License

MIT — see [LICENSE](LICENSE).

---

## Contributing

Bug reports, pull requests, and suggestions are welcome. Open an issue or fork away.
