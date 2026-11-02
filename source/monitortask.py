# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com

Keeps the graphics card gamma without the window. Windows puts the ramp back on every sign-in,
unlock and resume, so a task of the signed-in user applies the stored values again then. It
is registered only while some screen differs from untouched.
'''


import json
import os
import tempfile

import displays
import wsltasks

from wslshell import run


NAME = 'PyWinSystem Monitors'
SETTINGS_PATH = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'PyWinSystem',
                             'settings.json')

TEMPLATE = '''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Applies the saved monitor gamma after sign-in, unlock, resume.</Description>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>{user_id}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT2M</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <Hidden>true</Hidden>
  </Settings>
  <Triggers>
    <LogonTrigger>
      <UserId>{user_id}</UserId>
      <Delay>PT5S</Delay>
    </LogonTrigger>
    <SessionStateChangeTrigger>
      <UserId>{user_id}</UserId>
      <StateChange>SessionUnlock</StateChange>
      <Delay>PT2S</Delay>
    </SessionStateChangeTrigger>
{resume}
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


def read_stored():
    '''{key: gamma values} the window saved, read without wx.'''
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as file:
            return json.load(file).get('monitors') or {}
    except (OSError, ValueError, AttributeError):
        return {}


def is_registered():
    return run(['schtasks', '/Query', '/TN', NAME])[0] == 0


def register():
    '''Needs no elevation: a task of the signed-in user for that user.'''
    author, user_id = wsltasks.get_identity()
    command, prefix, folder = wsltasks.get_launcher()
    xml = TEMPLATE.format(user_id=wsltasks.escape(user_id),
                          resume=wsltasks.RESUME_TRIGGER.replace('PT10S', 'PT5S'),
                          command=wsltasks.escape(command),
                          arguments=wsltasks.escape(f'{prefix}--monitors restore'),
                          folder=wsltasks.escape(folder))
    path = os.path.join(tempfile.gettempdir(), f'{NAME}.xml')
    with open(path, 'wb') as file:
        file.write(xml.encode('utf-16'))
    code = run(['schtasks', '/Create', '/TN', NAME, '/XML', path, '/F'])[0]
    os.remove(path)
    return code == 0


def unregister():
    run(['schtasks', '/Delete', '/TN', NAME, '/F'])


def sync(stored):
    '''The task while some screen differs from untouched, none otherwise.'''
    wanted = any(values != displays.DEFAULT_SOFTWARE for values in stored.values())
    if wanted and not is_registered():
        register()
    elif not wanted and is_registered():
        unregister()


def main(argv):
    arguments = argv[argv.index('--monitors') + 1:]
    if arguments[:1] == ['restore']:
        displays.restore_gamma(read_stored())
        return 0
    print('usage: main.pyw --monitors restore')
    return 2
