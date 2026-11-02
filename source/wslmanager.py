# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ipaddress
import re
import socket
import subprocess
import time
import winreg

import psutil

import wslconfig
import wslnet
import wslsettings
import wsltasks

from wslshell import CREATE_NO_WINDOW
from wslshell import is_admin
from wslshell import log
from wslshell import powershell
from wslshell import read_last_log
from wslshell import run


LXSS = r'Software\Microsoft\Windows\CurrentVersion\Lxss'
VM_PROCESS = 'vmmemwsl'
VETHERNETS = ('vEthernet (WSL)', 'vEthernet (WSLCore)', 'vEthernet (WSL (Hyper-V firewall))')

# addresses other machines cannot reach; dnsTunneling answers on 10.255.255.254
LOCAL_ADDRESS = re.compile(r'^(127\.|\[::1\]|::1$|10\.255\.255\.254$)')
INET = re.compile(r'inet (\d+(?:\.\d+){3})')
HOST_NAME = re.compile(r'^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$')

ROUTED_ADDRESS = ('(Get-NetIPConfiguration | Where-Object IPv4DefaultGateway)'
                  '.IPv4Address.IPAddress')

STOP_TIMEOUT = 30
SETTLE_RETRIES = 6
SETTLE_DELAY = 5


def get_distributions():
    '''[(name, version, default)] from the registry, so asking never starts WSL.'''
    found = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, LXSS)
    except OSError:
        return found
    try:
        default = winreg.QueryValueEx(root, 'DefaultDistribution')[0]
    except OSError:
        default = ''
    index = 0
    while True:
        try:
            guid = winreg.EnumKey(root, index)
        except OSError:
            break
        index += 1
        try:
            key = winreg.OpenKey(root, guid)
            name = winreg.QueryValueEx(key, 'DistributionName')[0]
            version = winreg.QueryValueEx(key, 'Version')[0]
        except OSError:
            continue
        found.append((name, version, guid == default))
    return found


def resolve_distribution(settings):
    if settings['distribution']:
        return settings['distribution']
    return next((name for name, version, default in get_distributions() if default), '')


def is_vm_running():
    for process in psutil.process_iter(['name']):
        if (process.info['name'] or '').lower().startswith(VM_PROCESS):
            return True
    return False


def get_running():
    # wsl.exe would start the VM to answer, so only ask while it runs
    if not is_vm_running():
        return []
    code, output = run(['wsl.exe', '--list', '--running', '--quiet'], 15)
    return [v.strip() for v in output.split('\n') if v.strip()] if code == 0 else []


def get_mode(config=None):
    return 'mirrored' if wslconfig.get_networking_mode(config) == 'mirrored' else 'nat'


def get_external_address(settings):
    if settings['external_address']:
        return settings['external_address']
    code, output = powershell(ROUTED_ADDRESS, 30)
    lines = [v.strip() for v in output.split('\n') if v.strip()]
    if lines and re.match(r'^\d+(?:\.\d+){3}$', lines[0]):
        return lines[0]
    return socket.gethostbyname(socket.gethostname())


def get_published(settings):
    return sorted(set(settings['ports'] + settings['firewall_ports']))


def is_service_needed(settings):
    return bool(get_published(settings) or settings['startup_commands'] or settings['keepalive'])


def needs_admin(action, settings=None):
    if action in ('apply', 'boot', 'resume', 'uninstall'):
        return True
    if action == 'restart':
        settings = settings or wslsettings.load()[0]
        # firewall rules survive a restart, NAT forwarding has to follow the new address
        return get_mode() == 'nat' and bool(settings['ports'])
    return False


def wsl(distribution, arguments, timeout=30, user='root'):
    return run(['wsl.exe', '-d', distribution, '-u', user, '--exec'] + list(arguments), timeout)


def check(settings=None, problems=None):
    '''Problems with the settings against this machine; reads only.'''
    if settings is None:
        settings, problems = wslsettings.load()
    problems = list(problems or [])
    names = [name for name, version, default in get_distributions()]
    distribution = resolve_distribution(settings)
    if not names:
        problems.append('WSL has no distribution installed')
    elif distribution not in names:
        problems.append(f'Distribution {distribution} is not installed')

    for key in ('ports', 'firewall_ports', 'resume_probe_ports'):
        wrong = [v for v in settings[key] if not isinstance(v, int) or not 0 < v < 65536]
        if wrong:
            problems.append(f'{key} has ports out of range: {wrong}')

    if settings['resume_action'] not in wslsettings.RESUME_ACTIONS:
        problems.append(f'resume_action must be one of {", ".join(wslsettings.RESUME_ACTIONS)}')

    if get_mode() == 'nat':
        for key in ('binding_address', 'vethernet_address', 'external_address'):
            value = settings[key]
            if value:
                try:
                    ipaddress.IPv4Address(value)
                except ValueError:
                    problems.append(f'{key} {value} is not an IPv4 address')
        external = get_external_address(settings)
        if settings['binding_address'].split('.')[:3] == external.split('.')[:3]:
            problems.append(f'binding_address {settings["binding_address"]} is inside the LAN '
                            f'subnet of {external}')
    return problems


