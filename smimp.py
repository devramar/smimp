"""smimp Sublime Text 4 entry point. Python 3.8+ plugin host."""
import gzip
import difflib
import hashlib
import json
import os
import tempfile
import threading
import time
from collections import defaultdict

import sublime
import sublime_plugin

from .core.config import DEFAULTS, merge, project_root, load_project_config
from .core.java_source import (package_name, symbol_at, reconcile_imports,
                               unused_explicit_imports)
from .core.import_sort import format_imports, import_names
from .core.parser import JavaParser
from .core.resolver import resolve
from .core.scopes import canonical, normalized_roots, owning_root, within, child_folders
from .providers.index import ClassIndex, sources

_INDEXES = {}
_PARSERS = {}
_BATCHES = {}
_MUTEX = threading.RLock()


def _cache():
    path = os.path.join(sublime.cache_path(), 'smimp')
    os.makedirs(path, exist_ok=True)
    return path


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _text(view):
    return view.substr(sublime.Region(0, view.size()))


def _root(window):
    v = window.active_view()
    return project_root(window.folders(), v.file_name() if v else None)


def _config(window, root_override=None):
    root = root_override if root_override is not None else _root(window)
    settings = sublime.load_settings('smimp.sublime-settings')
    custom = {k: settings.get(k) for k in DEFAULTS if settings.get(k) is not None}
    return merge(merge(DEFAULTS, custom), load_project_config(root)), root


def _ui(action):
    sublime.set_timeout(action, 0)


def _notice(window, message):
    _ui(lambda: sublime.status_message('smimp: ' + message))


def _error(window, message):
    _ui(lambda: sublime.error_message('smimp: ' + message))


def _ensure(window, callback, force=False, root_override=None):
    """Always refresh file metadata asynchronously; share index builds per window/config."""
    try:
        config, root = _config(window, root_override)
    except (ValueError, OSError) as exc:
        _error(window, str(exc))
        return
    roots = window.folders()
    if not roots:
        _error(window, 'Open a project folder to index Java sources.')
        return
    key = str(window.id()) + ':' + hashlib.sha256(json.dumps(
        [roots, config['providers'], config.get('java_executable')], sort_keys=True).encode()).hexdigest()
    with _MUTEX:
        state = _INDEXES.get(key)
        if state is None:
            state = {'index': ClassIndex(os.path.join(_cache(), 'index-' + key.split(':')[1] + '.json.gz')),
                     'busy': False, 'waiting': []}
            _INDEXES[key] = state
        state['waiting'].append(callback)
        if state['busy']: return
        if state['index'].loaded and not force and time.time() - state['index'].last_scan < 30:
            waiting, state['waiting'] = state['waiting'], []
            for cb in waiting: _ui(lambda cb=cb: cb(state['index'], config, root))
            return
        state['busy'] = True

    _notice(window, 'Indexing sources and configured libraries...')
    def work():
        error = None
        try:
            state['index'].rebuild(roots, config, force)
        except Exception as exc:
            error = str(exc)
        with _MUTEX:
            waiting, state['waiting'] = state['waiting'], []
            state['busy'] = False
        if error:
            _error(window, 'Index failed: ' + error)
        else:
            _notice(window, '{} classes indexed'.format(state['index'].stats['types']))
            for cb in waiting:
                _ui(lambda cb=cb: cb(state['index'], config, root))
    threading.Thread(target=work, name='smimp-index', daemon=True).start()


def _parser(config):
    key = (config.get('java_executable'), config.get('javac_executable'), config.get('parser'))
    with _MUTEX:
        if key not in _PARSERS:
            _PARSERS[key] = JavaParser(os.path.join(_cache(), 'parser'),
                os.path.join(os.path.dirname(__file__), 'java', 'SmimpParser.java'),
                config.get('javac_executable', 'javac'), config.get('java_executable', 'java'),
                config.get('parser', 'javac'))
        return _PARSERS[key]


def plugin_unloaded():
    for parser in list(_PARSERS.values()): parser.close()


def _settings_file():
    return os.path.join(sublime.packages_path(), 'User', 'smimp.sublime-settings')


