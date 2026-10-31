## Features

* CPU, per-processor load, memory, page file, GPU and VRAM, disk I/O and network, refreshed every 1, 2 or 5 seconds.
* Time graphs over the last 300 samples for CPU, memory, each GPU with its VRAM, physical disk I/O and network. A folded panel keeps a small graph in its header, and System folds to the host name.
* Processes page: every process with its CPU and private memory, read in one system call (about 5 ms for 500 processes), sorted by name, CPU or memory. Filter by a name, PID or path in the search box, by kind (Apps own a window, or descend from one under the same name; Windows run from the Windows folder; Background is the rest) and by use (CPU 1% or more, memory 100 MB or 1 GB or more); the kind, use and sort are remembered. A List or Tree view; the tree folds a branch and keeps a filtered match under its ancestors. Each row says what a host process runs: the script of python, node and wsl, the services in svchost from the service manager (no administrator rights needed), the COM name of dllhost, and for conhost the console program that started it. A row opens to show the path, command line, working folder, user, parent, start time, threads, handles, memory and I/O, with Open location, Copy path and Copy command line. Command lines of elevated and system processes need Run as administrator. Processes are read only while the page is open. Linux processes of every running WSL distro show under vmmemWSL (a WSL kind, with user, state and command line), read by one small helper per distro that runs only while the page is open; a stopped WSL is never started for this. With more than one distro running, the WSL kind adds a chip per distro. A tree branch folds under any filter.
* What WSL takes of each: its CPU and memory against the `.wslconfig` limits, the memory its VM holds on Windows, and its disk and network traffic.
* MAC, private IP, gateway and DNS of each adapter; the public IP is asked from cloudflare.com only when you press Look up. A label or description cut short shows in full in a tip. Click an address, a MAC or the host name to copy it.
* Hardware page: processor, mainboard, each memory module with its channel, part number and speed, and each display adapter with VRAM, PCIe link and driver. The memory panel says how many channels the modules fill (dual, quad and so on, read from the slot names), the speed they run at against their rating, and the peak bandwidth that makes (MT/s × 8 bytes × channels).
* Displays on the Hardware page: what each monitor reports in its EDID (vendor, product code, serial, date of manufacture, size), its resolution and refresh rate, and the graphics card and port it is plugged into. Under each graphics card its sockets in driver order, filled where a display is plugged in, with a tip naming the display.
* Disk list with media, bus, size and the health Windows reports, Storage Spaces drives included.
* Disk health: NVMe temperature, life used, spare, power-on time, data written and read, unsafe shutdowns and media errors without administrator rights; SATA SMART attributes after Run as administrator. A hard disk that is asleep is left asleep unless you press Read anyway.
* GPU power against its limit, fan, core and memory clocks, and system uptime.
* Windows edition, version and build (for example Windows 11 Pro · 26H2 · build 26300.9818) beside the host name.
* Temperature and power panel: CPU package power from the Windows energy counter (Intel RAPL), GPU temperature and power, NVMe temperatures, a power graph, and CPU and mainboard temperatures and fans while LibreHardwareMonitor runs.
* Electricity cost: wall power from the measured CPU and GPUs, NVMe drives from their own power state table (top state while busy, lowest while idle), hard disks by whether they spin, monitors by count and whether Windows has the displays on, and a setting for the rest; the case goes through the power supply efficiency, the monitors do not. It graphs the wall power, shows the cost per hour, day and month at the current draw, and what today and this month cost while the app ran. Plans for Korea (progressive home tiers with summer steps, or one flat price), the United States and Japan; every price lives in %APPDATA%\PyWinSystem\tariffs.json and an edit applies at once. Stepped prices count the PC on top of the rest of the home.
* BIOS vendor, version and date, firmware type and Secure Boot state on the Hardware page.
* Network adapters on the Hardware page, a tray icon with Close to tray, and Auto hide menu, which shows the header only while the cursor is over the window.
* Only performance counters are sampled, so an idle hard disk is not woken; the disk list is read at start and on request.
* Auto, dark and light themes.

## Screenshot

![screenshot](/assets/images/screenshot-dce11d1b.webp)

## How to install

* Just download and install the latest release.
* Alternatively, if you like to build your own, download or clone a repository then execute makebuild.py. Python 3.x, Python packages in the requirements.pip file, PyInstaller and Inno Setup are required.
* To run from the source, install Python packages in the requirements.pip file, then execute source/main.pyw with pythonw.exe.
* GPU figures need an NVIDIA driver (NVML).
* Execute source/makeshortcut.py to put a shortcut in the Start menu.

## Supported platforms

* Microsoft Windows 11
