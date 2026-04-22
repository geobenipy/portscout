#!/usr/bin/env python
from __future__ import print_function

"""
PortScout Win32 Legacy
======================

Simplified PortScout variant for old 32-bit Windows systems and plain
command prompts. The code intentionally avoids:

- dataclasses
- type hints
- f-strings
- ANSI colors
- Unicode box drawing characters
- tqdm

Target compatibility:
- Python 2.7 32-bit
- Python 3.x 32-bit with pyserial installed
"""

import argparse
import re
import sys
import time
from datetime import datetime

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit(
        "[ERROR] pyserial is not installed.\n"
        "        Install it with: pip install pyserial"
    )


PY2 = sys.version_info[0] == 2

if PY2:
    text_type = unicode  # noqa: F821  pylint: disable=undefined-variable
else:
    text_type = str

try:
    PermissionError
except NameError:
    PermissionError = IOError


DEFAULT_BAUDRATES = "4800,9600,19200,38400,57600,115200"


TALKER_IDS = {
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
    "P": "Proprietary",
    "WI": "Weather Instruments",
    "YX": "Transducer",
    "SD": "Sounder",
    "SS": "Sounder",
    "VD": "Velocity Sensor",
    "VM": "Velocity Sensor (Magnetic)",
    "VW": "Velocity Sensor (Water)",
}


SENTENCE_TYPES = {
    "GGA": "GPS fix data",
    "GLL": "Latitude and longitude",
    "GNS": "GNSS fix data",
    "RMC": "Recommended minimum GNSS data",
    "VTG": "Course and ground speed",
    "ZDA": "Time and date",
    "GBS": "Satellite fault detection",
    "DTM": "Datum reference",
    "GRS": "Range residuals",
    "GST": "Pseudorange noise statistics",
    "GSA": "DOP and active satellites",
    "GSV": "Satellites in view",
    "HDG": "Heading with deviation and variation",
    "HDM": "Magnetic heading",
    "HDT": "True heading",
    "ROT": "Rate of turn",
    "RPM": "Engine revolutions",
    "APB": "Autopilot sentence B",
    "BOD": "Bearing origin to destination",
    "BWC": "Bearing and distance to waypoint",
    "BWR": "Bearing and distance to waypoint",
    "BWW": "Bearing waypoint to waypoint",
    "DBT": "Depth below transducer",
    "DPT": "Depth",
    "MTW": "Water temperature",
    "MWV": "Wind speed and angle",
    "MWD": "Wind direction and speed",
    "VDR": "Set and drift",
    "VHW": "Water speed and heading",
    "VWR": "Relative wind speed and angle",
    "XTE": "Cross-track error",
    "RTE": "Routes",
    "WPL": "Waypoint location",
    "VDM": "AIS message from other vessels",
    "VDO": "AIS message from own vessel",
    "PGRME": "Garmin estimated error",
    "PGRMZ": "Garmin altitude",
    "PGRMT": "Garmin sensor status",
    "PUBX": "u-blox proprietary",
}


REGEX_FLAGS = 0
if hasattr(re, "ASCII"):
    REGEX_FLAGS |= re.ASCII


NMEA_RE = re.compile(
    r"\$(?P<sentence>[A-Z0-9]{1,10}(?:,[^\*\r\n]*)?)"
    r"(?:\*(?P<checksum>[0-9A-Fa-f]{2}))?",
    REGEX_FLAGS,
)
CANDIDATE_RE = re.compile(r"\$[A-Z0-9][^\$\r\n]{3,82}", REGEX_FLAGS)
LINE_SPLIT_RE = re.compile(r"[\r\n]+")


def to_text(value):
    if value is None:
        return ""
    if isinstance(value, text_type):
        return value
    try:
        return value.decode("utf-8", "replace")
    except Exception:
        try:
            return value.decode("latin-1", "replace")
        except Exception:
            return text_type(value)


def prompt_input(message):
    if PY2:
        return raw_input(message)  # noqa: F821  pylint: disable=undefined-variable
    return input(message)


def should_pause_on_exit():
    if "--no-pause" in sys.argv:
        return False
    if "--pause" in sys.argv:
        return True
    return bool(getattr(sys, "frozen", False))


def make_baud_result(baud):
    return {
        "baud": baud,
        "bytes_read": 0,
        "sentences": [],
        "errors": [],
        "has_nmea": False,
    }


def make_port_result(port_info):
    return {
        "device": to_text(getattr(port_info, "device", "")),
        "description": to_text(getattr(port_info, "description", "")),
        "hwid": to_text(getattr(port_info, "hwid", "")),
        "accessible": True,
        "baud_results": [],
    }


