#!/usr/bin/env python3
"""
RealmScape Hotspot Daemon
=========================
Runs as a separate elevated process to create a private WiFi hotspot that
allows exactly ONE client — the DM's browser.

A fresh random password is generated every time the daemon starts.
The GUI app reads a status file written by this daemon and displays the
current SSID and password on-screen so the DM can connect their device.

If the machine already has network connectivity the daemon aborts
immediately — no hotspot is needed and the GUI will show nothing.

Usage
-----
Windows (run as Administrator):
    python hotspot_daemon.py [options]

Linux (requires hostapd, dnsmasq, iw):
    sudo python hotspot_daemon.py [options]

Options
-------
  --ssid NAME   WiFi network name        (default: RealmScape-DM)
  --port PORT   EcounterManager app port (default: 5000)
  --channel N   WiFi channel 1-11        (default: 6, Linux only)
"""

import argparse
import json
import os
import platform
import re
import secrets
import signal
import string
import subprocess
import sys
import time

SYSTEM = platform.system()           # 'Windows' | 'Linux'
WINDOWS_HOSTED_IP = '192.168.137.1'  # fixed IP Windows assigns to the virtual adapter
LINUX_AP_IP       = '192.168.200.1'
LINUX_DHCP_START  = '192.168.200.10'
LINUX_DHCP_END    = '192.168.200.10' # same start/end → only one lease possible

_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
# Status file read by the GUI app to display connection info
STATUS_FILE  = os.path.join(_SCRIPT_DIR, 'campaigns', '.hotspot_status.json')
# How often (seconds) the daemon refreshes the heartbeat timestamp
_HEARTBEAT_INTERVAL = 5


# ── status file ───────────────────────────────────────────────────────────────

def _write_status(data: dict):
    """Atomically write the status file with a fresh heartbeat timestamp."""
    data['heartbeat'] = time.time()
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    tmp = STATUS_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, STATUS_FILE)


def _clear_status():
    try:
        os.remove(STATUS_FILE)
    except FileNotFoundError:
        pass


# ── helpers ───────────────────────────────────────────────────────────────────

def _gen_password(n: int = 12) -> str:
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(n))


def _is_already_connected() -> bool:
    """Return True if the machine already has usable network connectivity."""
    if SYSTEM == 'Windows':
        r = _run('ipconfig', capture=True)
        for line in r.stdout.splitlines():
            if 'IPv4 Address' in line:
                ip = line.split(':')[-1].strip().rstrip('(Preferred)').strip()
                # Skip loopback and APIPA (169.254.x.x = no real network)
                if not ip.startswith('127.') and not ip.startswith('169.254.'):
                    return True
        return False
    else:
        # Reliable: a default route exists only when genuinely connected
        r = _run('ip', 'route', 'show', 'default', capture=True)
        return bool(r.stdout.strip())


def _check_privileges():
    if SYSTEM == 'Windows':
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("ERROR: This script must be run as Administrator on Windows.")
            print("       Right-click the terminal and choose 'Run as administrator'.")
            sys.exit(1)
    elif SYSTEM == 'Linux':
        if os.geteuid() != 0:
            print("ERROR: This script must be run as root on Linux.")
            print("       Use: sudo python hotspot_daemon.py")
            sys.exit(1)
    else:
        print(f"ERROR: Unsupported platform '{SYSTEM}'. Supported: Windows, Linux.")
        sys.exit(1)


def _run(*cmd, check=False, capture=False):
    return subprocess.run(
        list(cmd),
        check=check,
        capture_output=capture,
        text=True,
    )


# ── Windows implementation ────────────────────────────────────────────────────