def get_default_route(distribution):
    code, output = wsl(distribution, ['ip', '-o', '-4', 'route', 'show', 'default'])
    return output.split('\n')[0].split() if code == 0 else []


def get_route_field(distribution, keyword):
    parts = get_default_route(distribution)
    index = parts.index(keyword) + 1 if keyword in parts else len(parts)
    return parts[index] if index < len(parts) else ''


def get_wsl_address(distribution):
    code, output = wsl(distribution, ['ip', '-4', '-o', 'addr', 'show', 'eth0'])
    found = INET.findall(output)
    return found[0] if found else ''


def setup_nat(settings, distribution):
    '''Gives WSL a fixed address beside the one NAT hands out, and the host one on its side.'''
    binding = settings['binding_address']
    if binding and binding != get_route_field(distribution, 'via'):
        broadcast = '.'.join(binding.split('.')[:3] + ['255'])
        wsl(distribution, ['ip', 'addr', 'del', f'{binding}/24', 'dev', 'eth0', 'label',
                           'eth0:1'])
        wsl(distribution, ['ip', 'addr', 'add', f'{binding}/24', 'broadcast', broadcast,
                           'dev', 'eth0', 'label', 'eth0:1'])
    for name in VETHERNETS:
        run(['netsh', 'interface', 'ip', 'add', 'address', name,
             settings['vethernet_address'], '255.255.255.0'])


def apply_network(settings, distribution, preview=False):
    '''Opens and forwards the ports; returns what it does. Needs elevation unless previewing.'''
    mode = get_mode()
    published = get_published(settings)
    state = wslsettings.load_state()
    previous = [tuple(v) for v in state.get('portproxy', [])]
    steps = []
    where = 'the Windows and Hyper-V firewalls' if mode == 'mirrored' else 'the Windows firewall'
    if published:
        steps.append(f'Open {",".join(map(str, published))} on {where}')
    else:
        steps.append('Remove our firewall rules')
    if previous:
        steps.append(f'Remove {len(previous)} forwarding entries added before')
    external = ''
    if mode == 'nat' and settings['ports']:
        external = get_external_address(settings)
        steps.append(f'Forward {",".join(map(str, sorted(set(settings["ports"]))))} from '
                     f'{external} to {distribution}')
    if preview:
        return steps

    wslnet.set_rules(published, mode == 'mirrored')
    wslnet.delete_portproxy(previous)
    added = []
    if external:
        setup_nat(settings, distribution)
        address = get_wsl_address(distribution)
        if address:
            added = wslnet.add_portproxy(external, address, settings['ports'])
        else:
            steps.append(f'No address found for {distribution}, nothing forwarded')
    state['portproxy'] = added
    wslsettings.save_state(state)
    for step in steps:
        log(f'apply: {step}')
    return steps


def apply(settings=None, preview=False):
    '''Publishes the ports and registers the tasks the settings ask for.'''
    settings = settings or wslsettings.load()[0]
    distribution = resolve_distribution(settings)
    steps = apply_network(settings, distribution, preview)
    if is_service_needed(settings):
        names = [wsltasks.BOOT, wsltasks.RESUME]
        if settings['keepalive']:
            names.append(wsltasks.KEEPALIVE)
        steps.append(f'Register the tasks {", ".join(names)}')
        if not preview:
            wsltasks.install(distribution, settings['keepalive'])
    else:
        steps.append('Remove the tasks, nothing needs them')
        if not preview:
            wsltasks.uninstall()
    return steps


def uninstall(preview=False):
    steps = ['Remove our firewall rules', 'Remove the forwarding entries added before',
             f'Remove the tasks {", ".join(wsltasks.NAMES)}']
    if preview:
        return steps
    wslnet.remove_rules()
    state = wslsettings.load_state()
    wslnet.delete_portproxy([tuple(v) for v in state.get('portproxy', [])])
    state['portproxy'] = []
    wslsettings.save_state(state)
    wsltasks.uninstall()
    log('uninstall')
    return steps