def compute_checksum(sentence):
    xor_value = 0
    for ch in sentence:
        xor_value ^= ord(ch)
    return xor_value


def validate_and_parse(raw_sentence):
    raw_sentence = to_text(raw_sentence).strip()
    match = NMEA_RE.match(raw_sentence)
    if not match:
        return None

    body = match.group("sentence")
    checksum_text = match.group("checksum")

    checksum_ok = False
    if checksum_text:
        expected = compute_checksum(body)
        checksum_ok = expected == int(checksum_text, 16)

    parts = body.split(",", 1)
    tag = parts[0]

    if tag.startswith("P") and len(tag) >= 2:
        talker = "P"
        formatter = tag[1:]
    elif len(tag) >= 3:
        talker = tag[:2]
        formatter = tag[2:]
    else:
        talker = tag
        formatter = ""

    return {
        "raw": raw_sentence,
        "talker": talker,
        "formatter": formatter,
        "checksum_ok": checksum_ok,
    }


def extract_sentences_from_buffer(raw_bytes):
    text = to_text(raw_bytes)
    sentences = []

    for line in LINE_SPLIT_RE.split(text):
        line = line.strip()
        if not line:
            continue

        for candidate in CANDIDATE_RE.findall(line):
            hit = validate_and_parse(candidate)
            if hit and hit["formatter"]:
                sentences.append(hit)

    return sentences


def get_ports():
    ports = list(list_ports.comports())
    ports.sort(key=lambda item: to_text(getattr(item, "device", "")))
    return ports


def chunk_has_dollar(chunk):
    if not chunk:
        return False
    if PY2:
        return "$" in chunk
    return b"$" in chunk


def combine_chunks(chunks):
    if not chunks:
        if PY2:
            return ""
        return b""
    if PY2:
        return "".join(chunks)
    return b"".join(chunks)


