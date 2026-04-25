# H20 Diagnostic Tool

A zero-install, single-executable PC hardware diagnostic utility built for the
gaming PCs at **H20 Esports Campus Amsterdam**. Drop the `.exe` on a USB stick,
double-click it on any Windows machine, and get a full HTML health report in
your browser within a minute — no clicks, no reboots, no Python required.

![Screenshot placeholder](docs/screenshot.png)
<!-- Replace the line above with a real screenshot: docs/screenshot.png -->

## What it checks

- **System** — hostname, Windows version, uptime, last boot time
- **CPU** — model, cores/threads, clock speed, temperature, 10-second load sample (average + peak)
- **RAM** — total, current usage (GB + %), slot count, per-module speed
- **Storage** — every drive: model, SSD/HDD, size, free space (colour-coded), SMART status, short read/write benchmark
- **GPU** — model, VRAM, driver version, temperature (when available)
- **Network** — active adapters, IPv4/MAC, 10-ping latency & packet loss to 8.8.8.8, download/upload via `speedtest-cli`
- **Temperatures** — all sensors exposed by `psutil` and WMI ACPI thermal zones
- **Windows Event Log** — last 10 critical errors with timestamp, source and message

Every check degrades gracefully. A sensor that's not available shows
**"Niet beschikbaar"** instead of crashing the scan.

## Requirements

- **Windows 10 or 11, 64-bit**
- For the prebuilt `.exe`: **no installation required**
- To run from source: **Python 3.10+**

## Usage

### 1. Run directly from source

```bash
pip install -r build/requirements.txt
python src/h20_diagnostic.py
```

### 2. Build the portable EXE

From the project root, run:

```bat
build\build.bat
```

This installs dependencies, runs PyInstaller, and drops a single file —
`h20_diagnostic.exe` — directly in the **project root** (no `dist/` folder).
The build script prints:

> Build geslaagd. h20_diagnostic.exe staat in de projectroot.
> Kopieer dat bestand naar je USB-stick.

### 3. Use from a USB stick

1. Copy `h20_diagnostic.exe` from the project root to any USB drive.
2. Plug the stick into the target PC.
3. Double-click `h20_diagnostic.exe`.
4. A small terminal window shows the scan progress; the HTML report opens
   automatically in the default browser when the scan completes.

No install, no admin rights required for the basic checks. Administrator rights
unlock CPU temperatures and the Windows Event Log.

## Antivirus notice

Windows Defender and some third-party antivirus engines may flag the `.exe` as
suspicious. This is a **false positive** caused by PyInstaller bundling a
Python runtime inside the binary — it is a well-known pattern that heuristic
scanners treat as unusual.

The tool contains **no malicious code** and its source is fully visible in this
repository.

### Adding an exception in Windows Defender

1. Open **Windows Security** → **Virus & threat protection**.
2. Under **Virus & threat protection settings**, click **Manage settings**.
3. Scroll to **Exclusions** → **Add or remove exclusions** → **Add an exclusion**.
4. Choose **Folder** and select your USB drive, or choose **File** and select
   `h20_diagnostic.exe` directly.

If your workplace uses a different endpoint protection product (CrowdStrike,
SentinelOne, etc.), ask your IT administrator to whitelist the SHA-256 hash of
your build output.

## Output & logging

- The HTML report is written to the system temp folder and opened in the
  default browser. A copy is also saved next to the `.exe` when possible.
- All errors are appended to `h20_diagnostic_log.txt` next to the `.exe`.
  Inspect this file if a scan seems incomplete — every failed check leaves a
  trace with a stack trace.

## Project layout

```
h20-diagnostic-tool/
├── h20_diagnostic.exe        ← the only top-level file (after build, gitignored)
├── README.md
├── .gitignore
├── build/                    ← build scripts & dependencies
│   ├── build.bat
│   ├── setup_usb.ps1
│   └── requirements.txt
├── src/                      ← Python source
│   └── h20_diagnostic.py
├── assets/                   ← static resources bundled into the .exe
│   └── h20_logo.txt
└── tools/                    ← optional external helpers (see tools/README.md)
    └── README.md
```

The deliverable — `h20_diagnostic.exe` — is the **only file** that lives at the
project root after a build. Everything else is tucked into a clearly named
folder so the executable is impossible to miss.

## License

MIT — see `LICENSE` if present, otherwise the summary below:

> Copyright (c) H20 Esports Campus Amsterdam
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

---

**Made for H20 Esports Campus Amsterdam — Gaming Impacting the World**
