#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H20 Diagnostic Tool
===================
PC diagnostiek voor H20 Esports Campus Amsterdam.

Dit script verzamelt informatie over systeem, CPU, RAM, opslag, GPU, netwerk,
temperaturen en Windows-eventlogs. Daarna wordt een HTML-rapport gegenereerd
en automatisch geopend in de standaardbrowser.

Werkt standalone als .exe (gebouwd met PyInstaller) of direct via Python 3.10+.
"""

from __future__ import annotations

import ctypes
import html
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ----------------------------------------------------------------------------
# Externe libraries - veilig importeren met fallbacks
# ----------------------------------------------------------------------------
try:
    import psutil  # type: ignore
except Exception:  # noqa: BLE001
    psutil = None  # type: ignore

try:
    import wmi  # type: ignore
    import pythoncom  # type: ignore
except Exception:  # noqa: BLE001
    wmi = None  # type: ignore
    pythoncom = None  # type: ignore

try:
    from tqdm import tqdm  # type: ignore
except Exception:  # noqa: BLE001
    # Minimale fallback als tqdm niet beschikbaar is
    def tqdm(iterable=None, total=None, desc=None, **_kwargs):  # type: ignore
        if iterable is not None:
            return iterable
        class _Dummy:
            def update(self, _n=1): pass
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return _Dummy()

try:
    import urllib.request as _urllib_request
    _urllib_request  # zorg dat het beschikbaar is
except Exception:  # noqa: BLE001
    pass


# ----------------------------------------------------------------------------
# Constanten & paden
# ----------------------------------------------------------------------------
APP_NAME = "H20 Diagnostic Tool"
APP_VERSION = "1.0"
H20_RED = "#D4003C"


def get_base_dir() -> Path:
    """Geeft de map terug waar de .exe / het script naast staat."""
    if getattr(sys, "frozen", False):
        # Bij PyInstaller --onefile: de daadwerkelijke .exe-locatie
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def get_resource_path(relative: str) -> Path:
    """Vind resource-bestanden zowel bij script-mode als in een PyInstaller-bundle."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative  # type: ignore[attr-defined]
    return get_base_dir() / relative