class _WindowsHotspot:
    """
    Uses netsh wlan hostednetwork.
    Single-client policy: the first MAC that connects is whitelisted; any
    subsequent MAC triggers a stop/start cycle which evicts everyone — the DM's
    device reconnects automatically (it has the saved credentials), the intruder
    does not get back in because the DM reconnects first.
    """

    def __init__(self, ssid: str, password: str, app_port: int):
        self.ssid         = ssid
        self.password     = password
        self.app_port     = app_port
        self._allowed_mac: str | None = None
        self._running     = False
        self._last_hb     = 0.0

    # ── public ────────────────────────────────────────────────────────────────

    def check_capable(self):
        r = _run('netsh', 'wlan', 'show', 'drivers', capture=True)
        if 'Hosted network supported  : Yes' not in r.stdout:
            print("ERROR: Your WiFi adapter does not support hosted-network mode.")
            print("       Try a different adapter or use Linux for guaranteed support.")
            sys.exit(1)

    def start(self):
        self.check_capable()
        _run('netsh', 'wlan', 'set', 'hostednetwork',
             'mode=allow', f'ssid={self.ssid}', f'key={self.password}', check=True)
        _run('netsh', 'wlan', 'start', 'hostednetwork', check=True)
        self._running = True
        _write_status({
            'status':   'active',
            'ssid':     self.ssid,
            'password': self.password,
            'ip':       WINDOWS_HOSTED_IP,
            'port':     self.app_port,
        })
        self._print_info()
        self._monitor_loop()

    def stop(self):
        self._running = False
        _run('netsh', 'wlan', 'stop', 'hostednetwork')
        _run('netsh', 'wlan', 'set', 'hostednetwork', 'mode=disallow')
        _clear_status()
        print("Hotspot stopped.")

    # ── internal ──────────────────────────────────────────────────────────────

    def _connected_macs(self) -> list[str]:
        r = _run('netsh', 'wlan', 'show', 'hostednetwork', capture=True)
        return re.findall(r'[0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5}', r.stdout)

    def _monitor_loop(self):
        print("Monitoring connections. Press Ctrl+C to stop.\n")
        while self._running:
            # Refresh heartbeat so the GUI knows we're still alive
            if time.time() - self._last_hb >= _HEARTBEAT_INTERVAL:
                _write_status({
                    'status':   'active',
                    'ssid':     self.ssid,
                    'password': self.password,
                    'ip':       WINDOWS_HOSTED_IP,
                    'port':     self.app_port,
                })
                self._last_hb = time.time()

            macs = self._connected_macs()
            if macs:
                if self._allowed_mac is None:
                    self._allowed_mac = macs[0].upper()
                    print(f"[+] DM connected — MAC {self._allowed_mac}")
                intruders = [m.upper() for m in macs
                             if m.upper() != self._allowed_mac]
                if intruders:
                    print(f"[!] Intruder detected ({', '.join(intruders)}) — restarting hotspot …")
                    _run('netsh', 'wlan', 'stop', 'hostednetwork')
                    time.sleep(1)
                    _run('netsh', 'wlan', 'start', 'hostednetwork')
            time.sleep(3)

    def _print_info(self):
        print()
        print("=" * 48)
        print("  RealmScape Private Hotspot — ACTIVE")
        print("=" * 48)
        print(f"  SSID      : {self.ssid}")
        print(f"  Password  : {self.password}")
        print(f"  DM URL    : http://{WINDOWS_HOSTED_IP}:{self.app_port}")
        print("=" * 48)
        print("  Only the first device to connect will be")
        print("  allowed. All others will be disconnected.")
        print("=" * 48)
        print()


# ── Linux implementation ───────────────────────────────────────────────────────

