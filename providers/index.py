"""Pluggable, persisted index built from source/JDK/JAR providers."""
import glob
import gzip
import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import zipfile
from collections import defaultdict
from ..core.java_source import package_name, declarations

CACHE_VERSION = 3
_LOCK = threading.RLock()


def record(name, qualified, origin, provider):
    return {"name": name, "qualified_name": qualified, "origin": origin, "provider": provider}


def sources(roots, config):
    excluded = set(config.get('exclude_dirs', []))
    for root in roots:
        if not os.path.isdir(root): continue
        for directory, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in excluded and not d.startswith('.smimp')]
            for file in files:
                if file.endswith('.java') and file not in ('module-info.java', 'package-info.java'):
                    path = os.path.join(directory, file)
                    if not os.path.islink(path) and os.path.realpath(path).startswith(os.path.realpath(root) + os.sep):
                        yield path


def jar_paths(roots, patterns):
    found = set()
    for root in roots:
        for pattern in patterns:
            actual = pattern if os.path.isabs(pattern) else os.path.join(root, pattern)
            for file in glob.iglob(actual, recursive=True):
                if file.endswith(('.jar', '.jmod')) and os.path.isfile(file):
                    found.add(os.path.realpath(file))
    return sorted(found)


def jdk_paths(java_cmd='java'):
    homes = [os.getenv('JAVA_HOME', '')]
    if platform.system() == 'Darwin':
        try:
            found = subprocess.run(['/usr/libexec/java_home'], capture_output=True, text=True,
                                   timeout=5, check=True).stdout.strip()
            homes.append(found)
        except (OSError, subprocess.SubprocessError):
            pass
    executable = shutil.which(java_cmd)
    if executable:
        homes.append(os.path.dirname(os.path.dirname(os.path.realpath(executable))))
    for home in homes:
        if home:
            modules = os.path.join(home, 'jmods')
            if os.path.isdir(modules):
                return sorted(glob.glob(os.path.join(modules, '*.jmod')))
    return []


def scan_archive(path, provider):
    results = []
    try:
        with zipfile.ZipFile(path) as jar:
            for filename in jar.namelist():
                if path.endswith('.jmod'):
                    if not filename.startswith('classes/'): continue
                    filename = filename[8:]
                if not filename.endswith('.class') or filename.startswith(('META-INF/', 'module-info')):
                    continue
                if '$' in filename or filename.endswith('/package-info.class'):
                    continue
                qualified = filename[:-6].replace('/', '.')
                if '.' not in qualified: continue
                if provider == 'jdk' and not qualified.startswith(('java.', 'javax.')):
                    continue
                name = qualified.rsplit('.', 1)[1]
                if not name.isidentifier(): continue
                results.append(record(name, qualified, path, provider))
    except (OSError, zipfile.BadZipFile):
        pass
    return results


def scan_source(path):
    try:
        with open(path, encoding='utf-8') as stream: data = stream.read()
        package = package_name(data)
        return [record(name, package + '.' + name if package else name, path, 'sources')
                for name in declarations(data)]
    except (OSError, UnicodeError): return []


class ClassIndex:
    def __init__(self, cache_path):
        self.cache_path = cache_path
        self.items = []
        self.by_name = {}
        self.infos = {}
        self.stats = {}
        self.loaded = False
        self.last_scan = 0

    def rebuild(self, roots, config, force=False):
        cache = {}
        if not force:
            try:
                with gzip.open(self.cache_path, 'rt', encoding='utf-8') as stream:
                    cache = json.load(stream)
            except (OSError, ValueError, EOFError): pass
        old = cache.get('files', {}) if cache.get('version') == CACHE_VERSION else {}
        selected = {}
        providers = config['providers']
        if providers['sources']['enabled']:
            for p in sources(roots, providers['sources']): selected[p] = 'sources'
        if providers['jar_glob']['enabled']:
            for p in jar_paths(roots, providers['jar_glob'].get('patterns', [])):
                selected[p] = 'jar_glob'
        if providers['jdk']['enabled']:
            for p in jdk_paths(config.get('java_executable', 'java')): selected[p] = 'jdk'
        new_cache, counts, invalid = {}, defaultdict(int), 0
        for path, provider in selected.items():
            try:
                stat = os.stat(path)
                signature = [stat.st_mtime_ns, stat.st_size, provider]
            except OSError: continue
            previous = old.get(path, {})
            if previous.get('signature') == signature:
                items = previous['items']
            else:
                items = scan_source(path) if provider == 'sources' else scan_archive(path, provider)
                invalid += 1
            new_cache[path] = {'signature': signature, 'items': items}
            counts[provider] += len(items)
        uniques = {}
        for entry in new_cache.values():
            for item in entry['items']:
                # Always prefer project source for duplicate FQNs.
                ident = item['qualified_name']
                if ident not in uniques or item['provider'] == 'sources': uniques[ident] = item
        self.items = sorted(uniques.values(), key=lambda x: (x['name'].lower(), x['qualified_name']))
        by_name = defaultdict(list)
        for item in self.items: by_name[item['name']].append(item['qualified_name'])
        self.by_name = dict(by_name)
        self.infos = {item['qualified_name']: item for item in self.items}
        self.stats = {'types': len(self.items), 'files': len(new_cache), 'rescanned': invalid, 'by_provider': dict(counts)}
        self.loaded, self.last_scan = True, time.time()
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        tmp = self.cache_path + '.tmp'
        try:
            with gzip.open(tmp, 'wt', encoding='utf-8') as stream:
                json.dump({'version': CACHE_VERSION, 'files': new_cache}, stream, separators=(',', ':'))
            os.replace(tmp, self.cache_path)
        except OSError: pass
        return self
