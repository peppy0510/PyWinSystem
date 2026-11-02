# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import os
import re
import shutil


SECTION = re.compile(r'^\s*\[([^\]]+)\]\s*$')
ENTRY = re.compile(r'^(\s*)([A-Za-z0-9_.]+)(\s*=\s*)(.*?)\s*$')
# a comment after a value needs a space before it, so a path with # survives
INLINE_COMMENT = re.compile(r'\s+[#;].*$')


def get_path():
    return os.path.join(os.path.expanduser('~'), '.wslconfig')


def decode(data):
    if data.startswith(b'\xef\xbb\xbf'):
        return data[3:].decode('utf-8', 'replace'), 'utf-8-sig'
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16'), 'utf-16'
    try:
        return data.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        return data.decode('mbcs', 'replace'), 'mbcs'


def read_lines(path=None):
    try:
        with open(path or get_path(), 'rb') as file:
            text, encoding = decode(file.read())
    except FileNotFoundError:
        return [], 'utf-8', '\r\n'
    newline = '\r\n' if '\r\n' in text else '\n'
    return text.replace('\r\n', '\n').split('\n'), encoding, newline


def parse(lines):
    '''{section: {key: value}} with comments stripped, the last of a repeated key winning.'''
    config = {}
    section = None
    for line in lines:
        if line.lstrip().startswith(('#', ';')):
            continue
        matched = SECTION.match(line)
        if matched:
            section = matched.group(1).strip()
            config.setdefault(section, {})
            continue
        matched = ENTRY.match(line)
        if matched and section is not None:
            config[section][matched.group(2)] = INLINE_COMMENT.sub('', matched.group(4))
    return config


def read(path=None):
    return parse(read_lines(path)[0])


def get_networking_mode(config=None):
    config = read() if config is None else config
    return config.get('wsl2', {}).get('networkingMode', 'nat').strip().lower()


def find_section(lines, section):
    '''(first line after the header, end of the section) or None.'''
    start = None
    for index, line in enumerate(lines):
        matched = SECTION.match(line)
        if not matched:
            continue
        if start is not None:
            return start, index
        if matched.group(1).strip().lower() == section.lower():
            start = index + 1
    return (start, len(lines)) if start is not None else None


def set_entry(lines, section, key, value):
    '''Rewrites one key in place and leaves every other line as it was; None removes the key.'''
    found = find_section(lines, section)
    if found is None:
        if value is None:
            return lines
        while lines and not lines[-1].strip():
            lines.pop()
        return lines + ([''] if lines else []) + [f'[{section}]', f'{key}={value}', '']

    start, end = found
    last = None
    for index in range(start, end):
        matched = ENTRY.match(lines[index])
        if matched and not lines[index].lstrip().startswith(('#', ';')):
            last = index
            if matched.group(2).lower() == key.lower():
                if value is None:
                    lines = lines[:index] + lines[index + 1:]
                    end -= 1
                    # a section left with nothing in it goes with its header
                    if not any(line.strip() for line in lines[start:end]):
                        header = start - 1
                        while header > 0 and not lines[header - 1].strip():
                            header -= 1
                        lines = lines[:header] + lines[end:]
                    return lines
                indent, name, equal = matched.group(1), matched.group(2), matched.group(3)
                comment = INLINE_COMMENT.search(matched.group(4))
                tail = comment.group(0) if comment else ''
                lines[index] = f'{indent}{name}{equal}{value}{tail}'
                return lines
    if value is None:
        return lines
    at = (last + 1) if last is not None else start
    return lines[:at] + [f'{key}={value}'] + lines[at:]


def change_lines(lines, changes):
    for (section, key), value in changes.items():
        lines = set_entry(lines, section, key, None if value is None else str(value))
    if lines and lines[-1] != '':
        lines.append('')
    return lines


def change_text(text, changes):
    '''The same edit on text in memory, for /etc/wsl.conf that lives inside a distribution.'''
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = text.replace('\r\n', '\n').split('\n') if text else []
    return newline.join(change_lines(lines, changes))


def write(changes, path=None, backup=True):
    '''changes maps (section, key) to a value or None; the old file stays as .wslconfig.bak.'''
    path = path or get_path()
    lines, encoding, newline = read_lines(path)
    lines = change_lines(lines, changes)
    if backup and os.path.exists(path):
        shutil.copyfile(path, path + '.bak')
    with open(path, 'w', encoding=encoding, newline='') as file:
        file.write(newline.join(lines))
