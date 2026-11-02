# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import os
import sys
import tempfile
import time

from wslshell import powershell
from wslshell import quote
from wslshell import run


BOOT = 'PyWinSystem WSL Boot'
RESUME = 'PyWinSystem WSL Resume'
KEEPALIVE = 'PyWinSystem WSL Keepalive'
NAMES = (BOOT, RESUME, KEEPALIVE)

TEMPLATE = '''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>{author}</Author>
    <Description>{description}</Description>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>{user_id}</UserId>
      <LogonType>S4U</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>{time_limit}</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <Hidden>true</Hidden>
  </Settings>
  <Triggers>
{triggers}
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{folder}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'''

BOOT_TRIGGER = '    <BootTrigger />'

RESUME_TRIGGER = '''    <EventTrigger>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;\
*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]\
&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
      <Delay>PT10S</Delay>
    </EventTrigger>'''

WSL_UPDATE_TRIGGER = '''    <EventTrigger>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="Application"&gt;&lt;Select Path="Application"&gt;\
*[System[Provider[@Name='MsiInstaller'] and (EventID=11707)]] and \
*[EventData[Data='Product: Windows Subsystem for Linux -- Installation completed successfully.']]\
&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
      <Delay>PT30S</Delay>
    </EventTrigger>'''

IDENTITY = ('$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent(); '
            '$identity.Name; $identity.User.Value')

STATES = '''
foreach ($n in {names}) {{
    $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    $n + '|' + $(if ($t) {{ $t.State }} else {{ 'Missing' }})
}}
'''


def escape(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def get_launcher():
    '''(command, leading arguments, folder) that start this app without a window.'''
    if getattr(sys, 'frozen', False):
        return sys.executable, '', os.path.dirname(sys.executable)
    source = os.path.dirname(os.path.abspath(__file__))
    pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    command = pythonw if os.path.exists(pythonw) else sys.executable
    return command, f'"{os.path.join(source, "main.pyw")}" ', source


def get_identity():
    code, output = powershell(IDENTITY)
    parts = output.split()
    return parts if len(parts) == 2 else ['', '']


def describe(distribution, keepalive):
    '''{name: (description, time limit, triggers, command, arguments)} of the tasks we keep.'''
    command, prefix, folder = get_launcher()
    tasks = {
        BOOT: ('Starts WSL, publishes its ports and runs the startup commands on boot.', 'PT10M',
               BOOT_TRIGGER, command, f'{prefix}--wsl boot'),
        RESUME: ('Recovers WSL networking when the system resumes.', 'PT10M',
                 RESUME_TRIGGER, command, f'{prefix}--wsl resume'),
    }
    if keepalive:
        tasks[KEEPALIVE] = (
            'Keeps the WSL distribution running without a user logon.', 'PT0S',
            '\n'.join((BOOT_TRIGGER, WSL_UPDATE_TRIGGER)), 'conhost.exe',
            f'--headless wsl.exe -d {distribution} -u root -- sleep infinity')
    return tasks, folder


def install(distribution, keepalive):
    '''Registers the tasks, replacing earlier ones. Needs elevation.'''
    author, user_id = get_identity()
    tasks, folder = describe(distribution, keepalive)
    for name, (description, limit, triggers, command, arguments) in tasks.items():
        xml = TEMPLATE.format(author=escape(author), user_id=escape(user_id),
                              description=escape(description), time_limit=limit,
                              triggers=triggers, command=escape(command),
                              arguments=escape(arguments), folder=escape(folder))
        path = os.path.join(tempfile.gettempdir(), f'{name}.xml')
        with open(path, 'wb') as file:
            file.write(xml.encode('utf-16'))
        run(['schtasks', '/Create', '/TN', name, '/XML', path, '/F'])
        os.remove(path)
    if not keepalive:
        delete(KEEPALIVE)


def delete(name):
    run(['schtasks', '/Delete', '/TN', name, '/F'])


def uninstall():
    for name in NAMES:
        delete(name)


def get_states():
    '''{name: Ready, Running, Disabled or Missing} read without elevation.'''
    names = ', '.join(quote(v) for v in NAMES)
    code, output = powershell(STATES.format(names=names))
    states = {name: 'Missing' for name in NAMES}
    for line in output.split('\n'):
        name, _, state = line.strip().rpartition('|')
        if name in states:
            states[name] = state
    return states


def start(name):
    # a task still running ignores a new start
    deadline = time.time() + 30
    while get_states().get(name) == 'Running' and time.time() < deadline:
        time.sleep(0.5)
    return run(['schtasks', '/Run', '/TN', name])[0] == 0
