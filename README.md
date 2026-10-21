## Features

* CPU, per-processor load, memory, page file, GPU and VRAM, disk I/O and network, refreshed every 1, 2 or 5 seconds.
* Time graphs over the last 300 samples for CPU, memory, each GPU with its VRAM, physical disk I/O and network.
* What WSL takes of each: its CPU and memory against the `.wslconfig` limits, the memory its VM holds on Windows, and its disk and network traffic.
* Disk list with media, bus, size and the health Windows reports, Storage Spaces drives included.
* Only performance counters are sampled, so an idle hard disk is not woken; the disk list is read at start and on request.
* Auto, dark and light themes.

## How to install

* Download or clone a repository, install Python packages in the requirements.pip file, then execute source/main.pyw with pythonw.exe. Python 3.x is required.
* GPU figures need an NVIDIA driver (NVML).
* Execute source/makeshortcut.py to put a shortcut in the Start menu.

## Supported platforms

* Microsoft Windows 11
* Other versions of Windows have not been tested yet.