BASE_DIR = get_base_dir()
LOG_FILE = BASE_DIR / "h20_diagnostic_log.txt"


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
def setup_logging() -> None:
    """Configureer logging naar bestand naast de .exe."""
    try:
        logging.basicConfig(
            filename=str(LOG_FILE),
            filemode="a",
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        # Als logging-setup faalt (bijv. read-only USB), dan stil doorgaan
        logging.basicConfig(level=logging.CRITICAL)
    logging.info("=== %s v%s gestart ===", APP_NAME, APP_VERSION)


def log_exception(context: str, exc: BaseException) -> None:
    """Log een exception met stack-trace."""
    logging.error("%s: %s", context, exc)
    logging.debug("Traceback:\n%s", traceback.format_exc())


# ----------------------------------------------------------------------------
# Hulpfuncties
# ----------------------------------------------------------------------------
def is_admin() -> bool:
    """Controleer of het proces met beheerdersrechten draait (Windows)."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


def fmt_bytes(num_bytes: Optional[float]) -> str:
    """Formatteer bytes naar een leesbare string (GB/MB/KB)."""
    if num_bytes is None:
        return "Niet beschikbaar"
    try:
        num = float(num_bytes)
    except (TypeError, ValueError):
        return "Niet beschikbaar"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if num < 1024.0:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} EB"


def fmt_uptime(seconds: float) -> str:
    """Formatteer uptime-seconden als 'X dagen, Y uur, Z minuten'."""
    td = timedelta(seconds=int(seconds))
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes = remainder // 60
    parts: List[str] = []
    if days:
        parts.append(f"{days} dag{'en' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} uur")
    parts.append(f"{minutes} minuten")
    return ", ".join(parts)


def new_wmi() -> Optional[Any]:
    """Maak een WMI-client aan; retourneer None als het niet lukt."""
    if wmi is None:
        return None
    try:
        if pythoncom is not None:
            try:
                pythoncom.CoInitialize()
            except Exception:  # noqa: BLE001
                pass
        return wmi.WMI()
    except Exception as exc:  # noqa: BLE001
        log_exception("WMI initialisatie", exc)
        return None


# ----------------------------------------------------------------------------
# Status-datamodel
# ----------------------------------------------------------------------------
STATUS_GOOD = "good"       # Groen  - GOED
STATUS_WARN = "warn"       # Oranje - LET OP
STATUS_CRIT = "crit"       # Rood   - KRITIEK
STATUS_INFO = "info"       # Grijs  - Informatief / niet beschikbaar

STATUS_LABEL = {
    STATUS_GOOD: "GOED",
    STATUS_WARN: "LET OP",
    STATUS_CRIT: "KRITIEK",
    STATUS_INFO: "INFO",
}


def worst(a: str, b: str) -> str:
    """Geeft de slechtste van twee statussen terug."""
    order = {STATUS_INFO: 0, STATUS_GOOD: 1, STATUS_WARN: 2, STATUS_CRIT: 3}
    return a if order.get(a, 0) >= order.get(b, 0) else b


class Section:
    """Eén sectie in het rapport (bv. CPU, RAM)."""

    def __init__(self, name: str, icon: str):
        self.name = name
        self.icon = icon
        self.status: str = STATUS_GOOD
        # rows is een lijst van tuples: (label, waarde, rij-status)
        self.rows: List[Tuple[str, str, str]] = []
        self.banners: List[Tuple[str, str]] = []  # (type, message) type=warn/info/crit
        self.tables: List[Dict[str, Any]] = []    # Voor meervoudige items (schijven, etc.)
        self.issues: List[Any] = []

    def add_issue(self, severity: str, category: str, what: str, why: str, action: str) -> None:
        self.issues.append(_Issue(severity, category, what, why, action))
        if severity in (STATUS_WARN, STATUS_CRIT):
            self.status = worst(self.status, severity)

    def add_row(self, label: str, value: Any, row_status: str = STATUS_INFO) -> None:
        if value is None or value == "":
            value_str = "Niet beschikbaar"
            row_status = STATUS_INFO
        else:
            value_str = str(value)
        self.rows.append((label, value_str, row_status))
        if row_status in (STATUS_WARN, STATUS_CRIT):
            self.status = worst(self.status, row_status)

    def add_banner(self, kind: str, message: str) -> None:
        self.banners.append((kind, message))
        if kind == "warn":
            self.status = worst(self.status, STATUS_WARN)
        elif kind == "crit":
            self.status = worst(self.status, STATUS_CRIT)

    def add_table(self, title: str, headers: List[str], rows: List[List[str]]) -> None:
        self.tables.append({"title": title, "headers": headers, "rows": rows})


@dataclass
class _Issue:
    severity: str   # STATUS_WARN of STATUS_CRIT
    category: str   # bijv. "CPU", "Opslag"
    what: str       # wat is het probleem
    why: str        # waarom is het een probleem
    action: str     # wat moet er gebeuren


# ----------------------------------------------------------------------------
# Terminal-output
# ----------------------------------------------------------------------------
def print_logo() -> None:
    """Print het ASCII-logo naar de terminal."""
    logo_path = get_resource_path("assets/h20_logo.txt")
    try:
        if logo_path.exists():
            print(logo_path.read_text(encoding="utf-8"))
            return
    except Exception as exc:  # noqa: BLE001
        log_exception("Logo laden", exc)
    # Fallback-logo als het bestand ontbreekt
    print(
        "\n"
        "    H20 Esports Campus Amsterdam\n"
        f"    {APP_NAME} v{APP_VERSION}\n"
    )


def print_av_warning() -> None:
    """Print duidelijke antivirus-waarschuwing bij opstarten."""
    print("-" * 66)
    print("Let op: sommige antivirusprogramma's markeren deze tool als")
    print("verdacht vanwege de PyInstaller-verpakking. De tool bevat geen")
    print("schadelijke code. Voeg indien nodig een uitzondering toe in")
    print("Windows Defender voor deze USB-stick.")
    print("-" * 66)
    print()


def check_ok(message: str) -> None:
    print(f"[\u2713] {message}")


def check_fail(message: str) -> None:
    print(f"[!] {message}")


# ============================================================================
# Diagnostische checks
# ============================================================================
def check_system() -> Section:
    """Systeem-info: hostname, Windows-versie, uptime, laatste boot."""
    sec = Section("Systeem", "\U0001F5A5")  # monitor icoon
    try:
        hostname = socket.gethostname()
        sec.add_row("Hostname", hostname, STATUS_GOOD)

        os_name = f"{platform.system()} {platform.release()} ({platform.version()})"
        sec.add_row("Besturingssysteem", os_name, STATUS_GOOD)

        arch = platform.machine()
        sec.add_row("Architectuur", arch, STATUS_GOOD)

        if psutil is not None:
            boot_ts = psutil.boot_time()
            boot_dt = datetime.fromtimestamp(boot_ts)
            uptime_sec = time.time() - boot_ts
            sec.add_row("Laatste boot", boot_dt.strftime("%Y-%m-%d %H:%M:%S"), STATUS_GOOD)
            up_status = STATUS_WARN if uptime_sec > 14 * 86400 else STATUS_GOOD
            sec.add_row("Uptime", fmt_uptime(uptime_sec), up_status)
            if up_status == STATUS_WARN:
                sec.add_banner("warn", "PC langer dan 14 dagen online - herstart aanbevolen.")
                sec.add_issue(STATUS_WARN, "Systeem", "PC meer dan 14 dagen niet herstart",
                              "Langdurig draaien kan geheugenlekkage en instabiliteit veroorzaken",
                              "Start de PC opnieuw op")
        else:
            sec.add_row("Uptime", None)
            sec.add_row("Laatste boot", None)

        check_ok("Systeem-info verzameld")
    except Exception as exc:  # noqa: BLE001
        log_exception("Systeem-check", exc)
        sec.add_banner("crit", f"Systeem-check mislukt: {exc}")
        check_fail("Systeem-check mislukt")
    return sec


def check_cpu() -> Section:
    """CPU: model, cores, kloksnelheid, temperatuur, gebruik over 10s."""
    sec = Section("CPU", "\U0001F9E0")  # hersenen
    try:
        # Model via WMI (platform.processor geeft op Windows meestal ook goede info)
        model = platform.processor() or "Onbekend"
        c = new_wmi()
        if c is not None:
            try:
                procs = c.Win32_Processor()
                if procs:
                    model = procs[0].Name.strip() if procs[0].Name else model
            except Exception as exc:  # noqa: BLE001
                log_exception("WMI CPU-model", exc)
        sec.add_row("Model", model, STATUS_GOOD)

        if psutil is not None:
            cores_physical = psutil.cpu_count(logical=False) or "?"
            cores_logical = psutil.cpu_count(logical=True) or "?"
            sec.add_row("Cores / Threads", f"{cores_physical} / {cores_logical}", STATUS_GOOD)

            freq = psutil.cpu_freq()
            if freq:
                sec.add_row("Kloksnelheid (huidig)", f"{freq.current:.0f} MHz", STATUS_GOOD)
                if freq.max:
                    sec.add_row("Kloksnelheid (max)", f"{freq.max:.0f} MHz", STATUS_GOOD)
            else:
                sec.add_row("Kloksnelheid", None)

            # Gebruik meten over 10 seconden
            print("    Meten CPU-gebruik over 10 seconden...")
            samples = []
            for _ in range(10):
                samples.append(psutil.cpu_percent(interval=1))
            avg = sum(samples) / len(samples)
            peak = max(samples)
            avg_status = STATUS_GOOD if avg < 70 else STATUS_WARN if avg < 90 else STATUS_CRIT
            peak_status = STATUS_GOOD if peak < 85 else STATUS_WARN if peak < 98 else STATUS_CRIT
            sec.add_row("CPU-gebruik gemiddeld (10s)", f"{avg:.1f} %", avg_status)
            sec.add_row("CPU-gebruik piek (10s)", f"{peak:.1f} %", peak_status)
            if avg_status == STATUS_CRIT:
                sec.add_issue(STATUS_CRIT, "CPU", f"CPU-gebruik kritiek hoog ({avg:.0f}%)",
                              "Systeem is overbelast en presteert slecht",
                              "Sluit onnodige processen of herstart de PC")
            elif avg_status == STATUS_WARN:
                sec.add_issue(STATUS_WARN, "CPU", f"CPU-gebruik verhoogd ({avg:.0f}%)",
                              "Systeem draait op de grens van capaciteit",
                              "Controleer welke processen veel CPU gebruiken en sluit ze")
        else:
            sec.add_banner("warn", "psutil niet beschikbaar - beperkt CPU-overzicht.")

        # CPU-temperatuur via WMI MSAcpi_ThermalZoneTemperature
        cpu_temp: Optional[float] = None
        if c is not None:
            try:
                w_root = c  # hoofddomein
                try:
                    w_wmi = wmi.WMI(namespace=r"root\wmi")  # type: ignore[union-attr]
                    zones = w_wmi.MSAcpi_ThermalZoneTemperature()
                    if zones:
                        # Waarde is in tienden van Kelvin
                        kelvin_tenths = zones[0].CurrentTemperature
                        cpu_temp = (kelvin_tenths / 10.0) - 273.15
                except Exception as exc:  # noqa: BLE001
                    log_exception("WMI ThermalZone", exc)

                # Alternatief: via psutil (vaak leeg op Windows)
                if cpu_temp is None and psutil is not None and hasattr(psutil, "sensors_temperatures"):
                    try:
                        temps = psutil.sensors_temperatures()
                        for entries in temps.values():
                            for entry in entries:
                                if entry.current and 20 < entry.current < 120:
                                    cpu_temp = entry.current
                                    break
                            if cpu_temp is not None:
                                break
                    except Exception as exc:  # noqa: BLE001
                        log_exception("psutil sensors_temperatures", exc)
            except Exception as exc:  # noqa: BLE001
                log_exception("CPU-temperatuur", exc)

        if cpu_temp is not None:
            status = STATUS_GOOD if cpu_temp < 70 else STATUS_WARN if cpu_temp < 85 else STATUS_CRIT
            sec.add_row("CPU-temperatuur", f"{cpu_temp:.1f} \u00B0C", status)
            if status == STATUS_CRIT:
                sec.add_issue(STATUS_CRIT, "CPU", f"CPU-temperatuur kritiek ({cpu_temp:.0f}\u00B0C)",
                              "Oververhitting beschadigt hardware en kan de PC afsluiten",
                              "Schakel de PC uit en reinig de koeling direct")
            elif status == STATUS_WARN:
                sec.add_issue(STATUS_WARN, "CPU", f"CPU-temperatuur verhoogd ({cpu_temp:.0f}\u00B0C)",
                              "Te hoge temperatuur verkort levensduur en verlaagt prestaties",
                              "Reinig de koelventilator en controleer de thermische pasta")
        else:
            sec.add_row("CPU-temperatuur", None)
            if not is_admin():
                sec.add_banner("warn", "Temperatuur niet leesbaar - vereist meestal beheerdersrechten.")
            check_fail("CPU temperatuur niet beschikbaar")

        check_ok("CPU check voltooid")
    except Exception as exc:  # noqa: BLE001
        log_exception("CPU-check", exc)
        sec.add_banner("crit", f"CPU-check mislukt: {exc}")
        check_fail("CPU-check mislukt")
    return sec


def check_ram() -> Section:
    """RAM: totaal, gebruik, slots, snelheid."""
    sec = Section("Geheugen (RAM)", "\U0001F4BE")  # diskette
    try:
        if psutil is not None:
            mem = psutil.virtual_memory()
            total_gb = mem.total / (1024 ** 3)
            used_gb = mem.used / (1024 ** 3)
            pct = mem.percent
            sec.add_row("Totaal", f"{total_gb:.2f} GB", STATUS_GOOD)
            pct_status = STATUS_GOOD if pct < 75 else STATUS_WARN if pct < 90 else STATUS_CRIT
            sec.add_row("In gebruik", f"{used_gb:.2f} GB ({pct:.0f} %)", pct_status)
            sec.add_row("Beschikbaar", f"{mem.available / (1024 ** 3):.2f} GB", STATUS_GOOD)
            if pct_status == STATUS_CRIT:
                sec.add_issue(STATUS_CRIT, "RAM", f"RAM-gebruik kritiek hoog ({pct:.0f}%)",
                              "Systeem gebruikt wisselgeheugen, wat sterk vertraagt",
                              "Sluit programma's of voeg extra RAM toe")
            elif pct_status == STATUS_WARN:
                sec.add_issue(STATUS_WARN, "RAM", f"RAM-gebruik hoog ({pct:.0f}%)",
                              "Weinig vrij geheugen beschikbaar",
                              "Sluit onnodige programma's")
        else:
            sec.add_banner("warn", "psutil niet beschikbaar - gebruik onbekend.")

        c = new_wmi()
        if c is not None:
            try:
                slots_info = c.Win32_PhysicalMemoryArray()
                total_slots = 0
                for arr in slots_info:
                    if arr.MemoryDevices is not None:
                        total_slots += int(arr.MemoryDevices)
                modules = c.Win32_PhysicalMemory()
                populated = len(modules)
                if total_slots:
                    sec.add_row("Slots (bezet / totaal)", f"{populated} / {total_slots}", STATUS_GOOD)
                else:
                    sec.add_row("Bezette slots", f"{populated}", STATUS_GOOD)

                # Tabel per module
                headers = ["#", "Capaciteit", "Snelheid", "Fabrikant", "Slot"]
                rows: List[List[str]] = []
                for idx, m in enumerate(modules, start=1):
                    cap = fmt_bytes(int(m.Capacity)) if getattr(m, "Capacity", None) else "?"
                    speed = f"{m.Speed} MHz" if getattr(m, "Speed", None) else "?"
                    manu = (m.Manufacturer or "?").strip()
                    slot = (m.DeviceLocator or "?").strip()
                    rows.append([str(idx), cap, speed, manu, slot])
                if rows:
                    sec.add_table("RAM-modules", headers, rows)
            except Exception as exc:  # noqa: BLE001
                log_exception("WMI RAM-modules", exc)
                sec.add_banner("warn", "Moduledetails niet leesbaar.")
        else:
            sec.add_banner("warn", "WMI niet beschikbaar - slots en moduledetails onbekend.")

        check_ok("RAM check voltooid")
    except Exception as exc:  # noqa: BLE001
        log_exception("RAM-check", exc)
        sec.add_banner("crit", f"RAM-check mislukt: {exc}")
        check_fail("RAM-check mislukt")
    return sec


def _quick_disk_speed_test(drive_letter: str) -> Optional[Tuple[float, float]]:
    """Doe een snelle lees/schrijftest op de opgegeven drive. Retourneer (write_MBs, read_MBs)."""
    try:
        test_dir = Path(f"{drive_letter}:/").resolve()
        # Gebruik tempfile in de root van de drive
        test_file = test_dir / "h20_diag_speedtest.tmp"
        # Schrijven: 64 MB aan data in 1 MB blokken
        size_mb = 64
        block = os.urandom(1024 * 1024)
        t0 = time.perf_counter()
        with open(test_file, "wb") as f:
            for _ in range(size_mb):
                f.write(block)
            f.flush()
            os.fsync(f.fileno())
        write_dt = time.perf_counter() - t0
        write_speed = size_mb / write_dt if write_dt > 0 else 0.0

        # Lezen
        t0 = time.perf_counter()
        with open(test_file, "rb") as f:
            while f.read(1024 * 1024):
                pass
        read_dt = time.perf_counter() - t0
        read_speed = size_mb / read_dt if read_dt > 0 else 0.0

        try:
            test_file.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        return write_speed, read_speed
    except PermissionError:
        return None
    except Exception as exc:  # noqa: BLE001
        log_exception(f"Snelheidstest {drive_letter}", exc)
        return None


def check_storage() -> Section:
    """Opslag: alle schijven met grootte, vrije ruimte, SMART, snelheid."""
    sec = Section("Opslag", "\U0001F4BD")  # minidisk
    try:
        c = new_wmi()

        # Bouw SMART-status-map per drive-letter
        smart_map: Dict[str, str] = {}
        disk_models: Dict[str, str] = {}  # drive-letter -> model
        disk_type_map: Dict[str, str] = {}  # drive-letter -> SSD/HDD

        if c is not None:
            try:
                # Koppel Win32_DiskDrive -> Win32_DiskPartition -> Win32_LogicalDisk
                for disk in c.Win32_DiskDrive():
                    model = (disk.Model or "").strip()
                    status = (disk.Status or "").strip()
                    # Vertaal Windows SMART-status
                    if status.upper() in ("OK", "PRED FAIL", "DEGRADED"):
                        smart_status = "OK" if status.upper() == "OK" else "Warning"
                    elif status.upper() in ("ERROR", "STRESSED", "NONRECOVER"):
                        smart_status = "Error"
                    else:
                        smart_status = status or "Onbekend"

                    media_type = (getattr(disk, "MediaType", "") or "").lower()
                    # Heuristiek: 'ssd' in model of MediaType => SSD, anders HDD
                    if "ssd" in model.lower() or "nvme" in model.lower() or "solid state" in media_type:
                        dtype = "SSD"
                    else:
                        dtype = "HDD"

                    # Verbind disk met logische schijven
                    for partition in disk.associators("Win32_DiskDriveToDiskPartition"):
                        for logical in partition.associators("Win32_LogicalDiskToPartition"):
                            letter = (logical.DeviceID or "").rstrip(":").upper()
                            if letter:
                                smart_map[letter] = smart_status
                                disk_models[letter] = model or "Onbekend"
                                disk_type_map[letter] = dtype
            except Exception as exc:  # noqa: BLE001
                log_exception("WMI schijven mapping", exc)

        # Loop alle schijven met psutil
        if psutil is None:
            sec.add_banner("crit", "psutil niet beschikbaar - schijven niet leesbaar.")
            check_fail("Opslag-check mislukt")
            return sec

        partitions = psutil.disk_partitions(all=False)
        headers = ["Letter", "Model", "Type", "Totaal", "Vrij", "Vrij %", "SMART", "Schrijven", "Lezen"]
        rows: List[List[str]] = []
        worst_status = STATUS_GOOD

        for part in partitions:
            letter = (part.device or "").rstrip(":\\").upper()
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception as exc:  # noqa: BLE001
                log_exception(f"disk_usage {part.device}", exc)
                continue

            free_pct = 100.0 - usage.percent
            if free_pct < 10:
                free_status = STATUS_CRIT
            elif free_pct < 20:
                free_status = STATUS_WARN
            else:
                free_status = STATUS_GOOD

            smart = smart_map.get(letter, "Niet beschikbaar")
            smart_status = STATUS_GOOD if smart == "OK" else STATUS_WARN if smart == "Warning" else STATUS_CRIT if smart == "Error" else STATUS_INFO
            if smart_status == STATUS_CRIT:
                sec.add_issue(STATUS_CRIT, "Opslag", f"Schijf {letter}: SMART-fout gedetecteerd",
                              "Risico op onherstelbaar dataverlies",
                              f"Maak direct een backup en vervang schijf {letter}")
            elif smart_status == STATUS_WARN:
                sec.add_issue(STATUS_WARN, "Opslag", f"Schijf {letter}: SMART-waarschuwing",
                              "Schijf vertoont tekenen van slijtage",
                              f"Plan vervanging van schijf {letter} en maak een backup")
            if free_pct < 10:
                sec.add_issue(STATUS_CRIT, "Opslag", f"Schijf {letter}: kritiek weinig ruimte ({free_pct:.0f}% vrij)",
                              "PC kan vastlopen of crashen bij geen vrije ruimte",
                              f"Verwijder bestanden van schijf {letter} of vergroot de opslag direct")
            elif free_pct < 20:
                sec.add_issue(STATUS_WARN, "Opslag", f"Schijf {letter}: bijna vol ({free_pct:.0f}% vrij)",
                              "Weinig vrije ruimte vertraagt de PC",
                              f"Verwijder bestanden van schijf {letter} of vergroot de opslag")

            # Snelheidstest enkel op vaste schijven met voldoende vrije ruimte
            speed_str_w = "Niet beschikbaar"
            speed_str_r = "Niet beschikbaar"
            if usage.free > 200 * 1024 * 1024 and "fixed" in (part.opts or "").lower():
                res = _quick_disk_speed_test(letter)
                if res is not None:
                    speed_str_w = f"{res[0]:.0f} MB/s"
                    speed_str_r = f"{res[1]:.0f} MB/s"
            elif usage.free > 200 * 1024 * 1024:
                # Probeer toch voor alle vaste letters
                res = _quick_disk_speed_test(letter)
                if res is not None:
                    speed_str_w = f"{res[0]:.0f} MB/s"
                    speed_str_r = f"{res[1]:.0f} MB/s"

            row_status = worst(free_status, smart_status)
            worst_status = worst(worst_status, row_status)

            rows.append([
                f"{letter}:",
                disk_models.get(letter, "Onbekend"),
                disk_type_map.get(letter, "?"),
                fmt_bytes(usage.total),
                fmt_bytes(usage.free),
                f"{free_pct:.1f} %",
                smart,
                speed_str_w,
                speed_str_r,
            ])

        if rows:
            sec.add_table("Alle schijven", headers, rows)
            sec.status = worst(sec.status, worst_status)
        else:
            sec.add_banner("warn", "Geen schijven gedetecteerd.")

        check_ok("Opslag check voltooid")
    except Exception as exc:  # noqa: BLE001
        log_exception("Opslag-check", exc)
        sec.add_banner("crit", f"Opslag-check mislukt: {exc}")
        check_fail("Opslag-check mislukt")
    return sec


def check_gpu() -> Section:
    """GPU: model, VRAM, temperatuur, driver-versie."""
    sec = Section("GPU", "\U0001F3AE")  # gamepad
    try:
        c = new_wmi()
        if c is None:
            sec.add_banner("warn", "WMI niet beschikbaar - GPU-info beperkt.")
            check_fail("GPU check overgeslagen")
            return sec

        gpus = []
        try:
            gpus = c.Win32_VideoController()
        except Exception as exc:  # noqa: BLE001
            log_exception("WMI VideoController", exc)

        if not gpus:
            sec.add_banner("warn", "Geen GPU gedetecteerd via WMI.")
            check_fail("GPU niet gedetecteerd")
            return sec

        for idx, gpu in enumerate(gpus, start=1):
            name = (gpu.Name or "Onbekend").strip()
            sec.add_row(f"GPU {idx}", name, STATUS_GOOD)
            drv = getattr(gpu, "DriverVersion", None)
            drv_date = getattr(gpu, "DriverDate", None)
            sec.add_row(f"GPU {idx} driver", drv, STATUS_GOOD if drv else STATUS_INFO)
            if drv_date:
                try:
                    # WMI-datum formaat: YYYYMMDDhhmmss.xxxxxx
                    drv_date_fmt = f"{str(drv_date)[:4]}-{str(drv_date)[4:6]}-{str(drv_date)[6:8]}"
                    sec.add_row(f"GPU {idx} driverdatum", drv_date_fmt, STATUS_GOOD)
                except Exception:  # noqa: BLE001
                    pass

        # GPU-temperatuur vereist meestal NVIDIA/AMD-specifieke libs of OpenHardwareMonitor
        sec.add_row("GPU-temperatuur", None)
        sec.add_banner("warn", "GPU-temperatuur niet leesbaar zonder extra tools (OpenHardwareMonitor).")
        check_ok("GPU check voltooid")
    except Exception as exc:  # noqa: BLE001
        log_exception("GPU-check", exc)
        sec.add_banner("crit", f"GPU-check mislukt: {exc}")
        check_fail("GPU-check mislukt")
    return sec


def check_network() -> Section:
    """Netwerk: adapters, IP's, ping naar 8.8.8.8, speedtest."""
    sec = Section("Netwerk", "\U0001F310")  # wereldbol
    try:
        if psutil is not None:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            headers = ["Adapter", "Status", "IPv4", "MAC"]
            rows: List[List[str]] = []
            for name, addr_list in addrs.items():
                st = stats.get(name)
                if st is None:
                    continue
                # Sla loopback en neer-adapters over uit de tabel, maar toon wel iets
                ipv4 = ""
                mac = ""
                for a in addr_list:
                    fam = getattr(a, "family", None)
                    if fam is not None and str(fam).endswith("AF_INET"):
                        ipv4 = a.address
                    elif fam is not None and str(fam).endswith("AF_LINK"):
                        mac = a.address
                    elif fam == socket.AF_INET:
                        ipv4 = a.address
                status = "Actief" if st.isup else "Uit"
                rows.append([name, status, ipv4 or "-", mac or "-"])
            if rows:
                sec.add_table("Netwerkadapters", headers, rows)
        else:
            sec.add_banner("warn", "psutil niet beschikbaar - adapters onbekend.")

        # Ping-test naar 8.8.8.8 (10 pings)
        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ping_cmd = ["ping", "-n", "10", "-w", "1000", "8.8.8.8"]
            proc = subprocess.run(
                ping_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=creationflags,
            )
            output = proc.stdout + proc.stderr
            # Parse resultaten
            import re
            # Gemiddelde: "Average = 12ms"
            avg_match = re.search(r"(?:Average|Gemiddelde)\s*=\s*(\d+)\s*ms", output)
            loss_match = re.search(r"\((\d+)%\s*(?:loss|verlies)\)", output)
            avg = int(avg_match.group(1)) if avg_match else None
            loss = int(loss_match.group(1)) if loss_match else None

            if avg is not None:
                ping_status = STATUS_GOOD if avg < 30 else STATUS_WARN if avg < 80 else STATUS_CRIT
                sec.add_row("Ping naar 8.8.8.8 (gemiddelde)", f"{avg} ms", ping_status)
                if ping_status == STATUS_CRIT:
                    sec.add_issue(STATUS_CRIT, "Netwerk", f"Kritiek hoge netwerk-latentie ({avg} ms)",
                                  "Hoge ping maakt online gaming en remote work onbruikbaar",
                                  "Controleer netwerkkabel en router, bel internet provider")
                elif ping_status == STATUS_WARN:
                    sec.add_issue(STATUS_WARN, "Netwerk", f"Verhoogde netwerk-latentie ({avg} ms)",
                                  "Hoge ping beïnvloedt gameprestaties",
                                  "Controleer netwerkkabel of schakel naar bedraad internet")
            else:
                sec.add_row("Ping naar 8.8.8.8 (gemiddelde)", None)

            if loss is not None:
                loss_status = STATUS_GOOD if loss == 0 else STATUS_WARN if loss < 20 else STATUS_CRIT
                sec.add_row("Packet loss", f"{loss} %", loss_status)
                if loss_status == STATUS_CRIT:
                    sec.add_issue(STATUS_CRIT, "Netwerk", f"Ernstig pakketverlies ({loss}%)",
                                  "Verbinding is onstabiel, online gaming en videobellen werken niet",
                                  "Vervang netwerkkabel of start router opnieuw op")
                elif loss_status == STATUS_WARN:
                    sec.add_issue(STATUS_WARN, "Netwerk", f"Pakketverlies gedetecteerd ({loss}%)",
                                  "Instabiele verbinding kan online prestaties verminderen",
                                  "Controleer netwerkkabel en router")
            else:
                sec.add_row("Packet loss", None)
        except Exception as exc:  # noqa: BLE001
            log_exception("Ping-test", exc)
            sec.add_banner("warn", "Ping-test mislukt (firewall of geen internet).")

        # Speedtest via HTTP download + upload (geen SSL, werkt altijd)
        try:
            print("    Uitvoeren speedtest (download + upload)...")
            import urllib.request
            import ssl

            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            # Download: probeer meerdere betrouwbare HTTP-servers
            dl: Optional[float] = None
            for dl_url in [
                "http://ipv4.download.thinkbroadband.com/10MB.zip",
                "http://speedtest.tele2.net/10MB.zip",
                "http://proof.ovh.net/files/10Mb.dat",
            ]:
                try:
                    t0 = time.perf_counter()
                    with urllib.request.urlopen(dl_url, timeout=20) as resp:
                        dl_bytes = len(resp.read())
                    dl_elapsed = time.perf_counter() - t0
                    if dl_elapsed > 0:
                        dl = (dl_bytes * 8) / (dl_elapsed * 1_000_000)
                    break
                except Exception:  # noqa: BLE001
                    continue

            # Upload: 2 MB naar meerdere fallback-servers
            ul: Optional[float] = None
            ul_data = os.urandom(2 * 1024 * 1024)
            for ul_url in [
                "https://httpbin.org/post",
                "https://postman-echo.com/post",
                "https://speed.cloudflare.com/__up",
            ]:
                try:
                    req = urllib.request.Request(ul_url, data=ul_data, method="POST")
                    req.add_header("Content-Type", "application/octet-stream")
                    t0 = time.perf_counter()
                    with urllib.request.urlopen(req, timeout=30, context=ssl_ctx) as resp:
                        resp.read()
                    ul_elapsed = time.perf_counter() - t0
                    if ul_elapsed > 0:
                        ul = (len(ul_data) * 8) / (ul_elapsed * 1_000_000)
                    break
                except Exception as exc:  # noqa: BLE001
                    log_exception(f"Speedtest upload ({ul_url})", exc)
                    continue

            if dl is not None:
                dl_status = STATUS_GOOD if dl > 50 else STATUS_WARN if dl > 15 else STATUS_CRIT
                sec.add_row("Download", f"{dl:.1f} Mbps", dl_status)
                if dl_status == STATUS_CRIT:
                    sec.add_issue(STATUS_CRIT, "Netwerk", f"Kritiek lage downloadsnelheid ({dl:.0f} Mbps)",
                                  "Internetverbinding is te traag voor gaming en streaming",
                                  "Bel internet provider of controleer router")
                elif dl_status == STATUS_WARN:
                    sec.add_issue(STATUS_WARN, "Netwerk", f"Lage downloadsnelheid ({dl:.0f} Mbps)",
                                  "Updates en streaming kunnen vertragen",
                                  "Controleer of andere apparaten bandbreedte gebruiken")
            else:
                sec.add_row("Download", None)

            if ul is not None:
                ul_status = STATUS_GOOD if ul > 10 else STATUS_WARN if ul > 3 else STATUS_CRIT
                sec.add_row("Upload", f"{ul:.1f} Mbps", ul_status)
            else:
                sec.add_row("Upload", None)

        except Exception as exc:  # noqa: BLE001
            log_exception("Speedtest", exc)
            sec.add_banner("warn", "Speedtest mislukt (geen internet of firewall blokkeert).")
            sec.add_row("Download", None)
            sec.add_row("Upload", None)

        check_ok("Netwerk check voltooid")
    except Exception as exc:  # noqa: BLE001
        log_exception("Netwerk-check", exc)
        sec.add_banner("crit", f"Netwerk-check mislukt: {exc}")
        check_fail("Netwerk-check mislukt")
    return sec


def check_temperatures() -> Section:
    """Alle beschikbare temperatuursensoren via psutil."""
    sec = Section("Temperaturen", "\U0001F321")  # thermometer
    try:
        if psutil is None or not hasattr(psutil, "sensors_temperatures"):
            sec.add_banner("warn", "Sensoren niet leesbaar - psutil biedt op Windows beperkte ondersteuning.")
            sec.add_row("Sensoren", None)
            check_fail("Temperaturen niet beschikbaar")
            return sec

        try:
            temps = psutil.sensors_temperatures()
        except Exception as exc:  # noqa: BLE001
            log_exception("sensors_temperatures", exc)
            temps = {}

        # Ook via WMI ThermalZone proberen
        c = None
        thermal_zones: List[Tuple[str, float]] = []
        try:
            w_wmi = wmi.WMI(namespace=r"root\wmi") if wmi is not None else None  # type: ignore[union-attr]
            if w_wmi is not None:
                zones = w_wmi.MSAcpi_ThermalZoneTemperature()
                for idx, z in enumerate(zones, start=1):
                    kelvin = z.CurrentTemperature / 10.0
                    celsius = kelvin - 273.15
                    thermal_zones.append((f"ThermalZone {idx}", celsius))
        except Exception as exc:  # noqa: BLE001
            log_exception("WMI ThermalZone temps", exc)

        added_any = False
        for chip, entries in temps.items():
            for entry in entries:
                if entry.current is None:
                    continue
                label = f"{chip} - {entry.label}" if entry.label else chip
                t = entry.current
                if t < 20 or t > 120:
                    continue
                status = STATUS_GOOD if t < 70 else STATUS_WARN if t < 85 else STATUS_CRIT
                sec.add_row(label, f"{t:.1f} \u00B0C", status)
                added_any = True

        for label, t in thermal_zones:
            status = STATUS_GOOD if t < 70 else STATUS_WARN if t < 85 else STATUS_CRIT
            sec.add_row(label, f"{t:.1f} \u00B0C", status)
            added_any = True

        if not added_any:
            sec.add_row("Sensoren", None)
            sec.add_banner("warn", "Geen bruikbare sensoren - vereist meestal beheerdersrechten of extra tools.")
            check_fail("Temperatuur-sensoren niet beschikbaar")
        else:
            check_ok("Temperaturen uitgelezen")
    except Exception as exc:  # noqa: BLE001
        log_exception("Temperatuur-check", exc)
        sec.add_banner("crit", f"Temperatuur-check mislukt: {exc}")
        check_fail("Temperatuur-check mislukt")
    return sec


def check_eventlog() -> Section:
    """Laatste 10 kritieke errors uit Windows-eventlog."""
    sec = Section("Windows Eventlog", "\U0001F4DC")  # boekrol
    try:
        sec.add_banner("info",
            "Het Windows-eventlog registreert alle systeemfouten en crashes. "
            "Kritieke fouten kunnen wijzen op defecte hardware (RAM, schijf), "
            "stuurprogrammaproblemen of herhalende crashes die de PC instabiel maken.")
        c = new_wmi()
        if c is None:
            sec.add_banner("warn", "WMI niet beschikbaar - eventlog niet leesbaar.")
            check_fail("Eventlog overgeslagen")
            return sec

        if not is_admin():
            sec.add_banner(
                "warn",
                "Deze check vereist beheerdersrechten. Start de tool als administrator voor volledige resultaten.",
            )

        try:
            # Event Type 1 = Error. Sorteer op tijd, neem laatste 10.
            events = c.Win32_NTLogEvent(Type="Error")
        except Exception as exc:  # noqa: BLE001
            log_exception("WMI NTLogEvent", exc)
            events = []

        if not events:
            sec.add_row("Recente fouten", "Geen (of niet leesbaar)", STATUS_GOOD)
            check_ok("Eventlog gelezen")
            return sec

        # Sorteer op TimeGenerated (laatste eerst) - WMI geeft strings
        try:
            events_sorted = sorted(
                events,
                key=lambda e: str(e.TimeGenerated or ""),
                reverse=True,
            )[:10]
        except Exception:  # noqa: BLE001
            events_sorted = events[:10]

        headers = ["Datum/tijd", "Bron", "Bericht"]
        rows: List[List[str]] = []
        for ev in events_sorted:
            ts = str(ev.TimeGenerated or "")
            # Formaat: YYYYMMDDhhmmss.xxxxxx+zzz
            try:
                ts_fmt = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}:{ts[12:14]}"
            except Exception:  # noqa: BLE001
                ts_fmt = ts
            source = str(ev.SourceName or "Onbekend")
            msg = str(ev.Message or "").strip()
            if len(msg) > 240:
                msg = msg[:237] + "..."
            rows.append([ts_fmt, source, msg])

        if rows:
            sec.add_table("Laatste 10 errors", headers, rows)
            sec.status = worst(sec.status, STATUS_WARN)
            sec.add_issue(STATUS_WARN, "Eventlog", f"{len(rows)} kritieke fout(en) in Windows-eventlog",
                          "Kan wijzen op hardware- of softwareproblemen",
                          "Bekijk de eventlog-sectie voor details en neem contact op met IT")

        check_ok("Eventlog check voltooid")
    except Exception as exc:  # noqa: BLE001
        log_exception("Eventlog-check", exc)
        sec.add_banner("crit", f"Eventlog-check mislukt: {exc}")
        check_fail("Eventlog-check mislukt")
    return sec


