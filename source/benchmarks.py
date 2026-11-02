# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com

Benchmark pages for a processor or a graphics card, opened in the browser. The sites turn
away scripted requests, so the app only builds the address and lets the browser go there.
'''


import os
import re
import urllib.parse


# what Windows adds to a name that the benchmark sites leave out
NOISE = re.compile(r'\((?:R|TM|C)\)|\b(?:CPU|Processor|\d+(?:st|nd|rd|th) Gen)\b|@.*$|'
                   r'\b\d+-Core\b', re.IGNORECASE)
GPU_VENDORS = re.compile(r'^(?:NVIDIA|AMD|ATI)\s+', re.IGNORECASE)
CPU_VENDORS = re.compile(r'^(?:Intel|AMD)\s+', re.IGNORECASE)
# Technical City writes a memory size apart, GeForce-GTX-1060-6-GB
MEMORY_SIZE = re.compile(r'\b(\d+)(GB|MB)\b', re.IGNORECASE)


def tidy(name):
    return ' '.join(NOISE.sub(' ', name or '').split())


def get_slug(name):
    '''Technical City names a page by the model without its maker, words joined by hyphens.'''
    return '-'.join(MEMORY_SIZE.sub(r'\1 \2', name).split())


def get_userbenchmark(name):
    # a model page needs the site's own id, so its search, which first asks to pick the
    # human; once passed the browser usually is not asked again for a while
    return ('UserBenchmark', 'https://www.userbenchmark.com/Search?searchTerm=' +
            urllib.parse.quote_plus(name))


# Technical City opens straight on the model with the scores of many benchmarks side by side
def get_cpu_links(name):
    name = tidy(name)
    return [('PassMark', 'https://www.cpubenchmark.net/cpu.php?cpu=' +
             urllib.parse.quote_plus(name)),
            ('Technical City', 'https://technical.city/en/cpu/' +
             urllib.parse.quote(get_slug(CPU_VENDORS.sub('', name)))),
            get_userbenchmark(name)]


def get_gpu_links(name):
    # PassMark finds a graphics card only with its own id beside the name, which the app
    # cannot know, so the card goes without it
    name = GPU_VENDORS.sub('', tidy(name))
    return [('Technical City', 'https://technical.city/en/video/' +
             urllib.parse.quote(get_slug(name))),
            get_userbenchmark(name)]


def open_page(url):
    # the default browser through the shell; explorer takes an address with a query for a
    # path and opens a folder window instead
    os.startfile(url)