class _LinuxHotspot:
    """
    Uses hostapd (max_num_sta=1) + dnsmasq (single DHCP lease).
    The 802.11 association is refused at the kernel level for any device
    after the first — this is a hard, unbypassable block.
    """

    HOSTAPD_CONF  = '/tmp/realmscape_hostapd.conf'
    DNSMASQ_CONF  = '/tmp/realmscape_dnsmasq.conf'
    DNSMASQ_LEASE = '/tmp/realmscape_dnsmasq.leases'

    def __init__(self, ssid: str, password: str, app_port: int, channel: int = 6):
        self.ssid      = ssid
        self.password  = password
        self.app_port  = app_port
        self.channel   = channel
        self._iface    = None
        self._procs: list[subprocess.Popen] = []
        self._running  = False
        self._last_hb  = 0.0

    # ── public ────────────────────────────────────────────────────────────────

    def start(self):
        self._check_deps()
        self._iface = self._find_wifi_interface()
        if not self._iface:
            print("ERROR: No wireless interface found.")
            print("       Is a WiFi adapter present? Check 'iw dev'.")
            sys.exit(1)

        self._write_configs()
        self._configure_interface()
        self._start_hostapd()
        self._start_dnsmasq()
        self._running = True
        _write_status({
            'status':   'active',
            'ssid':     self.ssid,
            'password': self.password,
            'ip':       LINUX_AP_IP,
            'port':     self.app_port,
        })
        self._print_info()
        self._wait_loop()

    def stop(self):
        self._running = False
        for p in self._procs:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self._procs.clear()
        for path in (self.HOSTAPD_CONF, self.DNSMASQ_CONF, self.DNSMASQ_LEASE):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        if self._iface:
            _run('ip', 'link', 'set', self._iface, 'down')
        _clear_status()
        print("Hotspot stopped.")

    # ── internal ──────────────────────────────────────────────────────────────

    def _check_deps(self):
        missing = []
        for tool in ('hostapd', 'dnsmasq', 'iw', 'ip'):
            r = _run('which', tool, capture=True)
            if r.returncode != 0:
                missing.append(tool)
        if missing:
            pkgs = ' '.join(missing)
            print(f"ERROR: Missing required tools: {pkgs}")
            print(f"       Install with: sudo apt install {pkgs}")
            sys.exit(1)

    def _find_wifi_interface(self) -> str | None:
        r = _run('iw', 'dev', capture=True)
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith('Interface '):
                return line.split()[-1]
        return None

    def _write_configs(self):
        hostapd = f"""\
interface={self._iface}
driver=nl80211
ssid={self.ssid}
hw_mode=g
channel={self.channel}
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase={self.password}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
max_num_sta=1
"""
        with open(self.HOSTAPD_CONF, 'w') as f:
            f.write(hostapd)

        dnsmasq = f"""\
interface={self._iface}
bind-interfaces
dhcp-range={LINUX_DHCP_START},{LINUX_DHCP_END},255.255.255.0,24h
dhcp-lease-max=1
dhcp-leasefile={self.DNSMASQ_LEASE}
no-resolv
no-hosts
"""
        with open(self.DNSMASQ_CONF, 'w') as f:
            f.write(dnsmasq)

    def _configure_interface(self):
        _run('ip', 'addr', 'flush', 'dev', self._iface)
        _run('ip', 'addr', 'add', f'{LINUX_AP_IP}/24', 'dev', self._iface)
        _run('ip', 'link', 'set', self._iface, 'up')

    def _start_hostapd(self):
        p = subprocess.Popen(
            ['hostapd', self.HOSTAPD_CONF],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._procs.append(p)
        time.sleep(2)
        if p.poll() is not None:
            print("ERROR: hostapd failed to start.")
            print("       Is another process using the WiFi interface?")
            print(f"       Try: sudo airmon-ng stop {self._iface}")
            sys.exit(1)

    def _start_dnsmasq(self):
        _run('pkill', '-f', f'dnsmasq.*{self.DNSMASQ_CONF}')
        time.sleep(0.5)
        p = subprocess.Popen(
            ['dnsmasq', f'--conf-file={self.DNSMASQ_CONF}', '--no-daemon'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._procs.append(p)
        time.sleep(0.5)
        if p.poll() is not None:
            print("ERROR: dnsmasq failed to start.")
            print("       Is port 53 in use? Try: sudo systemctl stop systemd-resolved")
            sys.exit(1)

    def _wait_loop(self):
        print("Hotspot running. Press Ctrl+C to stop.\n")
        while self._running:
            if time.time() - self._last_hb >= _HEARTBEAT_INTERVAL:
                _write_status({
                    'status':   'active',
                    'ssid':     self.ssid,
                    'password': self.password,
                    'ip':       LINUX_AP_IP,
                    'port':     self.app_port,
                })
                self._last_hb = time.time()

            for p in self._procs:
                if p.poll() is not None:
                    print(f"ERROR: Background process exited unexpectedly (pid {p.pid}).")
                    self.stop()
                    sys.exit(1)
            time.sleep(2)

    def _print_info(self):
        print()
        print("=" * 48)
        print("  RealmScape Private Hotspot — ACTIVE")
        print("=" * 48)
        print(f"  SSID      : {self.ssid}")
        print(f"  Password  : {self.password}")
        print(f"  DM URL    : http://{LINUX_AP_IP}:{self.app_port}")
        print("=" * 48)
        print("  max_num_sta=1: only ONE device can associate.")
        print("  Second devices are refused at the 802.11 layer.")
        print("=" * 48)
        print()


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='RealmScape private hotspot daemon (run as admin/root)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--ssid',    default='RealmScape-DM',
                        help='WiFi network name (default: RealmScape-DM)')
    parser.add_argument('--port',    type=int, default=5000,
                        help='EcounterManager app port (default: 5000)')
    parser.add_argument('--channel', type=int, default=6,
                        help='WiFi channel 1-11 (default: 6, Linux only)')
    args = parser.parse_args()

    _check_privileges()

    if _is_already_connected():
        print("Network connectivity detected — hotspot not needed.")
        print("Connect to the existing network and use the normal IP address.")
        _clear_status()   # ensure GUI shows nothing
        sys.exit(0)

    password = _gen_password()

    if SYSTEM == 'Windows':
        hotspot = _WindowsHotspot(args.ssid, password, args.port)
    else:
        hotspot = _LinuxHotspot(args.ssid, password, args.port, args.channel)

    def _shutdown(sig, frame):
        print('\nShutting down …')
        hotspot.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    hotspot.start()


if __name__ == '__main__':
    main()
