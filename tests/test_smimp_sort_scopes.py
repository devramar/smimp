"""Scope picker and bounded folder browser regression tests."""
import os
import unittest
import types

from smimp.core.config import DEFAULTS, merge
from smimp.core.scopes import canonical, within, owning_root, child_folders
from smimp.providers.index import ClassIndex
import test_smimp_project_sort as sort_fixture

FakeWindow = sort_fixture.FakeWindow
FakeView = sort_fixture.FakeView


class MultiWindow(FakeWindow):
    def __init__(self, roots, active_file=None):
        super().__init__(roots[0])
        self.roots = list(roots)
        self.active = FakeView(active_file, '') if active_file else None

    def folders(self):
        return list(self.roots)

    def active_view(self):
        return self.active


class ScopeTests(unittest.TestCase):
    """Reuses existing Sublime test doubles and worker/UI fixtures."""
    @classmethod
    def setUpClass(cls):
        sort_fixture.ProjectSortTests.setUpClass()
        cls.plugin = sort_fixture.ProjectSortTests.plugin
        cls.plugin.sublime.QuickPanelItem = lambda **kwargs: types.SimpleNamespace(**kwargs)
        cls.plugin.sublime.load_settings = lambda filename: types.SimpleNamespace(get=lambda key: None)

    pick = sort_fixture.ProjectSortTests.pick
    write = sort_fixture.ProjectSortTests.write
    read = sort_fixture.ProjectSortTests.read

    def setUp(self):
        sort_fixture.ProjectSortTests.setUp(self)
        self.alpha = os.path.join(self.root, 'one')
        self.beta = os.path.join(self.root, 'two')
        os.makedirs(self.alpha)
        os.makedirs(self.beta)
        self.a = self.write('one/src/alpha/A.java',
                            'import java.util.List;\nimport org.x.X;\nclass A {}\n')
        self.a2 = self.write('one/src/beta/B.java',
                             'import java.util.List;\nimport org.x.X;\nclass B {}\n')
        self.b = self.write('two/src/third/C.java',
                            'import java.util.List;\nimport org.x.X;\nclass C {}\n')
        self.originals = {p: self.read(p) for p in (self.a, self.a2, self.b)}
        self.window = MultiWindow([self.alpha, self.beta], self.a)

    def assert_changed_only(self, selected):
        changed = {p for p in self.originals if self.read(p) != self.originals[p]}
        self.assertEqual(changed, set(selected))

    def select_menu(self, i):
        label, items, callback = self.window.dialog
        self.assertGreater(len(items), i)
        callback(i)

    def start_selected(self, directories, label):
        index = ClassIndex(self.cache).rebuild(self.window.folders(), self.config)
        session = self.plugin._ProjectSortSession(
            self.window, index, self.config, directories, label, self.window.folders())
        session.start()
        return session

    def test_default_current_folder_does_not_touch_other_directories(self):
        picker = self.plugin._SortScopePicker(
            self.window, lambda paths, name, root: self.start_selected(paths, name))
        picker.show()
        self.assertIn("This file's folder", self.window.dialog[1][0].trigger)
        self.select_menu(0)
        self.assertIn('alpha', self.window.dialog[0])
        self.select_menu(0)  # Review apply
        self.assert_changed_only([self.a])

    def test_this_root_and_all_roots_explicit_scopes(self):
        for selected, expected in [(1, [self.a, self.a2]), (2, [self.a, self.a2, self.b])]:
            with self.subTest(selected=selected):
                for path, original in self.originals.items():
                    self.plugin._write_atomic(path, original)
                picker = self.plugin._SortScopePicker(
                    self.window, lambda paths, name, root: self.start_selected(paths, name))
                picker.show()
                self.select_menu(selected)
                self.select_menu(0)  # Review apply
                self.assert_changed_only(expected)

    def test_browse_up_then_into_sibling_package(self):
        picker = self.plugin._SortScopePicker(
            self.window, lambda paths, name, root: self.start_selected(paths, name))
        picker.show()
        self.select_menu(3)  # Browse
        self.assertIn('Choose project root', self.window.dialog[0])
        self.select_menu(0)  # First project root, starts at active file folder
        self.assertIn('alpha', self.window.dialog[0])
        self.select_menu(1)  # Up to /src
        self.assertIn(os.path.join('one', 'src'), self.window.dialog[0])
        # first child entry will be after Sort, Up, Change root
        items = self.window.dialog[1]
        beta_index = next(i for i, entry in enumerate(items) if entry.trigger == 'beta/')
        self.select_menu(beta_index)
        self.assertIn('beta', self.window.dialog[0])
        self.select_menu(0)  # Sort here
        self.select_menu(0)  # Apply
        self.assert_changed_only([self.a2])

    def test_browse_other_root_and_never_above_it(self):
        picker = self.plugin._SortScopePicker(
            self.window, lambda paths, name, root: self.start_selected(paths, name))
        picker.show()
        self.select_menu(3)
        self.select_menu(1)  # Other root
        self.assertIn(self.beta, self.window.dialog[0])
        self.assertFalse(any('Up one folder' in item.trigger for item in self.window.dialog[1]))
        self.select_menu(0)
        self.select_menu(0)
        self.assert_changed_only([self.b])

    def test_cancel_and_project_root_change_prevents_writes(self):
        picker = self.plugin._SortScopePicker(self.window,
            lambda paths, name, root: self.start_selected(paths, name))
        picker.show()
        self.select_menu(-1)
        self.assertTrue(all(self.read(p) == v for p, v in self.originals.items()))
        session = self.start_selected([self.alpha], self.alpha)
        self.window.roots = [self.beta]
        session.apply()
        self.assertIn('Project folders changed', self.errors[-1])
        self.assert_changed_only([])

    def test_safety_and_directory_scopes(self):
        self.assertTrue(within(os.path.join(self.alpha, 'src'), self.alpha))
        self.assertFalse(within(self.alpha + '_other', self.alpha))
        self.assertEqual(owning_root([self.alpha, self.beta], self.a), canonical(self.alpha))
        self.assertFalse(within(self.root, self.alpha))
        outside_link = os.path.join(self.alpha, 'outside')
        try:
            os.symlink(self.beta, outside_link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass
        self.assertNotIn(outside_link, child_folders(self.alpha, self.alpha))
        self.assertEqual(len(child_folders(self.alpha, self.alpha, excluded={'src'})), 0)


if __name__ == '__main__':
    unittest.main()