def start_distribution(distribution):
    return run(['wsl.exe', '-d', distribution, '--exec', 'true'], 60)[0] == 0


def run_startup_commands(settings, distribution):
    commands = settings['startup_commands']
    if not commands:
        return
    code, output = run(['wsl.exe', '-d', distribution, '--exec', 'bash', '-c',
                        ' && '.join(commands)], 300)
    log(f'startup commands exited with {code}')


def stop_all():
    run(['wsl.exe', '--shutdown'], 60)
    deadline = time.time() + STOP_TIMEOUT
    while get_running() and time.time() < deadline:
        time.sleep(0.5)


def start_keepalive(settings, distribution):
    if not settings['keepalive']:
        return 'off'
    if is_admin() and wsltasks.get_states()[wsltasks.KEEPALIVE] != 'Missing':
        if wsltasks.start(wsltasks.KEEPALIVE):
            return 'task'
    # this logon session holds the distribution until the task takes over on the next boot
    subprocess.Popen(
        ['conhost.exe', '--headless', 'wsl.exe', '-d', distribution, '-u', 'root', '--',
         'sleep', 'infinity'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS |
        subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
    return 'session'


def boot():
    settings = wslsettings.load()[0]
    distribution = resolve_distribution(settings)
    log(f'boot {distribution}')
    start_distribution(distribution)
    apply_network(settings, distribution)
    run_startup_commands(settings, distribution)


def restart():
    '''Shuts every distribution down and brings ours back the way boot does.'''
    settings = wslsettings.load()[0]
    distribution = resolve_distribution(settings)
    log(f'restart {distribution}')
    stop_all()
    holder = start_keepalive(settings, distribution)
    start_distribution(distribution)
    if get_mode() == 'nat' and settings['ports']:
        apply_network(settings, distribution)
    run_startup_commands(settings, distribution)
    log(f'restarted, held by {holder}')


def probe(settings, distribution):
    alive = wsl(distribution, ['true'])[0] == 0
    outbound = inbound = False
    if alive:
        outbound = bool(get_route_field(distribution, 'via'))
        if outbound and settings['resume_probe_host']:
            outbound = wsl(distribution, ['getent', 'hosts',
                                          settings['resume_probe_host']], 15)[0] == 0
        inbound = True
        if settings['resume_probe_ports']:
            external = get_external_address(settings)
            for port in settings['resume_probe_ports']:
                try:
                    socket.create_connection((external, port), timeout=5).close()
                except OSError:
                    inbound = False
                    break
    return {'distribution': alive, 'outbound': outbound, 'inbound': inbound}


def heal(settings, distribution):
    '''Repairs only the layer that failed; False leaves the restart to the caller.'''
    state = probe(settings, distribution)
    log(f'probe {state}')
    if all(state.values()):
        return True
    if not state['distribution']:
        return False
    if not state['outbound']:
        device = get_route_field(distribution, 'dev') or 'eth0'
        log(f'reset interface {device}')
        wsl(distribution, ['ip', 'link', 'set', device, 'down'])
        time.sleep(1)
        wsl(distribution, ['ip', 'link', 'set', device, 'up'])
    if not state['inbound']:
        log('reset inbound')
        apply_network(settings, distribution)
    for _ in range(SETTLE_RETRIES):
        time.sleep(SETTLE_DELAY)
        state = probe(settings, distribution)
        log(f'probe {state}')
        if all(state.values()):
            return True
    return False


def resume():
    settings = wslsettings.load()[0]
    distribution = resolve_distribution(settings)
    action = settings['resume_action']
    log(f'resume {action}')
    if action == 'none':
        return
    if action == 'heal' and heal(settings, distribution):
        return
    restart()


def parse_listening(text):
    ports = set()
    for line in text.split('\n'):
        parts = line.split()
        if len(parts) < 4:
            continue
        address, _, port = parts[3].rpartition(':')
        if port.isdigit() and not LOCAL_ADDRESS.match(address):
            ports.add(int(port))
    return sorted(ports)


def get_listening(distribution):
    code, output = wsl(distribution, ['sh', '-c', 'ss -Hltn; echo --; ss -Hlun'], 15)
    if code != 0:
        return None
    tcp, _, udp = output.partition('--')
    return {'tcp': parse_listening(tcp), 'udp': parse_listening(udp)}


def read_wsl_conf(distribution):
    '''{section: {key: value}} of /etc/wsl.conf, {} when it is missing; asks a running WSL.'''
    code, output = wsl(distribution, ['sh', '-c', 'cat /etc/wsl.conf 2>/dev/null; true'])
    return wslconfig.parse(output.split('\n')) if code == 0 else None


def check_wsl_conf(distribution, changes):
    '''Why a change would leave the distribution unusable, or None; a missing default user
    keeps WSL from opening a shell at all.'''
    for (section, key), value in changes.items():
        if value is None:
            continue
        if (section, key) == ('network', 'hostname') and not HOST_NAME.match(value):
            return f'{value} is not a host name: letters, digits and inner hyphens, up to 63'
        if (section, key) == ('user', 'default') and \
                wsl(distribution, ['getent', 'passwd', value])[0] != 0:
            return f'{distribution} has no user {value}'
    return None


def write_wsl_conf(distribution, changes):
    '''Edits /etc/wsl.conf as root, keeping its comments; the old file stays as wsl.conf.bak.
    Returns None when written, else why not.'''
    problem = check_wsl_conf(distribution, changes)
    if problem:
        return problem
    code, output = wsl(distribution, ['sh', '-c', 'cat /etc/wsl.conf 2>/dev/null; true'])
    if code != 0:
        return f'{distribution} did not answer'
    text = wslconfig.change_text(output, changes)
    try:
        result = subprocess.run(
            ['wsl.exe', '-d', distribution, '-u', 'root', '--exec', 'sh', '-c',
             'cp -p /etc/wsl.conf /etc/wsl.conf.bak 2>/dev/null; cat > /etc/wsl.conf'],
            input=text.encode('utf-8'), capture_output=True, timeout=30,
            creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)
    if result.returncode != 0:
        return f'{distribution} refused the write'
    log(f'/etc/wsl.conf in {distribution} {changes}')
    return None


def get_status(settings=None, problems=None):
    '''What is in effect right now, with the problems found; reads only and never starts WSL.'''
    if settings is None:
        settings, problems = wslsettings.load()
    problems = check(settings, problems)
    config = wslconfig.read()
    mode = get_mode(config)
    distribution = resolve_distribution(settings)
    running = get_running()
    tasks = wsltasks.get_states()
    opened = wslnet.get_opened()
    published = get_published(settings)

    status = {
        'distribution': distribution,
        'distributions': [{'name': n, 'version': v, 'default': d}
                          for n, v, d in get_distributions()],
        'vm_running': bool(running) or is_vm_running(),
        'running': distribution in running,
        'running_distributions': running,
        'mode': mode,
        'wslconfig': config,
        'tasks': tasks,
        'keepalive': settings['keepalive'],
        'opened': opened,
        'published': published,
        'last_log': read_last_log(),
    }

    if tasks[wsltasks.KEEPALIVE] == 'Running':
        status['held_by'] = 'task'
    # our own logon hold or another tool's, a sleeping wsl.exe cannot tell which
    elif status['running'] and settings['keepalive'] and is_held_by_process():
        status['held_by'] = 'process'
    else:
        status['held_by'] = None

    if mode == 'nat':
        ours = {tuple(v) for v in wslsettings.load_state().get('portproxy', [])}
        status['forwarded'] = [list(v) for v in wslnet.get_portproxy() if v[:2] in ours]

    listening = get_listening(distribution) if status['running'] else None
    status['listening'] = listening
    status['wsl_conf'] = read_wsl_conf(distribution) if status['running'] else None
    if listening is not None:
        heard = set(listening['tcp']) | set(listening['udp'])
        status['idle_ports'] = [v for v in published if v not in heard]

    needed = is_service_needed(settings)
    if needed and 'Missing' in (tasks[wsltasks.BOOT], tasks[wsltasks.RESUME]):
        problems.append('The tasks are not registered, press Apply')
    if settings['keepalive'] and tasks[wsltasks.KEEPALIVE] == 'Missing':
        problems.append('The keepalive task is not registered, press Apply')
    expected_hyperv = published if mode == 'mirrored' else []
    if opened['windows'] != published or opened['hyperv'] != expected_hyperv:
        problems.append('Opened ports differ from the settings, press Apply')
    if settings['keepalive'] and status['running'] and status['held_by'] is None:
        problems.append('Keepalive is on but nothing holds the distribution')
    status['problems'] = problems
    return status


def is_held_by_process():
    for process in psutil.process_iter(['name', 'cmdline']):
        try:
            line = ' '.join(process.info['cmdline'] or [])
        except (psutil.Error, TypeError):
            continue
        if (process.info['name'] or '').lower() == 'wsl.exe' and 'sleep infinity' in line:
            return True
    return False