def _store_preference(scope, root, simple, qualified):
    if scope == 'global':
        settings = sublime.load_settings('smimp.sublime-settings')
        prefs = dict(settings.get('preferred_imports', {}))
        prefs[simple] = qualified
        settings.set('preferred_imports', prefs)
        sublime.save_settings('smimp.sublime-settings')
    elif root:
        filename = os.path.join(root, '.smimp.json')
        content = load_project_config(root)
        content.setdefault('preferred_imports', {})[simple] = qualified
        tmp = filename + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as stream:
            json.dump(content, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
        os.replace(tmp, filename)


def _source_imports(index, text, proposals=(), source_packages=None):
    """Find local-source imports from the index without assuming a build system."""
    if not index:
        return []
    qualified = [name for name, _static in import_names(text)] + list(proposals)
    if source_packages is None:
        source_packages = {x['qualified_name'].rsplit('.', 1)[0]
                           for x in index.items if x['provider'] == 'sources' and
                           '.' in x['qualified_name']}
    project_names = set()
    for name in qualified:
        owner = name
        while '.' in owner:
            info = index.infos.get(owner)
            if info and info['provider'] == 'sources':
                project_names.add(owner)
                break
            owner = owner.rsplit('.', 1)[0]
        if name.endswith('.*') and name[:-2] in source_packages:
            project_names.add(name)
    return sorted(project_names)


def _sort_options(config):
    return config.get('import_sort', {})


class SmimpApplyImportsCommand(sublime_plugin.TextCommand):
    """Exactly one editor transaction, so regular Ctrl+Z reverses everything."""
    def run(self, edit, imports=None, expected_hash=None, restore=None,
            sort_after=False, source_imports=None, project_prefixes=None):
        original = _text(self.view)
        if expected_hash and _hash(original) != expected_hash:
            sublime.status_message('smimp: File changed; import operation cancelled.')
            return
        skipped_removals = []
        if restore is not None:
            updated = restore
        else:
            updated, _added, _removed, skipped_removals = reconcile_imports(original, imports or [])
        if sort_after and restore is None:
            updated, warning = format_imports(updated, source_imports or (), project_prefixes or ())
            if warning:
                sublime.status_message('smimp: ' + warning)
        if skipped_removals:
            sublime.status_message('smimp: Could not replace commented import(s): ' +
                                   ', '.join(skipped_removals))
        if original == updated: return
        start = 0
        while start < min(len(original), len(updated)) and original[start] == updated[start]:
            start += 1
        endold, endnew = len(original), len(updated)
        while endold > start and endnew > start and original[endold - 1] == updated[endnew - 1]:
            endold -= 1
            endnew -= 1
        self.view.replace(edit, sublime.Region(start, endold), updated[start:endnew])


def _view_by_id(window, ident):
    return next((v for v in window.views() if v.id() == ident), None)


def _open_view(window, file):
    # Sublime's find_open_file considers all groups in the same window.
    return window.find_open_file(file)


def _pick(window, label, values, done, default=0):
    window.show_quick_panel(values, done, selected_index=default, placeholder=label)


def _choose_import(window, index, config, root, view, simple, options, done, allow_once=True):
    """Select candidate then persistence policy. One decision per symbol per batch."""
    lines = [sublime.QuickPanelItem(trigger=item, annotation=index.infos.get(item, {}).get('provider', ''),
                                    details=index.infos.get(item, {}).get('origin', '')) for item in options]
    lines.append(sublime.QuickPanelItem(trigger='Skip {}'.format(simple), annotation='No import'))

    def selected(i):
        if i < 0 or i == len(options):
            done(None)
            return
        qualified = options[i]
        def mode(choice):
            if allow_once:
                if choice < 0 or choice == 3:
                    done(None)
                else:
                    done((qualified, None if choice == 0 else 'project' if choice == 1 else 'global'))
            else:
                done((qualified, 'project' if choice == 0 else 'global') if choice in (0, 1) else None)
        choices = (['Use once: ' + qualified,
                    'Always use in this project: ' + qualified,
                    'Always use globally: ' + qualified,
                    'Skip this symbol'] if allow_once else
                   ['Always use in this project: ' + qualified,
                    'Always use globally: ' + qualified,
                    'Cancel'])
        _pick(window, 'Decision for ' + simple, choices, mode)
    _pick(window, 'Resolve ' + simple, lines, selected)


def _commit_changes(window, changes, batch=False):
    """Validate, commit, and (for project operations) record a revert manifest.

    A clean open buffer gets one normal undoable TextCommand. Closed files are
    atomically replaced on disk; cross-file rollback uses the batch manifest.
    """
    for entry in changes:
        path = entry['path']
        view = (_view_by_id(window, entry['view_id']) if path == '<untitled>' else
                _open_view(window, path))
        if view:
            if _hash(_text(view)) != _hash(entry['source']) or view.is_read_only():
                _error(window, 'File changed or is read-only: ' + path)
                return False
        else:
            try:
                if _hash(_read_file(path)) != _hash(entry['source']):
                    raise ValueError('File changed')
            except (OSError, UnicodeError, ValueError):
                _error(window, 'File changed or is inaccessible: ' + path)
                return False

    applied = []
    try:
        for entry in changes:
            path = entry['path']
            view = (_view_by_id(window, entry['view_id']) if path == '<untitled>' else
                    _open_view(window, path))
            if view:
                view.run_command('smimp_apply_imports', {
                    'restore': entry['updated'], 'expected_hash': _hash(entry['source'])})
                applied.append(entry)
                if _hash(_text(view)) != _hash(entry['updated']):
                    raise RuntimeError('Editor refused to apply changes: ' + path)
            else:
                _write_atomic(path, entry['updated'])
                applied.append(entry)

        if batch:
            manifest = _batch_manifest(window)
            # Use atomic replacement so an interrupted write cannot corrupt an
            # existing usable manifest from the previous batch.
            temp_manifest = manifest + '.tmp'
            try:
                with gzip.open(temp_manifest, 'wt', encoding='utf-8') as stream:
                    json.dump([{'path': e['path'], 'before': e['source'],
                                'after': _hash(e['updated'])} for e in applied], stream)
                os.replace(temp_manifest, manifest)
            finally:
                if os.path.exists(temp_manifest): os.remove(temp_manifest)
            _BATCHES[window.id()] = manifest
    except Exception as exc:
        for entry in reversed(applied):
            try:
                view = (_view_by_id(window, entry['view_id']) if entry['path'] == '<untitled>' else
                        _open_view(window, entry['path']))
                current = _text(view) if view else _read_file(entry['path'])
                if _hash(current) == _hash(entry['updated']):
                    if view:
                        view.run_command('smimp_apply_imports', {
                            'restore': entry['source'], 'expected_hash': _hash(entry['updated'])})
                    else:
                        _write_atomic(entry['path'], entry['source'])
            except Exception:
                pass  # Never overwrite a file changed externally during rollback.
        _error(window, 'Batch failed; rollback attempted: ' + str(exc))
        return False
    return True


class SmimpImportClassCommand(sublime_plugin.WindowCommand):
    """ListInputHandler supplies native fuzzy filtering and initial cursor text."""
    def run(self, qualified_name, prefill='', view_id=None):
        target = None
        if view_id is not None:
            for v in self.window.views():
                if v.id() == view_id: target = v; break
        target = target or self.window.active_view()
        if target:
            config = _PICKER_CONFIG.get(self.window.id(), {})
            index = _PICKER_INDEX.get(self.window.id())
            sort_cfg = _sort_options(config)
            target.run_command('smimp_apply_imports', {
                'imports': [qualified_name],
                'sort_after': bool(sort_cfg.get('on_insert', True)),
                'source_imports': _source_imports(index, _text(target), [qualified_name]),
                'project_prefixes': sort_cfg.get('project_package_prefixes', [])
            })
            sublime.status_message('smimp: import ' + qualified_name)

    def input(self, args):
        if 'qualified_name' in args: return None
        return SmimpClassInputHandler(_PICKER_INDEX.get(self.window.id()), args.get('prefill', ''),
                                      _PICKER_PREFS.get(self.window.id(), {}))


class SmimpClassInputHandler(sublime_plugin.ListInputHandler):
    def __init__(self, index=None, prefill='', preferences=None):
        self.index = index
        self.prefill = prefill
        self.preferences = preferences or {}

    def name(self): return 'qualified_name'
    def placeholder(self): return 'Search classes in sources, JARs and JDK'
    def initial_text(self): return self.prefill
    def initial_selection(self): return [(0, len(self.prefill))] if self.prefill else []
    def list_items(self):
        if self.index is None: return []
        ordered = sorted(self.index.items, key=lambda i: (i['name'].lower(),
                       i['qualified_name'] != self.preferences.get(i['name']),
                       i['provider'] != 'sources', i['qualified_name']))
        return [sublime.ListInputItem(text=item['name'], value=item['qualified_name'],
                    details=item['qualified_name'] + '  ·  ' + item['provider'] + '  ·  ' + os.path.basename(item['origin']))
                for item in ordered]


class SmimpImportAtCursorCommand(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.active_view()
        if not view or not view.match_selector(0, 'source.java'):
            sublime.status_message('smimp: Open a Java file.')
            return
        offset = view.sel()[0].begin() if view.sel() else 0
        name = symbol_at(_text(view), offset)
        def ready(index, config, root):
            if not index.items:
                _error(self.window, 'No classes indexed. Check provider settings.')
                return
            # Use the Command Palette overlay so the ListInputHandler opens before run().
            _PICKER_INDEX[self.window.id()] = index
            _PICKER_PREFS[self.window.id()] = config.get('preferred_imports', {})
            _PICKER_CONFIG[self.window.id()] = config
            self.window.run_command('show_overlay', {'overlay': 'command_palette',
                'command': 'smimp_import_class', 'args': {'prefill': name, 'view_id': view.id()}})
        _ensure(self.window, ready)


_PICKER_INDEX = {}
_PICKER_PREFS = {}
_PICKER_CONFIG = {}
_PENDING_REVIEWS = {}


class _Session:
    def __init__(self, window, scope, mode, index, config, root, package=None):
        self.window, self.scope, self.mode = window, scope, mode
        self.index, self.config, self.root = index, config, root
        self.package = package
        self.entries = []
        self.ambiguous = {}
        self.unknown = defaultdict(int)
        self.decisions = {}
        self.pref_updates = []
        self.skipped = []

    def start(self):
        captures = {}
        if self.scope == 'file':
            view = self.window.active_view()
            if view and view.match_selector(0, 'source.java'):
                captures[view.file_name() or '<untitled>'] = (_text(view), view.id())
            if not captures:
                _notice(self.window, 'No eligible Java file.')
                return
        _notice(self.window, 'Analyzing Java files...')
        def work():
            if self.scope != 'file':
                paths = list(sources(self.window.folders(), self.config['providers']['sources']))
                limit = int(self.config.get('max_batch_files', 5000))
                if len(paths) > limit:
                    _error(self.window, 'Batch exceeds max_batch_files ({}).'.format(limit))
                    return
                for path in paths:
                    opened = _open_view(self.window, path)
                    if opened and opened.is_dirty():
                        self.skipped.append(path + ' (unsaved changes)')
                        continue
                    captures[path] = (None, opened.id() if opened else None)
            if not captures:
                _notice(self.window, 'No eligible Java files.')
                return
            parser = _parser(self.config)
            for path, (text, vid) in captures.items():
                if text is None:
                    try:
                        with open(path, encoding='utf-8', newline='') as stream: text = stream.read()
                    except (OSError, UnicodeError):
                        self.skipped.append(path + ' (unreadable UTF-8)')
                        continue
                if self.scope == 'package':
                    p = package_name(text)
                    if not (p == self.package or p.startswith(self.package + '.')): continue
                found, reliable = parser.analyze(text)
                auto_cfg = self.config.get('auto_import', {})
                resolved, ambiguous, unknown = resolve(
                    text, found, self.index.by_name, self.config.get('preferred_imports', {}),
                    auto_cfg.get('repair_unindexed_explicit_imports', True))
                unused = (unused_explicit_imports(text, found)
                          if reliable and auto_cfg.get('remove_unused_explicit_imports', True) else [])
                if resolved or ambiguous or unused:
                    self.entries.append({'path': path, 'view_id': vid, 'source': text,
                                         'resolved': resolved, 'ambiguous': ambiguous,
                                         'unused': unused, 'analysis_reliable': reliable})
                    for name, options in ambiguous.items(): self.ambiguous[name] = options
                for name in unknown: self.unknown[name] += 1
            _ui(self._next)
        threading.Thread(target=work, name='smimp-parse', daemon=True).start()

    def _next(self):
        remaining = [n for n in sorted(self.ambiguous) if n not in self.decisions]
        if self.mode == 'attempt_all' and remaining:
            name = remaining[0]
            def chosen(outcome):
                self.decisions[name] = outcome[0] if outcome else None
                if outcome and outcome[1]: self.pref_updates.append((outcome[1], name, outcome[0]))
                self._next()
            _choose_import(self.window, self.index, self.config, self.root,
                           self.window.active_view(), name, self.ambiguous[name], chosen)
            return
        self.review()

    def _changes(self):
        changes = []
        for entry in self.entries:
            qualified = list(entry['resolved'].values())
            if self.mode == 'attempt_all':
                qualified.extend(self.decisions[name] for name in entry['ambiguous'] if self.decisions.get(name))
            updated, imported, removed, skipped_removals = reconcile_imports(
                entry['source'], qualified, entry.get('unused', ()))
            if skipped_removals:
                self.skipped.append(entry['path'] + ' (commented import(s) kept: ' +
                                    ', '.join(skipped_removals) + ')')
            if imported or removed:
                sort_cfg = _sort_options(self.config)
                if sort_cfg.get('on_insert', True):
                    updated, warning = format_imports(
                        updated,
                        _source_imports(self.index, updated, qualified),
                        sort_cfg.get('project_package_prefixes', []))
                    if warning:
                        self.skipped.append(entry['path'] + ' (' + warning + ')')
                changes.append({**entry, 'updated': updated, 'added': imported, 'removed': removed})
        return changes

    def review(self):
        _PENDING_REVIEWS[self.window.id()] = self
        changes = self._changes()
        count = sum(len(c['added']) for c in changes)
        removed_count = sum(len(c.get('removed', ())) for c in changes)
        conflicts = len(self.ambiguous) - sum(1 for val in self.decisions.values() if val)
        labels = [
            'Apply {} import(s), remove/replace {} import(s) in {} file(s){}'.format(
                count, removed_count, len(changes),
                ' and sort import blocks' if _sort_options(self.config).get('on_insert', True) else ''),
            'Preview proposed imports',
            'Cancel'
        ]
        def choice(i):
            if i == 0: self.apply(changes)
            if i == 1:
                report = self.window.new_file()
                report.set_name('smimp · Import Review (not saved)')
                report.set_scratch(True)
                body = ['smimp import review', '', 'Scope: ' + self.scope,
                        'Files: {}'.format(len(changes)), 'Imports added: {}'.format(count),
                        'Imports removed/replaced: {}'.format(removed_count),
                        'Unresolved names: {}'.format(len(self.unknown)),
                        'Ambiguous names left out: {}'.format(conflicts),
                        'Sorting enabled: {}'.format(bool(_sort_options(self.config).get('on_insert', True))),
                        'Sort warnings: {}'.format(len([x for x in self.skipped if 'Skipped sorting' in x])), '']
                for change in changes:
                    body.append(change['path'])
                    body.extend('    - import {};'.format(x) for x in change.get('removed', ()))
                    body.extend('    + import {};'.format(x) for x in change['added'])
                    body.append('')
                if self.unknown:
                    body.append('Unknown symbols (not imported): ' + ', '.join(sorted(self.unknown)))
                report.run_command('append', {'characters': '\n'.join(body), 'force': True})
                sublime.status_message('smimp: Review open. Use Command Palette → smimp: Resume Import Review.')
        _pick(self.window, 'smimp review', labels, choice)

    def apply(self, changes):
        if not changes:
            _PENDING_REVIEWS.pop(self.window.id(), None)
            _notice(self.window, 'Nothing to import.')
            return
        if not _commit_changes(self.window, changes, batch=self.scope != 'file'):
            return
        _PENDING_REVIEWS.pop(self.window.id(), None)
        for scope, name, qualified in self.pref_updates:
            try: _store_preference(scope, self.root, name, qualified)
            except (OSError, ValueError) as exc:
                _error(self.window, 'Imports applied, but a preference could not be saved: ' + str(exc))
        _notice(self.window, 'Applied {} import(s), removed/replaced {} import(s) in {} file(s).'.format(
            sum(len(c['added']) for c in changes),
            sum(len(c.get('removed', ())) for c in changes), len(changes)))


def _batch_manifest(window):
    root_sig = json.dumps(window.folders(), sort_keys=True).encode('utf-8')
    return os.path.join(_cache(), 'last-batch-' + hashlib.sha256(root_sig).hexdigest() + '.json.gz')


def _read_file(path):
    with open(path, encoding='utf-8', newline='') as stream:
        return stream.read()


def _write_atomic(path, content):
    import stat
    old_mode = stat.S_IMODE(os.stat(path).st_mode)
    temp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='', dir=os.path.dirname(path),
                                         prefix='.smimp-', delete=False) as out:
            temp = out.name
            out.write(content)
        os.chmod(temp, old_mode)
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp): os.remove(temp)