# ============================================================================
# HTML-rapport
# ============================================================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<title>H20 Diagnostic Tool - Rapport</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0d0d0d;
    --panel: #161616;
    --panel-2: #1d1d1d;
    --border: #2a2a2a;
    --text: #e8e8e8;
    --muted: #8c8c8c;
    --accent: __H20_RED__;
    --good: #3ccf4e;
    --warn: #f5a623;
    --crit: #ef2b2b;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    background: var(--bg);
    color: var(--text);
    font-family: 'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace;
    font-size: 14px;
    line-height: 1.5;
  }
  .container { max-width: 1180px; margin: 0 auto; padding: 40px 24px 80px; }
  header { display: flex; align-items: center; gap: 18px; margin-bottom: 28px; border-bottom: 1px solid var(--border); padding-bottom: 20px; }
  .logo { font-size: 28px; font-weight: 700; letter-spacing: 2px; }
  .logo span { color: var(--accent); }
  header .sub { color: var(--muted); font-size: 12px; margin-top: 4px; }
  .summary {
    background: var(--panel);
    border: 1px solid var(--border);
    border-left: 4px solid var(--accent);
    padding: 24px;
    margin-bottom: 28px;
    border-radius: 4px;
  }
  .summary .big {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: 2px;
    margin-bottom: 6px;
  }
  .summary.good .big { color: var(--good); }
  .summary.warn .big { color: var(--warn); }
  .summary.crit .big { color: var(--crit); }
  .summary .meta { color: var(--muted); font-size: 12px; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
    gap: 18px;
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 4px;
    overflow: hidden;
  }
  .card-head {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 18px;
    border-bottom: 1px solid var(--border);
    background: var(--panel-2);
  }
  .card-head .icon { font-size: 18px; }
  .card-head .title { font-weight: 700; flex: 1; letter-spacing: 1px; }
  .badge {
    font-size: 11px;
    font-weight: 700;
    padding: 4px 10px;
    border-radius: 2px;
    letter-spacing: 1.5px;
  }
  .badge.good { background: rgba(60,207,78,.15); color: var(--good); border: 1px solid rgba(60,207,78,.4); }
  .badge.warn { background: rgba(245,166,35,.15); color: var(--warn); border: 1px solid rgba(245,166,35,.4); }
  .badge.crit { background: rgba(239,43,43,.15); color: var(--crit); border: 1px solid rgba(239,43,43,.4); }
  .badge.info { background: rgba(140,140,140,.15); color: var(--muted); border: 1px solid rgba(140,140,140,.4); }
  .card-body { padding: 14px 18px; }
  .row {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 8px 0;
    border-bottom: 1px dashed var(--border);
    word-break: break-word;
  }
  .row:last-child { border-bottom: none; }
  .row .k { color: var(--muted); }
  .row .v { font-weight: 500; text-align: right; }
  .row .v.good { color: var(--good); }
  .row .v.warn { color: var(--warn); }
  .row .v.crit { color: var(--crit); }
  .row .v.info { color: var(--muted); font-style: italic; }
  .banner {
    padding: 10px 14px;
    margin: 10px 0;
    border-radius: 3px;
    font-size: 13px;
    border-left: 3px solid;
  }
  .banner.warn { background: rgba(245,166,35,.08); border-color: var(--warn); color: #f5c680; }
  .banner.crit { background: rgba(239,43,43,.08); border-color: var(--crit); color: #ff8989; }
  .banner.info { background: rgba(140,140,140,.08); border-color: var(--muted); color: var(--muted); }
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 12px;
    font-size: 12px;
  }
  table th, table td {
    padding: 8px 10px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  table th {
    background: var(--panel-2);
    color: var(--muted);
    font-weight: 500;
    letter-spacing: 1px;
    text-transform: uppercase;
    font-size: 11px;
  }
  .tbl-title {
    margin-top: 14px;
    margin-bottom: 4px;
    color: var(--muted);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  footer {
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
    color: var(--muted);
    font-size: 12px;
    text-align: center;
  }
  footer span.accent { color: var(--accent); }
  /* --- Samenvatting & Problemen --- */
  .sumblock {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 4px;
    margin-bottom: 28px;
    overflow: hidden;
  }
  .sumblock-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px;
    background: var(--panel-2);
    border-bottom: 1px solid var(--border);
    font-weight: 700;
    letter-spacing: 1px;
    font-size: 13px;
  }
  .sumblock-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 16px; }
  .sum-section-title {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 8px;
  }
  .sum-overall { font-size: 15px; font-weight: 600; }
  .sum-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
  .sum-item { display: flex; gap: 10px; font-size: 13px; line-height: 1.5; }
  .sum-icon { flex-shrink: 0; font-size: 15px; line-height: 1.5; }
  .sum-text { flex: 1; }
  .sum-text strong { display: block; }
  .sum-text .sum-why { color: var(--muted); font-size: 12px; }
  .sum-text .sum-action { color: var(--warn); font-size: 12px; font-weight: 600; }
  .sum-item.crit .sum-text strong { color: var(--crit); }
  .sum-item.warn .sum-text strong { color: var(--warn); }
  .sum-actions-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
  .sum-actions-list li { font-size: 13px; display: flex; gap: 8px; align-items: flex-start; }
  .sum-actions-list li::before { content: "→"; color: var(--accent); font-weight: 700; flex-shrink: 0; }
  .sum-action-cat { color: var(--muted); font-size: 11px; }
  @media (max-width: 700px) {
    .grid { grid-template-columns: 1fr; }
    .container { padding: 20px 12px 60px; }
  }
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <div class="logo">H<span>2</span>0 <span style="color: var(--muted); font-weight: 400; font-size: 14px; letter-spacing: 1px;">DIAGNOSTIC TOOL</span></div>
      <div class="sub">__HOSTNAME__ &middot; __TIMESTAMP__</div>
    </div>
  </header>

  <div class="summary __SUMMARY_CLASS__">
    <div class="big">__SUMMARY_LABEL__</div>
    <div class="meta">Algemene PC-status op basis van __SECTION_COUNT__ checks.</div>
  </div>

  __SUMMARY_BLOCK__

  <div class="grid">
    __CARDS__
  </div>

  <footer>
    Rapport gegenereerd op __TIMESTAMP__<br>
    <span class="accent">H20 Esports Campus Amsterdam</span> &mdash; Diagnostic Tool v__VERSION__
  </footer>
</div>
</body>
</html>
"""


def build_summary_html(sections: List[Section]) -> str:
    """Genereer de Samenvatting & Problemen sectie bovenaan het rapport."""
    all_issues: List[_Issue] = []
    for sec in sections:
        all_issues.extend(sec.issues)

    overall = STATUS_GOOD
    for s in sections:
        overall = worst(overall, s.status)

    icon_map = {STATUS_CRIT: "\U0001F534", STATUS_WARN: "\U0001F7E1", STATUS_GOOD: "\U0001F7E2"}
    label_map = {STATUS_CRIT: "KRITIEK — directe actie vereist", STATUS_WARN: "LET OP — aandacht gewenst", STATUS_GOOD: "GEZOND — geen problemen gevonden"}
    overall_icon = icon_map.get(overall, "\U0001F7E2")
    overall_label = label_map.get(overall, "GEZOND")

    parts: List[str] = []

    # Samenvatting
    parts.append(
        '<div>'
        f'<div class="sum-section-title">Samenvatting</div>'
        f'<div class="sum-overall">{overall_icon} Systeem: {html.escape(overall_label)}</div>'
        '</div>'
    )

    # Problemen
    if all_issues:
        crits = [i for i in all_issues if i.severity == STATUS_CRIT]
        warns = [i for i in all_issues if i.severity == STATUS_WARN]
        items_html = ""
        for issue in crits + warns:
            icon = "\U0001F534" if issue.severity == STATUS_CRIT else "\U0001F7E1"
            css = "crit" if issue.severity == STATUS_CRIT else "warn"
            items_html += (
                f'<li class="sum-item {css}">'
                f'<span class="sum-icon">{icon}</span>'
                f'<span class="sum-text">'
                f'<strong>[{html.escape(issue.category)}] {html.escape(issue.what)}</strong>'
                f'<span class="sum-why">{html.escape(issue.why)}</span>'
                f'<span class="sum-action">&#8594; {html.escape(issue.action)}</span>'
                f'</span>'
                f'</li>'
            )
        parts.append(
            '<div>'
            '<div class="sum-section-title">Problemen</div>'
            f'<ul class="sum-list">{items_html}</ul>'
            '</div>'
        )

    # Acties (deduplicated, max 5)
    if all_issues:
        seen: set = set()
        actions: List[tuple] = []
        for issue in [i for i in all_issues if i.severity == STATUS_CRIT] + \
                     [i for i in all_issues if i.severity == STATUS_WARN]:
            if issue.action not in seen:
                seen.add(issue.action)
                actions.append((issue.action, issue.category))
            if len(actions) == 5:
                break
        actions_html = "".join(
            f'<li>{html.escape(a)} <span class="sum-action-cat">({html.escape(cat)})</span></li>'
            for a, cat in actions
        )
        parts.append(
            '<div>'
            '<div class="sum-section-title">Acties</div>'
            f'<ul class="sum-actions-list">{actions_html}</ul>'
            '</div>'
        )

    body_html = "".join(parts)

    return (
        '<div class="sumblock">'
        '<div class="sumblock-head">&#128203; SAMENVATTING &amp; PROBLEMEN</div>'
        f'<div class="sumblock-body">{body_html}</div>'
        '</div>'
    )


def render_value(value: str, status: str) -> str:
    css_class = status if status in (STATUS_GOOD, STATUS_WARN, STATUS_CRIT, STATUS_INFO) else STATUS_INFO
    return f'<span class="v {css_class}">{html.escape(value)}</span>'


def render_card(section: Section) -> str:
    badge_class = section.status
    badge_label = STATUS_LABEL.get(section.status, STATUS_LABEL[STATUS_GOOD])
    body_parts: List[str] = []

    # Rijen
    for label, value, row_status in section.rows:
        body_parts.append(
            f'<div class="row"><span class="k">{html.escape(label)}</span>'
            f"{render_value(value, row_status)}</div>"
        )

    # Banners
    for kind, msg in section.banners:
        css = kind if kind in ("warn", "crit", "info") else "info"
        body_parts.append(f'<div class="banner {css}">{html.escape(msg)}</div>')

    # Tabellen
    for tbl in section.tables:
        headers_html = "".join(f"<th>{html.escape(h)}</th>" for h in tbl["headers"])
        rows_html = ""
        for row in tbl["rows"]:
            cells = "".join(f"<td>{html.escape(str(c))}</td>" for c in row)
            rows_html += f"<tr>{cells}</tr>"
        body_parts.append(
            f'<div class="tbl-title">{html.escape(tbl["title"])}</div>'
            f"<table><thead><tr>{headers_html}</tr></thead><tbody>{rows_html}</tbody></table>"
        )

    body_html = "".join(body_parts) or '<div class="row"><span class="k">Geen gegevens</span></div>'

    return (
        '<div class="card">'
        '<div class="card-head">'
        f'<span class="icon">{section.icon}</span>'
        f'<span class="title">{html.escape(section.name.upper())}</span>'
        f'<span class="badge {badge_class}">{badge_label}</span>'
        "</div>"
        f'<div class="card-body">{body_html}</div>'
        "</div>"
    )


def build_html_report(sections: List[Section]) -> str:
    # Overall status bepalen
    overall = STATUS_GOOD
    for s in sections:
        overall = worst(overall, s.status)

    summary_map = {
        STATUS_GOOD: ("good", "GEZOND"),
        STATUS_WARN: ("warn", "LET OP"),
        STATUS_CRIT: ("crit", "ACTIE VEREIST"),
        STATUS_INFO: ("good", "GEZOND"),
    }
    summary_class, summary_label = summary_map[overall]

    cards_html = "".join(render_card(s) for s in sections)
    summary_block = build_summary_html(sections)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = html.escape(socket.gethostname() or "onbekend")

    html_out = (HTML_TEMPLATE
                .replace("__H20_RED__", H20_RED)
                .replace("__HOSTNAME__", hostname)
                .replace("__TIMESTAMP__", ts)
                .replace("__SUMMARY_CLASS__", summary_class)
                .replace("__SUMMARY_LABEL__", summary_label)
                .replace("__SECTION_COUNT__", str(len(sections)))
                .replace("__SUMMARY_BLOCK__", summary_block)
                .replace("__CARDS__", cards_html)
                .replace("__VERSION__", APP_VERSION))
    return html_out


def write_and_open_report(html_content: str) -> Path:
    """Schrijf het rapport naar een tijdelijk bestand en open het in de browser."""
    try:
        # Gebruik een temp-bestand zodat read-only USB-sticks geen probleem vormen
        tmp_dir = Path(tempfile.gettempdir())
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = tmp_dir / f"h20_diagnostic_report_{ts}.html"
        out_path.write_text(html_content, encoding="utf-8")

        # Probeer een kopie naast de .exe te maken (zodat de gebruiker het terugvindt)
        try:
            mirror = BASE_DIR / f"h20_diagnostic_report_{ts}.html"
            shutil.copy2(out_path, mirror)
        except Exception as exc:  # noqa: BLE001
            log_exception("Rapport-kopie naast .exe", exc)

        webbrowser.open(out_path.as_uri())
        return out_path
    except Exception as exc:  # noqa: BLE001
        log_exception("Rapport schrijven/openen", exc)
        raise


# ============================================================================
# Main
# ============================================================================
def main() -> int:
    setup_logging()

    print_logo()
    print_av_warning()

    if not is_admin():
        print("Let op: de tool draait zonder beheerdersrechten.")
        print("Sommige checks (temperaturen, eventlog) geven dan beperkte data.\n")

    # Lijst van (naam, functie) - volgorde bepaalt volgorde in rapport
    checks = [
        ("Systeem",        check_system),
        ("CPU",            check_cpu),
        ("RAM",            check_ram),
        ("Opslag",         check_storage),
        ("GPU",            check_gpu),
        ("Netwerk",        check_network),
        ("Eventlog",       check_eventlog),
    ]

    sections: List[Section] = []
    bar = tqdm(total=len(checks), desc="Diagnose", ncols=70, unit="check")
    try:
        for name, func in checks:
            try:
                sec = func()
            except Exception as exc:  # noqa: BLE001
                log_exception(f"Check '{name}'", exc)
                sec = Section(name, "\u26A0")
                sec.add_banner("crit", f"Onverwachte fout: {exc}")
            sections.append(sec)
            try:
                bar.update(1)
            except Exception:  # noqa: BLE001
                pass
    finally:
        try:
            bar.close()
        except Exception:  # noqa: BLE001
            pass

    print()
    try:
        html_content = build_html_report(sections)
        report_path = write_and_open_report(html_content)
        print(f"Rapport geopend in browser: {report_path}")
        logging.info("Rapport gegenereerd op %s", report_path)
    except Exception as exc:  # noqa: BLE001
        log_exception("Rapport-generatie", exc)
        print(f"[!] Fout bij genereren rapport: {exc}")
        print(f"    Zie log: {LOG_FILE}")
        return 1

    # Laat het terminal-venster even openstaan zodat de gebruiker het resultaat ziet
    try:
        input("\nDruk op Enter om af te sluiten...")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAfgebroken door gebruiker.")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Onverwachte hoofdfout")
        print(f"[!] Onverwachte fout: {exc}")
        print(f"    Zie log: {LOG_FILE}")
        try:
            input("\nDruk op Enter om af te sluiten...")
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