def probe_port(device, baud, read_duration, timeout):
    result = make_baud_result(baud)
    chunks = []
    saw_dollar = False
    serial_handle = None

    try:
        serial_handle = serial.Serial(
            port=device,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

        deadline = time.time() + read_duration
        while time.time() < deadline:
            chunk = serial_handle.read(256)
            if chunk:
                chunks.append(chunk)
                result["bytes_read"] += len(chunk)
                if chunk_has_dollar(chunk):
                    saw_dollar = True

            if result["bytes_read"] > 4096 and saw_dollar:
                break

    except serial.SerialException as exc:
        result["errors"].append(to_text(exc))
        return result
    except PermissionError:
        result["errors"].append("Permission denied - port may already be in use.")
        return result
    except Exception as exc:
        result["errors"].append("Unexpected error: %s" % to_text(exc))
        return result
    finally:
        if serial_handle is not None:
            try:
                serial_handle.close()
            except Exception:
                pass

    raw_data = combine_chunks(chunks)
    if raw_data:
        result["sentences"] = extract_sentences_from_buffer(raw_data)
        result["has_nmea"] = len(result["sentences"]) > 0

    return result


def scan_port(port_info, baud_rates, read_duration, timeout, verbose):
    result = make_port_result(port_info)

    for baud in baud_rates:
        baud_result = probe_port(result["device"], baud, read_duration, timeout)
        result["baud_results"].append(baud_result)

        if baud_result["has_nmea"] and not verbose:
            break

        if baud_result["errors"]:
            for error_text in baud_result["errors"]:
                lowered = error_text.lower()
                if "permission" in lowered or "access is denied" in lowered:
                    result["accessible"] = False
                    return result

    return result


def has_nmea(port_result):
    for item in port_result["baud_results"]:
        if item["has_nmea"]:
            return True
    return False


def get_best_baud(port_result):
    best_baud = None
    best_count = -1

    for item in port_result["baud_results"]:
        if not item["has_nmea"]:
            continue
        hit_count = len(item["sentences"])
        if hit_count > best_count:
            best_count = hit_count
            best_baud = item["baud"]

    return best_baud


def get_all_sentences(port_result):
    all_items = []
    for item in port_result["baud_results"]:
        all_items.extend(item["sentences"])
    return all_items


def sentence_summary(sentences):
    summary = {}

    for sentence in sentences:
        key = "%s%s" % (sentence["talker"], sentence["formatter"])
        if key not in summary:
            summary[key] = {
                "talker": sentence["talker"],
                "formatter": sentence["formatter"],
                "count": 0,
                "cksum_ok": 0,
                "cksum_fail": 0,
            }

        summary[key]["count"] += 1
        if sentence["checksum_ok"]:
            summary[key]["cksum_ok"] += 1
        else:
            summary[key]["cksum_fail"] += 1

    return summary


def describe_talker(talker):
    return TALKER_IDS.get(talker, "Unknown talker")


def describe_formatter(formatter):
    return SENTENCE_TYPES.get(formatter, "Unknown or proprietary sentence")


def format_checksum(ok_count, fail_count):
    total = ok_count + fail_count
    if total <= 0:
        return "n/a"
    percentage = int(round((float(ok_count) / float(total)) * 100.0))
    return "%d/%d (%d%%)" % (ok_count, total, percentage)


def open_text_file_for_write(path):
    if PY2:
        return open(path, "wb")
    return open(path, "w", encoding="utf-8")


def write_output_file(output_file, lines):
    if not output_file:
        return None

    payload = "\n".join(lines)
    try:
        handle = open_text_file_for_write(output_file)
        try:
            if PY2:
                handle.write(payload.encode("utf-8"))
            else:
                handle.write(payload)
        finally:
            handle.close()
        return None
    except IOError as exc:
        return "Could not write report file: %s" % to_text(exc)


def print_report(results, scan_start, scan_end, args):
    lines = []

    def emit(line):
        lines.append(line)

    total_ports = len(results)
    nmea_ports = []
    for item in results:
        if has_nmea(item):
            nmea_ports.append(item)

    duration = (scan_end - scan_start).total_seconds()

    emit("")
    emit("=" * 70)
    emit("PORTSCOUT WIN32 LEGACY")
    emit("Serial COM Port and NMEA Scanner")
    emit("=" * 70)
    emit("Scan started : %s" % scan_start.strftime("%Y-%m-%d %H:%M:%S"))
    emit("Scan ended   : %s" % scan_end.strftime("%Y-%m-%d %H:%M:%S"))
    emit("Duration     : %.1f s" % duration)
    emit("Baud rates   : %s" % ", ".join([str(item) for item in args.baudrates]))
    emit("Read window  : %s s per baud rate" % args.duration)
    emit("=" * 70)
    emit("")

    emit("SUMMARY")
    emit("-" * 70)
    emit("Total COM ports found : %s" % total_ports)
    emit("Ports with NMEA data  : %s" % len(nmea_ports))
    emit("-" * 70)
    emit("")

    if not results:
        emit("No serial ports found on this machine.")
        emit("")
    else:
        for index, port_result in enumerate(results, 1):
            status_text = "NMEA DETECTED" if has_nmea(port_result) else "NO NMEA"
            emit("[%02d] %s - %s" % (index, port_result["device"], status_text))
            emit("    Description : %s" % port_result["description"])
            emit("    Hardware ID : %s" % port_result["hwid"])

            if not port_result["accessible"]:
                emit("    Port is not accessible (busy or permission denied).")
                emit("")
                continue

            if has_nmea(port_result):
                best_baud = get_best_baud(port_result)
                all_sentences = get_all_sentences(port_result)
                summary = sentence_summary(all_sentences)

                emit("    Best baud   : %s" % best_baud)
                emit("    Sentences   : %s" % len(all_sentences))
                emit("")
                emit("    Code      Count   Checksum     Talker / Description")
                emit("    --------  ------  -----------  ------------------------------------")

                summary_keys = sorted(
                    summary.keys(),
                    key=lambda key: (-summary[key]["count"], key),
                )
                for key in summary_keys:
                    info = summary[key]
                    checksum_label = format_checksum(
                        info["cksum_ok"],
                        info["cksum_fail"],
                    )
                    description = "%s / %s" % (
                        describe_talker(info["talker"]),
                        describe_formatter(info["formatter"]),
                    )
                    emit(
                        "    %-8s  %6d  %-11s  %s"
                        % ("$" + key, info["count"], checksum_label, description)
                    )

                if args.verbose:
                    emit("")
                    emit("    Raw sentences:")
                    for sentence in all_sentences[:50]:
                        checksum_flag = "OK" if sentence["checksum_ok"] else "BAD"
                        emit("    [%s] %s" % (checksum_flag, sentence["raw"]))
                    if len(all_sentences) > 50:
                        emit("    ... %d more not shown" % (len(all_sentences) - 50))

                emit("")
            else:
                total_bytes = 0
                all_errors = []
                for baud_result in port_result["baud_results"]:
                    total_bytes += baud_result["bytes_read"]
                    all_errors.extend(baud_result["errors"])

                if total_bytes == 0:
                    emit("    No data received on any baud rate.")
                else:
                    emit(
                        "    Received %d bytes but no valid NMEA sentences were found."
                        % total_bytes
                    )

                seen_errors = set()
                for error_text in all_errors:
                    if error_text in seen_errors:
                        continue
                    seen_errors.add(error_text)
                    emit("    Error: %s" % error_text)

                emit("")

        if nmea_ports:
            emit("=" * 70)
            emit("NMEA PORT QUICK REFERENCE")
            emit("-" * 70)
            for item in nmea_ports:
                summary = sentence_summary(get_all_sentences(item))
                codes = ["$" + code for code in sorted(summary.keys())]
                emit(
                    "%-10s  %6s baud  %s"
                    % (item["device"], get_best_baud(item), ", ".join(codes))
                )
            emit("")

    emit("=" * 70)
    emit("SCAN COMPLETE")
    emit("=" * 70)
    emit("")

    for line in lines:
        print(line)

    write_error = write_output_file(args.output, lines)
    if write_error:
        print("[WARN] %s" % write_error)
    elif args.output:
        print("Report saved to: %s" % args.output)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="portscout_win32",
        description=(
            "Legacy-friendly serial COM port scanner with NMEA 0183 detection."
        ),
        epilog=(
            "Examples:\n"
            "  python portscout_win32.py\n"
            "  python portscout_win32.py --baudrates 4800,9600 --duration 5\n"
            "  python portscout_win32.py --output report.txt --verbose\n"
            "  python portscout_win32.py --pause\n"
            "  portscout_win32_xp.exe --no-pause\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-b",
        "--baudrates",
        default=DEFAULT_BAUDRATES,
        metavar="RATES",
        help="Comma-separated list of baud rates to probe",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=3.0,
        metavar="SEC",
        help="Serial read timeout per attempt in seconds",
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=float,
        default=4.0,
        metavar="SEC",
        help="Read duration per baud rate attempt in seconds",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="FILE",
        help="Write the report to a text file",
    )
    parser.add_argument(
        "--skip-empty",
        action="store_true",
        help="Hide ports that returned no data",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print raw NMEA sentences",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="Wait for Enter before closing",
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Do not wait for Enter before closing",
    )
    return parser


def parse_baudrates(parser, value):
    try:
        baud_rates = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError:
        parser.error("--baudrates must be a comma-separated list of integers.")

    if not baud_rates:
        parser.error("--baudrates is empty.")

    return baud_rates


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.baudrates = parse_baudrates(parser, args.baudrates)

    print("")
    print("PortScout Win32 Legacy - starting scan")
    print("")

    ports = get_ports()
    if not ports:
        print("No serial COM ports detected. Nothing to scan.")
        return 0

    print(
        "Found %d port(s): %s"
        % (len(ports), ", ".join([to_text(getattr(item, "device", "")) for item in ports]))
    )
    print("Probing baud rates: %s" % ", ".join([str(item) for item in args.baudrates]))
    print(
        "Maximum scan time: about %.0f s"
        % (len(ports) * len(args.baudrates) * args.duration)
    )
    print("")

    scan_start = datetime.now()
    results = []

    for index, port_info in enumerate(ports, 1):
        device_name = to_text(getattr(port_info, "device", ""))
        print("[%d/%d] Scanning %s" % (index, len(ports), device_name))
        results.append(
            scan_port(
                port_info,
                args.baudrates,
                args.duration,
                args.timeout,
                args.verbose,
            )
        )

    scan_end = datetime.now()

    if args.skip_empty:
        filtered = []
        for item in results:
            keep_item = False
            if has_nmea(item):
                keep_item = True
            else:
                for baud_result in item["baud_results"]:
                    if baud_result["bytes_read"] > 0:
                        keep_item = True
                        break
            if keep_item:
                filtered.append(item)
        results = filtered

    print_report(results, scan_start, scan_end, args)

    for item in results:
        if has_nmea(item):
            return 0
    return 1


if __name__ == "__main__":
    exit_code = 1

    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("")
        print("Aborted by user.")
        exit_code = 1
    except SystemExit as exc:
        if isinstance(exc.code, int):
            exit_code = exc.code
        elif exc.code is None:
            exit_code = 0
        else:
            exit_code = 1
    except Exception as exc:
        print("")
        print("FATAL ERROR: %s" % to_text(exc))
        exit_code = 1

    if should_pause_on_exit():
        try:
            prompt_input("Press Enter to close...")
        except Exception:
            pass

    sys.exit(exit_code)