class SmimpSortImportsCommand(sublime_plugin.WindowCommand):
    """Explicit formatter; one edit, one ordinary undo step."""
    def run(self):
        view = self.window.active_view()
        if not view or not view.match_selector(0, 'source.java'):
            _notice(self.window, 'Open a Java file to sort its imports.')
            return
        original = _text(view)
        view_id = view.id()
        def ready(index, config, root):
            active = _view_by_id(self.window, view_id)
            if not active:
                return
            if _hash(_text(active)) != _hash(original):
                _notice(self.window, 'File changed while indexing; sorting cancelled.')
                return
            sort_cfg = _sort_options(config)
            updated, warning = format_imports(
                original,
                _source_imports(index, original),
                sort_cfg.get('project_package_prefixes', []))
            if warning:
                _notice(self.window, warning)
            elif updated == original:
                _notice(self.window, 'Imports already sorted.')
            else:
                active.run_command('smimp_apply_imports', {
                    'restore': updated, 'expected_hash': _hash(original)})
                _notice(self.window, 'Imports sorted (Ctrl+Z to undo).')
        _ensure(self.window, ready)


class _SortScopePicker:
    """Quick panels that can never navigate above the open project roots."""
    def __init__(self, window, on_choose):
        self.window = window
        self.on_choose = on_choose
        self.roots = normalized_roots(window.folders())
        view = window.active_view()
        self.active_file = view.file_name() if view else None
        self.active_root = owning_root(self.roots, self.active_file)
        self.active_folder = canonical(os.path.dirname(self.active_file)) if self.active_root else None

    def _select(self, directories, description, config_root=None):
        if normalized_roots(self.window.folders()) != self.roots:
            _error(self.window, 'Project folders changed; reopen the scope selector.')
            return
        selected = normalized_roots(directories)
        if len(selected) != len(directories) or any(not any(within(d, root) for root in self.roots)
                                                      for d in selected):
            _error(self.window, 'Selected folder is no longer within this project.')
            return
        self.on_choose(selected, description, config_root)

    def show(self):
        choices = []
        actions = []
        if self.active_root and self.active_folder:
            choices.append(sublime.QuickPanelItem(
                trigger="This file's folder (and subfolders)", annotation='Default',
                details=self.active_folder))
            actions.append(lambda: self._select([self.active_folder], self.active_folder, self.active_root))
            choices.append(sublime.QuickPanelItem(
                trigger='This project root folder', details=self.active_root))
            actions.append(lambda: self._select([self.active_root], self.active_root, self.active_root))
        choices.append(sublime.QuickPanelItem(
            trigger='All project root folders', annotation='Widest scope',
            details='\n'.join(self.roots)))
        actions.append(lambda: self._select(self.roots, 'All project root folders'))
        choices.append(sublime.QuickPanelItem(
            trigger='Browse project folders…',
            details='Navigate down or up, then sort the selected folder and descendants'))
        actions.append(self.choose_root)
        def picked(i):
            if 0 <= i < len(actions): actions[i]()
        _pick(self.window, 'smimp · Choose import sorting scope', choices, picked)

    def choose_root(self):
        if len(self.roots) == 1:
            self.browse(self.roots[0], self.roots[0])
            return
        items = [sublime.QuickPanelItem(trigger=os.path.basename(root) or root,
                                        details=root,
                                        annotation='Current root' if root == self.active_root else '')
                 for root in self.roots]
        items.append(sublime.QuickPanelItem(trigger='Back to scope options'))
        def chosen(i):
            if i == len(self.roots): self.show()
            elif 0 <= i < len(self.roots):
                self.browse(self.roots[i],
                            self.active_folder if self.roots[i] == self.active_root else self.roots[i])
        _pick(self.window, 'smimp · Choose project root', items, chosen)

    def browse(self, root, current):
        if not within(current, root) or not os.path.isdir(current):
            _error(self.window, 'Folder unavailable or outside project root.')
            return
        current = canonical(current)
        root = canonical(root)
        try:
            settings, _ = _config(self.window, root)
        except (OSError, ValueError) as exc:
            _error(self.window, 'Could not read root settings: ' + str(exc))
            return
        excluded = settings.get('providers', {}).get('sources', {}).get('exclude_dirs', ())
        children = child_folders(current, root, excluded)
        items = [sublime.QuickPanelItem(
            trigger='Sort imports here (including subfolders)', annotation='Select', details=current)]
        actions = [lambda: self._select([current], current, root)]
        if current != root:
            items.append(sublime.QuickPanelItem(trigger='..  Up one folder',
                                                details=os.path.dirname(current)))
            actions.append(lambda: self.browse(root, os.path.dirname(current)))
        if len(self.roots) > 1:
            items.append(sublime.QuickPanelItem(trigger='Choose another project root…'))
            actions.append(self.choose_root)
        else:
            items.append(sublime.QuickPanelItem(trigger='Back to scope options'))
            actions.append(self.show)
        for path in children:
            items.append(sublime.QuickPanelItem(trigger=os.path.basename(path) + '/',
                                                annotation='Open folder', details=path))
            actions.append(lambda path=path: self.browse(root, path))
        def chosen(i):
            if 0 <= i < len(actions): actions[i]()
        _pick(self.window, 'smimp · Folder: ' + current, items, chosen)


