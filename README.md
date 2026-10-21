## Features

* CPU, per-processor load, memory, page file, GPU and VRAM, disk I/O and network, refreshed every 1, 2 or 5 seconds.
* Time graphs over the last 300 samples for CPU, memory, each GPU with its VRAM, physical disk I/O and network.
* What WSL takes of each: its CPU and memory against the `.wslconfig` limits, the memory its VM holds on Windows, and its disk and network traffic.
* MAC, IPv4 and IPv6 of each adapter; the public IP is asked from cloudflare.com only when you press Look up.
* Hardware page: processor, mainboard, each memory module with its part number and speed, and each display adapter with VRAM, PCIe link and driver.
* Disk list with media, bus, size and the health Windows reports, Storage Spaces drives included.
* Disk health: NVMe temperature, life used, spare, power-on time, data written and read, unsafe shutdowns and media errors without administrator rights; SATA SMART attributes after Run as administrator. A hard disk that is asleep is left asleep unless you press Read anyway.
* GPU power against its limit, fan, core and memory clocks, and system uptime.
* Temperature and power panel: CPU package power from the Windows energy counter (Intel RAPL), GPU temperature and power, NVMe temperatures, a power graph, and CPU and mainboard temperatures and fans while LibreHardwareMonitor runs.
* Electricity cost: wall power from the measured CPU and GPUs, NVMe drives from their own power state table (top state while busy, lowest while idle), hard disks by whether they spin, monitors by count and whether Windows has the displays on, and a setting for the rest; the case goes through the power supply efficiency, the monitors do not. Shown the cost per hour, day and month at the current draw, and what today and this month cost while the app ran. Plans for Korea (progressive home tiers with summer steps, or one flat price), the United States and Japan; every price lives in %APPDATA%\PyWinSystem\tariffs.json and an edit applies at once. Stepped prices count the PC on top of the rest of the home.
* BIOS vendor, version and date, firmware type and Secure Boot state on the Hardware page.
* Network adapters on the Hardware page, and a tray icon with Close to tray.
* Only performance counters are sampled, so an idle hard disk is not woken; the disk list is read at start and on request.
* Auto, dark and light themes.

## How to install

* Download or clone a repository, install Python packages in the requirements.pip file, then execute source/main.pyw with pythonw.exe. Python 3.x is required.
* GPU figures need an NVIDIA driver (NVML).
* Execute source/makeshortcut.py to put a shortcut in the Start menu.

## Supported platforms

* Microsoft Windows 11
* Other versions of Windows have not been tested yet.
