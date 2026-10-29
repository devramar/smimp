"""Project-sort regression tests using lightweight Sublime API doubles."""
import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from smimp.core.config import DEFAULTS, merge
from smimp.providers.index import ClassIndex


class FakeWindow:
    def __init__(self, root, opened=()):
        self.root = root
        self.opened = list(opened)
        self.dialog = None

    def folders(self): return [self.root]
    def id(self): return 101
    def views(self): return self.opened
    def find_open_file(self, path):
        return next((v for v in self.opened if v.file_name() == path), None)


class FakeView:
    def __init__(self, path, content, dirty=False):
        self.path = path
        self.content = content
        self.dirty = dirty
        self.read_only = False
    def file_name(self): return self.path
    def id(self): return 22
    def is_dirty(self): return self.dirty
    def is_read_only(self): return self.read_only
    def size(self): return len(self.content)
    def substr(self, region): return self.content
    def run_command(self, command, args):
        assert command == 'smimp_apply_imports', command
        self.content = args['restore']
        self.dirty = True


class SyncThread:
    def __init__(self, target, **kwargs): self.target = target
    def start(self): self.target()


class ProjectSortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_sublime = types.ModuleType('sublime')
        fake_sublime.Region = lambda a, b: (a, b)
        fake_sublime.status_message = lambda text: None
        fake_plugin = types.ModuleType('sublime_plugin')
        fake_plugin.TextCommand = type('TextCommand', (), {})
        fake_plugin.WindowCommand = type('WindowCommand', (), {})
        fake_plugin.ListInputHandler = type('ListInputHandler', (), {})
        with mock.patch.dict(sys.modules, {'sublime': fake_sublime, 'sublime_plugin': fake_plugin}):
            cls.plugin = importlib.import_module('smimp.smimp')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.config = merge(DEFAULTS, {'providers': {'jdk': {'enabled': False}}})
        self.window = FakeWindow(self.root)
        self.cache = os.path.join(self.root, 'test-index.gz')
        self.notices = []
        self.errors = []
        self.patches = [
            mock.patch.object(self.plugin.threading, 'Thread', SyncThread),
            mock.patch.object(self.plugin, '_ui', lambda action: action()),
            mock.patch.object(self.plugin, '_notice', lambda window, msg: self.notices.append(msg)),
            mock.patch.object(self.plugin, '_error', lambda window, msg: self.errors.append(msg)),
            mock.patch.object(self.plugin, '_cache', lambda: self.root),
            mock.patch.object(self.plugin, '_pick', self.pick)
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def pick(self, window, label, values, done, default=0):
        self.window.dialog = (label, values, done)

    def write(self, filename, content):
        path = os.path.join(self.root, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='') as stream:
            stream.write(content)
        return path

    def read(self, path):
        return self.plugin._read_file(path)

    def session(self):
        index = ClassIndex(self.cache).rebuild([self.root], self.config)
        return self.plugin._ProjectSortSession(self.window, index, self.config)

    def test_review_commit_revert_and_idempotence(self):
        a = self.write('src/demo/A.java', 'package demo;\nimport java.util.List;\nimport org.x.X;\nclass A {}\n')
        b = self.write('src/demo/B.java', 'package demo;\nimport java.util.Set;\nimport dev.ramar.json.JObject;\nclass B {}\n')
        original_a, original_b = self.read(a), self.read(b)
        session = self.session()
        session.start()
        self.assertEqual(session.scanned, 2)
        self.assertEqual(len(session.changes), 2)
        self.assertEqual(self.read(a), original_a)  # no writes before review
        self.assertEqual(self.window.dialog[1][0], 'Apply import sorting to 2 file(s)')
        self.window.dialog[2](0)  # Apply
        self.assertEqual(self.errors, [])
        self.assertIn('import org.x.X;\n\n\nimport java.util.List;', self.read(a))
        self.assertIn('import dev.ramar.json.JObject;\n\n\nimport java.util.Set;', self.read(b))
        manifest = self.plugin._batch_manifest(self.window)
        self.assertTrue(os.path.exists(manifest))
        second = self.session()
        second.start()
        self.assertEqual(len(second.changes), 0)
        self.assertIn('No imports need sorting', self.notices[-1])
        self.assertTrue(os.path.exists(manifest))  # no-op must not destroy rollback
        command = self.plugin.SmimpRevertLastBatchCommand()
        command.window = self.window
        command.run()
        self.window.dialog[2](0)
        self.assertEqual(self.read(a), original_a)
        self.assertEqual(self.read(b), original_b)
        self.assertFalse(os.path.exists(manifest))

    def test_skips_dirty_files_comments_and_generated_output(self):
        dirty = self.write('src/Dirty.java', 'import z.Z;\nimport a.A;\nclass Dirty {}\n')
        commented = self.write('src/Commented.java', 'import z.Z; // explanation\nimport a.A;\nclass C {}\n')
        eligible = self.write('src/Eligible.java', 'import z.Z;\nimport a.A;\nclass E {}\n')
        generated = self.write('build/Generated.java', 'import z.Z;\nimport a.A;\nclass G {}\n')
        self.window.opened = [FakeView(dirty, self.read(dirty), dirty=True)]
        session = self.session()
        session.start()
        self.assertEqual(session.scanned, 3)
        self.assertEqual(len(session.changes), 1)
        self.assertEqual(session.changes[0]['path'], eligible)
        self.assertEqual(len(session.skipped), 2)
        self.assertIn('comment', ''.join(session.skipped))
        self.assertEqual(self.read(generated), 'import z.Z;\nimport a.A;\nclass G {}\n')

    def test_preflight_rejects_external_changes_without_partial_write(self):
        a = self.write('src/A.java', 'import z.Z;\nimport a.A;\nclass A {}\n')
        b = self.write('src/B.java', 'import z.Z;\nimport a.A;\nclass B {}\n')
        session = self.session()
        session.start()
        original_a = self.read(a)
        self.write('src/B.java', 'import new.M;\nclass B {}\n')
        session.apply()
        self.assertEqual(self.read(a), original_a)
        self.assertIn('File changed', self.errors[-1])
        self.assertFalse(os.path.exists(self.plugin._batch_manifest(self.window)))

    def test_open_clean_buffer_uses_editor_edit_and_batch_rollback(self):
        path = self.write('src/Open.java',
                          'package demo;\nimport java.util.List;\nimport org.x.X;\nclass Open {}\n')
        original = self.read(path)
        view = FakeView(path, original)
        self.window.opened = [view]
        session = self.session()
        session.start()
        session.apply()
        self.assertIn('import org.x.X;\n\n\nimport java.util.List;', view.content)
        self.assertEqual(self.read(path), original)  # Sublime buffer remains unsaved
        command = self.plugin.SmimpRevertLastBatchCommand()
        command.window = self.window
        command.run()
        self.window.dialog[2](0)
        self.assertEqual(view.content, original)


if __name__ == '__main__':
    unittest.main()