class _ProjectSortSession:
    """Format existing imports across the current window's project folders.

    This deliberately does not call the Java parser or resolve missing imports.
    It only invokes the same safe formatter as Sort Imports in File.
    """
    def __init__(self, window, index, config, directories=None, scope_label=None, project_roots=None):
        self.window, self.index, self.config = window, index, config
        self.directories = list(directories if directories is not None else window.folders())
        self.scope_label = scope_label or 'All project root folders'
        self.project_roots = list(project_roots if project_roots is not None
                                  else normalized_roots(window.folders()))
        self.changes = []
        self.skipped = []
        self.scanned = 0

    def start(self):
        if (normalized_roots(self.window.folders()) != self.project_roots or
            not all(any(within(folder, root) for root in self.project_roots)
                    for folder in self.directories)):
            _error(self.window, 'Project roots changed, or sorting scope is outside the project.')
            return
        roots = self.directories
        # Snapshot Sublime view metadata on the UI thread; only disk and index
        # accesses happen in the background scan.
        opened = {os.path.normcase(os.path.realpath(view.file_name())):
                  (view.id(), view.is_dirty(), view.is_read_only())
                  for view in self.window.views() if view.file_name()}
        _notice(self.window, 'Checking Java imports in ' + self.scope_label + '...')

        def work():
            paths = sorted(set(sources(roots, self.config['providers']['sources'])))
            limit = int(self.config.get('max_batch_files', 5000))
            if len(paths) > limit:
                _error(self.window, 'Project contains {} Java files; max_batch_files is {}.'.format(
                    len(paths), limit))
                return
            source_packages = {item['qualified_name'].rsplit('.', 1)[0]
                               for item in self.index.items
                               if item['provider'] == 'sources' and '.' in item['qualified_name']}
            prefixes = _sort_options(self.config).get('project_package_prefixes', [])
            for path in paths:
                self.scanned += 1
                vid, dirty, read_only = opened.get(
                    os.path.normcase(os.path.realpath(path)), (None, False, False))
                if dirty or read_only:
                    self.skipped.append(path + ' (unsaved changes or read-only)')
                    continue
                try:
                    original = _read_file(path)
                except (OSError, UnicodeError):
                    self.skipped.append(path + ' (unreadable UTF-8)')
                    continue
                updated, warning = format_imports(
                    original, _source_imports(self.index, original,
                                              source_packages=source_packages), prefixes)
                if warning:
                    self.skipped.append(path + ' (' + warning + ')')
                elif updated != original:
                    self.changes.append({'path': path, 'view_id': vid,
                                         'source': original, 'updated': updated})
            _ui(self.review)

        threading.Thread(target=work, name='smimp-sort-project', daemon=True).start()

    def review(self):
        if normalized_roots(self.window.folders()) != self.project_roots:
            _error(self.window, 'Project folders changed during sorting; please retry.')
            return
        if not self.changes:
            _PENDING_REVIEWS.pop(self.window.id(), None)
            _notice(self.window, 'No imports need sorting in {} ({} scanned, {} skipped).'.format(
                self.scope_label,
                self.scanned, len(self.skipped)))
            return
        _PENDING_REVIEWS[self.window.id()] = self
        labels = [
            'Apply import sorting to {} file(s)'.format(len(self.changes)),
            'Preview sorting changes',
            'Cancel'
        ]

        def selected(choice):
            if choice == 0:
                self.apply()
            elif choice == 1:
                self.preview()
            elif choice == 2:
                _PENDING_REVIEWS.pop(self.window.id(), None)
        _pick(self.window, 'smimp: {} · {} Java files scanned, {} skipped'.format(
              self.scope_label, self.scanned, len(self.skipped)), labels, selected)

    def preview(self):
        report = self.window.new_file()
        report.set_name('smimp · Project Import Sorting Review (not saved)')
        report.set_scratch(True)
        lines = ['smimp: Project Import Sorting', '',
                 'Scope: ' + self.scope_label,
                 'Java files scanned: {}'.format(self.scanned),
                 'Files with proposed changes: {}'.format(len(self.changes)),
                 'Skipped: {}'.format(len(self.skipped)), '',
                 'Diffs of proposed changes (not yet applied):', '']
        for entry in self.changes:
            lines.extend(difflib.unified_diff(
                entry['source'].splitlines(), entry['updated'].splitlines(),
                fromfile=entry['path'] + ' (original)',
                tofile=entry['path'] + ' (sorted)', lineterm='', n=0))
            lines.append('')
        if self.skipped:
            lines.extend(['Skipped files:', ''] + self.skipped)
        report.run_command('append', {'characters': '\n'.join(lines) + '\n', 'force': True})
        _notice(self.window, 'Preview open. Run smimp: Resume Import Review to apply or cancel.')

    def apply(self):
        if normalized_roots(self.window.folders()) != self.project_roots:
            _error(self.window, 'Project folders changed since review; no files modified.')
            return
        if not _commit_changes(self.window, self.changes, batch=True):
            return
        _PENDING_REVIEWS.pop(self.window.id(), None)
        _notice(self.window, 'Sorted imports in {} Java files ({} skipped). '
                'Use smimp: Revert Last Batch to undo across files.'.format(
                    len(self.changes), len(self.skipped)))


