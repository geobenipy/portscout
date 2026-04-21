#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PortScout - Serial COM Port Scanner with NMEA 0183 Detection
=============================================================
Author  : Beni

Scans all available serial COM ports and identifies NMEA 0183 data streams.
For every port that is alive, PortScout tries a range of baud rates, reads
raw bytes, validates NMEA sentences (checksum + structure), and reports
exactly which sentence types were found.

Usage
-----
    python portscout.py [options]

    -h, --help              Show help and exit
    -b, --baudrates         Comma-separated list of baud rates to probe
                            (default: 4800,9600,19200,38400,57600,115200)
    -t, --timeout           Read timeout per baud rate attempt in seconds
                            (default: 3)
    -d, --duration          Total read duration per baud rate attempt in
                            seconds (default: 4)
    -o, --output            Write the report to a text file in addition to
                            printing it to the console
    --no-color              Disable ANSI colour output
    --skip-empty            Skip ports that returned no data at all
    -v, --verbose           Print every raw NMEA sentence found
"""

import argparse
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Optional dependency imports with friendly error messages
# ---------------------------------------------------------------------------

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.exit(
        "[ERROR] pyserial is not installed.\n"
        "        Run:  pip install pyserial"
    )

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    print(
        "[INFO ] tqdm not found – progress bars disabled.\n"
        "        Install with:  pip install tqdm\n"
    )

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

_USE_COLOR = True  # may be disabled via --no-color or when not a tty


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(t: str) -> str:  return _c("32", t)
def yellow(t: str) -> str: return _c("33", t)
def cyan(t: str) -> str:   return _c("36", t)
def red(t: str) -> str:    return _c("31", t)
def bold(t: str) -> str:   return _c("1",  t)
def dim(t: str) -> str:    return _c("2",  t)

# ---------------------------------------------------------------------------
# NMEA sentence knowledge base
# ---------------------------------------------------------------------------

#: Talker IDs – who is sending the data
TALKER_IDS: Dict[str, str] = {
    "GP": "GPS",
    "GL": "GLONASS",
    "GA": "Galileo",
    "GB": "BeiDou",
    "GN": "Multi-constellation GNSS",
    "GQ": "QZSS",
    "II": "Integrated Instrumentation",
    "IN": "Integrated Navigation",
    "EC": "LORAN-C",
    "LC": "LORAN-C",
    "RA": "RADAR",
    "HC": "Magnetic Compass",
    "HE": "Gyro",
    "PG": "Garmin Proprietary",
    "P":  "Proprietary",
    "WI": "Weather Instruments",
    "YX": "Transducer",
    "SD": "Sounder",
    "SS": "Sounder",
    "VD": "Velocity Sensor",
    "VM": "Velocity Sensor (Magnetic)",
    "VW": "Velocity Sensor (Water)",
}

#: Sentence formatter (the part after the talker ID)
SENTENCE_TYPES: Dict[str, str] = {
    # ── Position & Navigation ──────────────────────────────────────────────
    "GGA": "Global Positioning System Fix Data (position, altitude, satellites)",
    "GLL": "Geographic Position – Latitude / Longitude",
    "GNS": "GNSS Fix Data (multi-constellation)",
    "RMC": "Recommended Minimum Specific GNSS Data (position, speed, course, date)",
    "VTG": "Course Over Ground and Ground Speed",
    "ZDA": "Time and Date",
    "GBS": "GNSS Satellite Fault Detection",
    "DTM": "Datum Reference",
    "GRS": "GNSS Range Residuals",
    "GST": "GNSS Pseudorange Noise Statistics",
    # ── Satellite Information ──────────────────────────────────────────────
    "GSA": "GNSS DOP and Active Satellites",
    "GSV": "GNSS Satellites in View",
    # ── Heading / Attitude ────────────────────────────────────────────────
    "HDG": "Heading – Deviation and Variation",
    "HDM": "Heading – Magnetic",
    "HDT": "Heading – True",
    "ROT": "Rate of Turn",
    "RPM": "Engine Revolutions",
    # ── Marine / Vessel ───────────────────────────────────────────────────
    "APB": "Autopilot Sentence B",
    "BOD": "Bearing – Origin to Destination",
    "BWC": "Bearing and Distance to Waypoint (Great Circle)",
    "BWR": "Bearing and Distance to Waypoint (Rhumb Line)",
    "BWW": "Bearing – Waypoint to Waypoint",
    "DBT": "Depth Below Transducer",
    "DPT": "Depth",
    "MTW": "Mean Temperature of Water",
    "MWV": "Wind Speed and Angle",
    "MWD": "Wind Direction and Speed",
    "VDR": "Set and Drift",
    "VHW": "Water Speed and Heading",
    "VWR": "Relative Wind Speed and Angle",
    "XTE": "Cross-Track Error – Measured",
    "RTE": "Routes",
    "WPL": "Waypoint Location",
    # ── AIS ───────────────────────────────────────────────────────────────
    "VDM": "AIS VHF Data-link Message (other vessels)",
    "VDO": "AIS VHF Data-link Message (own vessel)",
    # ── Proprietary ───────────────────────────────────────────────────────
    "PGRME": "Garmin Estimated Error",
    "PGRMZ": "Garmin Altitude",
    "PGRMT": "Garmin Sensor Status",
    "PUBX":  "u-blox Proprietary",
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SentenceHit:
    """One observed instance of an NMEA sentence."""
    raw:          str
    talker:       str
    formatter:    str
    checksum_ok:  bool


@dataclass
class BaudResult:
    """Results for one (port, baud-rate) combination."""
    baud:          int
    bytes_read:    int
    sentences:     List[SentenceHit] = field(default_factory=list)
    errors:        List[str]         = field(default_factory=list)
    has_nmea:      bool              = False


@dataclass
class PortResult:
    """All scan results for one COM port."""
    device:       str
    description:  str
    hwid:         str
    accessible:   bool
    baud_results: List[BaudResult] = field(default_factory=list)

    @property
    def best_baud(self) -> Optional[int]:
        """Return the baud rate with the most NMEA sentences found."""
        hits = [(r.baud, len(r.sentences)) for r in self.baud_results if r.has_nmea]
        return max(hits, key=lambda x: x[1])[0] if hits else None

    @property
    def all_sentences(self) -> List[SentenceHit]:
        """Flattened list of all NMEA sentences found across all baud rates."""
        out: List[SentenceHit] = []
        for r in self.baud_results:
            out.extend(r.sentences)
        return out

    @property
    def has_nmea(self) -> bool:
        return any(r.has_nmea for r in self.baud_results)


# ---------------------------------------------------------------------------
# NMEA parsing helpers
# ---------------------------------------------------------------------------

# Matches a standard NMEA sentence: $<talker><formatter>,<data>*<checksum>
# Also matches proprietary sentences: $P<data>*<checksum>
_NMEA_RE = re.compile(
    r"\$(?P<sentence>[A-Z0-9]{1,10}(?:,[^\*\r\n]*)?)"
    r"(?:\*(?P<checksum>[0-9A-Fa-f]{2}))?",
    re.ASCII,
)


def _compute_checksum(sentence: str) -> int:
    """XOR all bytes between $ and * (exclusive)."""
    xor = 0
    for ch in sentence:
        xor ^= ord(ch)
    return xor


def validate_and_parse(raw_sentence: str) -> Optional[SentenceHit]:
    """
    Try to parse a single NMEA sentence string.

    Returns a :class:`SentenceHit` on success, or ``None`` if the input does
    not look like a valid NMEA sentence at all.

    Parameters
    ----------
    raw_sentence:
        The raw string starting with ``$``.
    """
    raw_sentence = raw_sentence.strip()
    m = _NMEA_RE.match(raw_sentence)
    if not m:
        return None

    body     = m.group("sentence")   # everything between $ and *
    cksum_s  = m.group("checksum")   # two hex chars or None

    checksum_ok = False
    if cksum_s:
        expected  = _compute_checksum(body)
        checksum_ok = (expected == int(cksum_s, 16))

    # Break apart talker + formatter
    # Proprietary: $PXXX  ->  talker="P", formatter=rest
    # Standard:    $GPRMC ->  talker="GP", formatter="RMC"
    parts     = body.split(",", 1)
    tag       = parts[0]  # e.g. "GPRMC" or "PUBX"

    if tag.startswith("P") and len(tag) >= 2:
        talker    = "P"
        formatter = tag[1:]
    elif len(tag) >= 3:
        talker    = tag[:2]
        formatter = tag[2:]
    else:
        talker    = tag
        formatter = ""

    return SentenceHit(
        raw=raw_sentence,
        talker=talker,
        formatter=formatter,
        checksum_ok=checksum_ok,
    )


def extract_sentences_from_buffer(raw_bytes: bytes) -> List[SentenceHit]:
    """
    Decode a raw byte buffer and extract all recognisable NMEA sentences.

    The function tries UTF-8 first, falls back to latin-1, and then searches
    line-by-line for ``$``-prefixed NMEA content.

    Parameters
    ----------
    raw_bytes:
        Raw bytes as received from the serial port.
    """
    try:
        text = raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        text = raw_bytes.decode("latin-1", errors="replace")

    sentences: List[SentenceHit] = []
    # Look at every line AND scan for embedded $ signs in noisy data
    for line in re.split(r"[\r\n]+", text):
        line = line.strip()
        if not line:
            continue
        # A line might have multiple sentences (e.g. concatenated from buffer)
        for candidate in re.findall(r"\$[A-Z0-9][^\$\r\n]{3,82}", line):
            hit = validate_and_parse(candidate)
            if hit and hit.formatter:
                sentences.append(hit)

    return sentences


# ---------------------------------------------------------------------------
# Port scanning
# ---------------------------------------------------------------------------

def list_ports() -> List[serial.tools.list_ports_common.ListPortInfo]:
    """Return all available serial ports, sorted by device name."""
    ports = list(serial.tools.list_ports.comports())
    ports.sort(key=lambda p: p.device)
    return ports


def probe_port(
    device: str,
    baud: int,
    read_duration: float,
    timeout: float,
) -> BaudResult:
    """
    Open *device* at *baud* baud, read data for *read_duration* seconds and
    return a :class:`BaudResult` with everything found.

    Parameters
    ----------
    device:
        Serial port device string, e.g. ``"COM3"`` or ``"/dev/ttyUSB0"``.
    baud:
        Baud rate to use.
    read_duration:
        How many seconds to read data before closing the port.
    timeout:
        pyserial read timeout in seconds.
    """
    result = BaudResult(baud=baud, bytes_read=0)
    buffer = bytearray()

    try:
        with serial.Serial(
            port=device,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        ) as ser:
            deadline = time.monotonic() + read_duration
            while time.monotonic() < deadline:
                chunk = ser.read(256)
                if chunk:
                    buffer.extend(chunk)
                    result.bytes_read += len(chunk)
                # Early exit: if we already have enough data with valid NMEA,
                # no need to wait the full duration.
                if result.bytes_read > 4096 and b"$" in buffer:
                    break

    except serial.SerialException as exc:
        result.errors.append(str(exc))
        return result
    except PermissionError:
        result.errors.append("Permission denied – port may be in use by another application.")
        return result
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"Unexpected error: {exc}")
        return result

    if buffer:
        result.sentences = extract_sentences_from_buffer(bytes(buffer))
        result.has_nmea  = len(result.sentences) > 0

    return result


def scan_port(
    port_info: serial.tools.list_ports_common.ListPortInfo,
    baud_rates: List[int],
    read_duration: float,
    timeout: float,
    progress: Optional["tqdm"] = None,  # type: ignore[type-arg]
    verbose: bool = False,
) -> PortResult:
    """
    Run :func:`probe_port` for every baud rate in *baud_rates* and return a
    consolidated :class:`PortResult`.

    Stops probing as soon as NMEA data is found (greedy first-match strategy),
    unless ``verbose=True``.

    Parameters
    ----------
    port_info:
        A pyserial ``ListPortInfo`` object.
    baud_rates:
        Ordered list of baud rates to try.
    read_duration:
        Seconds of reading per baud rate.
    timeout:
        pyserial read timeout per attempt.
    progress:
        A tqdm instance to call ``.set_postfix`` on (optional).
    verbose:
        If True, probe all baud rates even after NMEA is found.
    """
    result = PortResult(
        device=port_info.device,
        description=port_info.description,
        hwid=port_info.hwid,
        accessible=True,
    )

    for baud in baud_rates:
        if progress:
            progress.set_postfix(
                port=port_info.device, baud=baud, refresh=True
            )

        br = probe_port(port_info.device, baud, read_duration, timeout)
        result.baud_results.append(br)

        # If we found NMEA and aren't in verbose mode, stop here.
        if br.has_nmea and not verbose:
            break

        # If the port is not accessible at all (permission / in-use), bail out.
        if br.errors and any("Permission" in e for e in br.errors):
            result.accessible = False
            break

    return result


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

_SEPARATOR  = "─" * 72
_SEPARATOR2 = "═" * 72


def _describe_formatter(formatter: str) -> str:
    return SENTENCE_TYPES.get(formatter, "Unknown / Proprietary")


def _describe_talker(talker: str) -> str:
    return TALKER_IDS.get(talker, "Unknown")


def _sentence_summary(sentences: List[SentenceHit]) -> Dict[str, Dict]:
    """
    Build a summary dict keyed by ``"TALKER+FORMATTER"`` with counts and
    checksum stats.
    """
    summary: Dict[str, Dict] = {}
    for s in sentences:
        key = f"{s.talker}{s.formatter}"
        if key not in summary:
            summary[key] = {
                "talker":      s.talker,
                "formatter":   s.formatter,
                "count":       0,
                "cksum_ok":    0,
                "cksum_fail":  0,
            }
        summary[key]["count"] += 1
        if s.checksum_ok:
            summary[key]["cksum_ok"] += 1
        else:
            summary[key]["cksum_fail"] += 1
    return summary


def _fmt_cksum(ok: int, fail: int) -> str:
    total = ok + fail
    if total == 0:
        return dim("n/a")
    pct = ok / total * 100
    label = f"{ok}/{total} ({pct:.0f}%)"
    if pct == 100.0:
        return green(label)
    elif pct >= 80.0:
        return yellow(label)
    else:
        return red(label)


def print_report(
    results: List[PortResult],
    scan_start: datetime,
    scan_end: datetime,
    args: argparse.Namespace,
    output_file: Optional[str] = None,
) -> None:
    """
    Print a structured, human-readable report to stdout and optionally to a
    file.

    Parameters
    ----------
    results:
        List of :class:`PortResult` objects from the scan.
    scan_start / scan_end:
        Timestamps used to compute total scan duration.
    args:
        Parsed CLI arguments (used to echo settings in the header).
    output_file:
        If set, write a colour-stripped copy of the report to this path.
    """
    lines: List[str] = []
    plain: List[str] = []  # colour-stripped for file output

    def emit(line: str) -> None:
        lines.append(line)
        # Strip ANSI escapes for file output
        plain.append(re.sub(r"\033\[[0-9;]*m", "", line))

    nmea_ports   = [r for r in results if r.has_nmea]
    total_ports  = len(results)
    total_nmea   = len(nmea_ports)
    duration     = (scan_end - scan_start).total_seconds()

    emit("")
    emit(bold(_SEPARATOR2))
    emit(bold("  PORTSCOUT  —  Serial COM Port & NMEA Scanner"))
    emit(bold("  By Beni  |  https://github.com/beni/portscout"))
    emit(bold(_SEPARATOR2))
    emit(f"  Scan started : {scan_start.strftime('%Y-%m-%d %H:%M:%S')}")
    emit(f"  Scan ended   : {scan_end.strftime('%Y-%m-%d %H:%M:%S')}")
    emit(f"  Duration     : {duration:.1f} s")
    emit(f"  Baud rates   : {', '.join(str(b) for b in args.baudrates)}")
    emit(f"  Read window  : {args.duration} s per baud rate")
    emit(bold(_SEPARATOR2))
    emit("")

    # ── Summary banner ──────────────────────────────────────────────────────
    emit(bold("  SUMMARY"))
    emit(f"  {_SEPARATOR}")
    emit(f"  Total COM ports found  : {bold(str(total_ports))}")
    emit(f"  Ports with NMEA data   : "
         + (bold(green(str(total_nmea))) if total_nmea else bold(red("0"))))
    emit(f"  {_SEPARATOR}")
    emit("")

    if not results:
        emit(yellow("  No serial ports found on this machine."))
        emit("")
        _write(lines, plain, output_file)
        return

    # ── Per-port details ────────────────────────────────────────────────────
    for i, r in enumerate(results, 1):
        header_flag = green("  ✔ NMEA DETECTED") if r.has_nmea else dim("  · no NMEA")
        emit(bold(f"  [{i:02d}] {r.device}") + "  " + header_flag)
        emit(f"       Description : {r.description}")
        emit(f"       Hardware ID : {dim(r.hwid)}")

        if not r.accessible:
            emit(f"       " + red("Port is not accessible (in use or permission denied)."))
            emit("")
            continue

        if r.has_nmea:
            best = r.best_baud
            emit(f"       Best baud    : {bold(green(str(best)))} baud")

            sentences = r.all_sentences
            summary   = _sentence_summary(sentences)

            emit(f"       NMEA sentences found : {bold(str(len(sentences)))}")
            emit("")
            emit(f"       {'Sentence':<18} {'Talker':<8} {'Description':<42} {'Cksum OK'}")
            emit(f"       {'─'*18} {'─'*8} {'─'*42} {'─'*16}")

            for key, info in sorted(summary.items(), key=lambda x: (-x[1]["count"], x[0])):
                talker_desc    = _describe_talker(info["talker"])
                formatter_desc = _describe_formatter(info["formatter"])
                cksum_str      = _fmt_cksum(info["cksum_ok"], info["cksum_fail"])

                emit(
                    f"       {cyan('$'+key):<26} "
                    f"{dim(talker_desc):<16} "
                    f"{formatter_desc:<42} "
                    f"{cksum_str}"
                )

            emit("")
            # Verbose: print raw sentences
            if args.verbose:
                emit(f"       {'─'*60}")
                emit(f"       Raw sentences:")
                for s in sentences[:50]:  # cap at 50 to avoid flooding
                    ck = green("✔") if s.checksum_ok else red("✗")
                    emit(f"       {ck} {dim(s.raw)}")
                if len(sentences) > 50:
                    emit(f"       … {len(sentences)-50} more not shown")
                emit("")
        else:
            # Show what was found (or not)
            total_bytes = sum(br.bytes_read for br in r.baud_results)
            if total_bytes == 0:
                emit(f"       " + dim("No data received on any baud rate."))
            else:
                emit(
                    f"       Received {total_bytes} bytes "
                    f"but no valid NMEA sentences detected."
                )
            errors = [e for br in r.baud_results for e in br.errors]
            if errors:
                for e in set(errors):
                    emit(f"       " + red(f"Error: {e}"))
            emit("")

    # ── NMEA quick-reference ────────────────────────────────────────────────
    if nmea_ports:
        emit(bold(_SEPARATOR2))
        emit(bold("  NMEA PORT QUICK-REFERENCE"))
        emit(f"  {_SEPARATOR}")
        for r in nmea_ports:
            summary = _sentence_summary(r.all_sentences)
            types   = sorted(f"${k}" for k in summary)
            emit(
                f"  {bold(r.device):<18} "
                f"{bold(green(str(r.best_baud)))} baud   "
                f"{', '.join(cyan(t) for t in types)}"
            )
        emit("")

    emit(bold(_SEPARATOR2))
    emit(bold("  SCAN COMPLETE"))
    emit(bold(_SEPARATOR2))
    emit("")

    _write(lines, plain, output_file)


def _write(
    lines: List[str],
    plain: List[str],
    output_file: Optional[str],
) -> None:
    """Print coloured lines to stdout and optionally write plain text to file."""
    print("\n".join(lines))
    if output_file:
        try:
            with open(output_file, "w", encoding="utf-8") as fh:
                fh.write("\n".join(plain))
            print(f"\n  Report saved to: {output_file}\n")
        except OSError as exc:
            print(red(f"\n  [WARN] Could not write report file: {exc}"))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="portscout",
        description=(
            "PortScout – Scan serial COM ports and detect NMEA 0183 data streams.\n"
            "By Beni  |  https://github.com/geobenipy/portscout.git"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python portscout.py\n"
            "  python portscout.py --baudrates 4800,9600 --duration 5\n"
            "  python portscout.py --output report.txt --verbose\n"
            "  python portscout.py --no-color\n"
        ),
    )
    p.add_argument(
        "-b", "--baudrates",
        default="4800,9600,19200,38400,57600,115200",
        metavar="RATES",
        help=(
            "Comma-separated list of baud rates to probe "
            "(default: 4800,9600,19200,38400,57600,115200)"
        ),
    )
    p.add_argument(
        "-t", "--timeout",
        type=float,
        default=3.0,
        metavar="SEC",
        help="pyserial read timeout per attempt in seconds (default: 3)",
    )
    p.add_argument(
        "-d", "--duration",
        type=float,
        default=4.0,
        metavar="SEC",
        help="Read duration per baud rate attempt in seconds (default: 4)",
    )
    p.add_argument(
        "-o", "--output",
        default=None,
        metavar="FILE",
        help="Write the report to a file in addition to the console",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colour output",
    )
    p.add_argument(
        "--skip-empty",
        action="store_true",
        help="Omit ports that returned no data at all from the report",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print every raw NMEA sentence found",
    )
    return p


def main() -> int:
    global _USE_COLOR  # noqa: PLW0603

    parser = build_parser()
    args   = parser.parse_args()

    # ── Validate & parse baud rates ─────────────────────────────────────────
    try:
        baud_rates = [int(b.strip()) for b in args.baudrates.split(",") if b.strip()]
    except ValueError:
        parser.error("--baudrates must be a comma-separated list of integers.")
    if not baud_rates:
        parser.error("--baudrates is empty.")
    args.baudrates = baud_rates

    # ── Colour setup ────────────────────────────────────────────────────────
    if args.no_color or not sys.stdout.isatty():
        _USE_COLOR = False

    # ── Port discovery ──────────────────────────────────────────────────────
    print(bold("\n  PortScout  —  starting up …\n"))
    ports = list_ports()

    if not ports:
        print(yellow("  No serial COM ports detected. Nothing to scan."))
        return 0

    print(f"  Found {bold(str(len(ports)))} port(s): "
          + ", ".join(bold(p.device) for p in ports))
    print(f"  Probing baud rates: {', '.join(str(b) for b in baud_rates)}")
    total_steps = len(ports) * len(baud_rates)
    print(
        f"  Max scan time: ~{total_steps * args.duration:.0f} s "
        f"(stops early when NMEA is found)\n"
    )

    # ── Scanning ────────────────────────────────────────────────────────────
    scan_start = datetime.now()
    results: List[PortResult] = []

    if TQDM_AVAILABLE:
        pbar = tqdm(
            ports,
            desc="  Scanning",
            unit="port",
            bar_format=(
                "  {l_bar}{bar:30}{r_bar} [{elapsed}<{remaining}]"
            ),
            colour="cyan",
            dynamic_ncols=True,
        )
        for port_info in pbar:
            r = scan_port(
                port_info,
                baud_rates,
                args.duration,
                args.timeout,
                progress=pbar,
                verbose=args.verbose,
            )
            results.append(r)
        pbar.close()
    else:
        for idx, port_info in enumerate(ports, 1):
            print(f"  [{idx}/{len(ports)}] Scanning {port_info.device} …")
            r = scan_port(
                port_info,
                baud_rates,
                args.duration,
                args.timeout,
                verbose=args.verbose,
            )
            results.append(r)

    scan_end = datetime.now()

    # ── Optional filter ─────────────────────────────────────────────────────
    if args.skip_empty:
        results = [
            r for r in results
            if r.has_nmea or any(br.bytes_read > 0 for br in r.baud_results)
        ]

    # ── Report ──────────────────────────────────────────────────────────────
    print_report(
        results,
        scan_start=scan_start,
        scan_end=scan_end,
        args=args,
        output_file=args.output,
    )

    return 0 if any(r.has_nmea for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