class SmimpSortImportsInProjectCommand(sublime_plugin.WindowCommand):
    def run(self):
        if not self.window.folders():
            _notice(self.window, 'Open a project folder to sort imports.')
            return
        def selected(directories, description, config_root):
            project_roots = normalized_roots(self.window.folders())
            _ensure(self.window, lambda idx, conf, root: _ProjectSortSession(
                self.window, idx, conf, directories, description, project_roots).start(),
                root_override=config_root)
        _SortScopePicker(self.window, selected).show()


class SmimpAutoImportFileCommand(sublime_plugin.WindowCommand):
    def run(self): _begin(self.window, 'file')


class SmimpImportClassesInProjectCommand(sublime_plugin.WindowCommand):
    def run(self): _begin(self.window, 'project')


class SmimpImportClassesInPackageCommand(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.active_view()
        current = package_name(_text(view)) if view else ''
        def received(value):
            value = value.strip()
            if not value or any(not part.isidentifier() for part in value.split('.')):
                _error(self.window, 'Provide a Java package name such as com.example.services.')
                return
            _begin(self.window, 'package', value)
        self.window.show_input_panel('Package and subpackages:', current, received, None, None)


def _begin(window, scope, package=None):
    def menu(choice):
        if choice not in (0, 1): return
        mode = 'attempt_all' if choice == 0 else 'unambiguous'
        _ensure(window, lambda idx, conf, root: _Session(window, scope, mode, idx, conf, root, package).start())
    _pick(window, 'smimp automatic import mode',
          ['Attempt all (default) — ask about ambiguous types',
           'Only unambiguous — no decisions'], menu)


class SmimpResumeImportReviewCommand(sublime_plugin.WindowCommand):
    def run(self):
        session = _PENDING_REVIEWS.get(self.window.id())
        if session: session.review()
        else: _notice(self.window, 'No review awaiting confirmation.')


class SmimpRevertLastBatchCommand(sublime_plugin.WindowCommand):
    def run(self):
        manifest = _BATCHES.get(self.window.id(),
            _batch_manifest(self.window))
        try:
            with gzip.open(manifest, 'rt', encoding='utf-8') as stream: changes = json.load(stream)
        except (OSError, ValueError):
            _error(self.window, 'No prior batch manifest found in this window.')
            return
        for item in changes:
            view = _open_view(self.window, item['path'])
            try:
                current = _text(view) if view else _read_file(item['path'])
            except (OSError, UnicodeError): current = ''
            if _hash(current) != item['after']:
                _error(self.window, 'Rollback stopped: file changed after batch: ' + item['path'])
                return
        def selected(choice):
            if choice != 0: return
            for item in changes:
                view = _open_view(self.window, item['path'])
                if view:
                    view.run_command('smimp_apply_imports', {'restore': item['before'],
                                     'expected_hash': item['after']})
                else:
                    _write_atomic(item['path'], item['before'])
            try: os.remove(manifest)
            except OSError: pass
            _notice(self.window, 'Reverted {} files.'.format(len(changes)))
        _pick(self.window, 'Restore imports from last batch?',
              ['Revert {} files'.format(len(changes)), 'Cancel'], selected)


class SmimpOpenProjectSettingsCommand(sublime_plugin.WindowCommand):
    def run(self):
        root = _root(self.window)
        if not root:
            _error(self.window, 'Open a project folder first.')
            return
        filename = os.path.join(root, '.smimp.json')
        if not os.path.exists(filename):
            with open(filename, 'w', encoding='utf-8') as stream:
                json.dump({'providers': {'jar_glob': {'enabled': False, 'patterns': ['**/env/**/*.jar']}},
                           'preferred_imports': {},
                           'auto_import': {'repair_unindexed_explicit_imports': True,
                                           'remove_unused_explicit_imports': True}},
                          stream, indent=2)
                stream.write('\n')
        self.window.open_file(filename)


class SmimpOpenGlobalSettingsCommand(sublime_plugin.WindowCommand):
    def run(self):
        filename = _settings_file()
        if not os.path.isfile(filename):
            with open(filename, 'w', encoding='utf-8') as stream:
                stream.write('{\n  "preferred_imports": {},\n  "auto_import": {\n'
                             '    "repair_unindexed_explicit_imports": true,\n'
                             '    "remove_unused_explicit_imports": true\n  }\n}\n')
        self.window.open_file(filename)


class SmimpAddPreferredImportCommand(sublime_plugin.WindowCommand):
    def run(self):
        def entered(name):
            name = name.strip()
            if not name.isidentifier():
                _error(self.window, 'Enter a simple Java class name, e.g. List.')
                return
            def indexed(index, conf, root):
                options = index.by_name.get(name, [])
                if not options:
                    _error(self.window, 'No indexed class named ' + name)
                    return
                def done(outcome):
                    if outcome and outcome[1]:
                        try: _store_preference(outcome[1], root, name, outcome[0])
                        except (OSError, ValueError) as exc: _error(self.window, str(exc))
                        else: _notice(self.window, '{} → {} ({})'.format(name, outcome[0], outcome[1]))
                _choose_import(self.window, index, conf, root, self.window.active_view(), name, options, done, allow_once=False)
            _ensure(self.window, indexed)
        view = self.window.active_view()
        initial = symbol_at(_text(view), view.sel()[0].begin()) if view and view.sel() else ''
        self.window.show_input_panel('Preferred class name:', initial, entered, None, None)


class SmimpRebuildClassIndexCommand(sublime_plugin.WindowCommand):
    def run(self): _ensure(self.window, lambda idx, conf, root: _notice(self.window,
        'Rebuilt index: {}'.format(idx.stats)), force=True)


class SmimpShowIndexStatusCommand(sublime_plugin.WindowCommand):
    def run(self):
        def show(idx, conf, root):
            stats = idx.stats
            sublime.message_dialog('smimp index\n\nTypes: {}\nFiles: {}\nRescanned: {}\nProviders: {}\nRoot: {}'.format(
                stats['types'], stats['files'], stats['rescanned'], stats['by_provider'], root or 'none'))
        _ensure(self.window, show)
