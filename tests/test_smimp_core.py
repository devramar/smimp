import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from smimp.core.config import DEFAULTS, merge
from smimp.core.java_source import (add_imports, declarations, fallback_candidates, imports, package_name,
                                    symbol_at, reconcile_imports, unused_explicit_imports)
from smimp.core.import_sort import format_imports
from smimp.core.parser import JavaParser
from smimp.core.resolver import resolve
from smimp.providers.index import ClassIndex, jar_paths


class CoreTests(unittest.TestCase):
    def test_scope_and_comments(self):
        text = '/* package fake; class Fake {} */\npackage real.thing;\n// import fake.List;\nclass MyClass { class Nested {} }\ninterface Extra {}\n'
        self.assertEqual(package_name(text), 'real.thing')
        self.assertEqual(list(declarations(text)), ['MyClass', 'Extra'])
        self.assertEqual(imports(text), [])

    def test_cursor(self):
        text = 'List<String> entries = Lists.of("");'
        self.assertEqual(symbol_at(text, text.index('List') + 2), 'List')
        self.assertEqual(symbol_at(text, text.index('Lists') + 3), 'Lists')

    def test_single_undoable_insertion_data(self):
        text = 'package demo;\n\npublic class X {}\n'
        updated, inserted = add_imports(text, ['java.util.List', 'java.util.List', 'java.lang.String'])
        self.assertEqual(inserted, ['java.util.List'])
        self.assertEqual(updated, 'package demo;\n\nimport java.util.List;\n\npublic class X {}\n')
        self.assertEqual(add_imports(updated, ['java.util.List'])[0], updated)

    def test_keep_existing_order_and_crlf(self):
        text = 'package foo;\r\n\r\nimport z.Z;\r\nimport a.A;\r\n\r\nclass C {}'
        updated, added = add_imports(text, ['java.util.List'])
        self.assertIn('import z.Z;\r\nimport a.A;\r\nimport java.util.List;\r\n', updated)
        self.assertEqual(added, ['java.util.List'])

    def test_ambiguous_preferred_and_wildcards(self):
        text = 'package demo;\nclass Demo { List<String> values; }'
        classes = {'List': ['java.awt.List', 'java.util.List'], 'String': ['java.lang.String']}
        r, ambiguous, unknown = resolve(text, {'List', 'String'}, classes, {})
        self.assertEqual(ambiguous['List'], ['java.awt.List', 'java.util.List'])
        self.assertEqual(r, {})
        self.assertEqual(unknown, set())
        r, ambiguous, unknown = resolve(text, {'List', 'String'}, classes, {'List': 'java.util.List'})
        self.assertEqual(r, {'List': 'java.util.List'})
        self.assertEqual(ambiguous, {})
        r, ambig, unk = resolve('package demo;\nimport java.util.*;\nclass Demo { List<String> v; }',
                                {'List'}, classes, {})
        self.assertEqual(r, {})
        self.assertEqual(ambig, {})


    def test_stale_explicit_import_is_resolved_to_current_index(self):
        text = ('package demo;\n\n'
                'import dev.ramar.json.JObject;\n\n'
                'class Demo { JObject value; }\n')
        classes = {'JObject': ['dev.something_else.json.JObject']}
        resolved, ambiguous, unknown = resolve(text, {'JObject'}, classes, {})
        self.assertEqual(resolved, {'JObject': 'dev.something_else.json.JObject'})
        self.assertEqual(ambiguous, {})
        self.assertEqual(unknown, set())

        updated, added, removed, skipped = reconcile_imports(text, list(resolved.values()))
        self.assertEqual(added, ['dev.something_else.json.JObject'])
        self.assertEqual(removed, ['dev.ramar.json.JObject'])
        self.assertEqual(skipped, [])
        self.assertIn('import dev.something_else.json.JObject;', updated)
        self.assertNotIn('import dev.ramar.json.JObject;', updated)

    def test_valid_explicit_import_still_satisfies_symbol(self):
        text = 'import dev.ramar.json.JObject;\nclass Demo { JObject value; }\n'
        classes = {'JObject': ['dev.ramar.json.JObject', 'dev.other.JObject']}
        resolved, ambiguous, unknown = resolve(text, {'JObject'}, classes, {})
        self.assertEqual((resolved, ambiguous, unknown), ({}, {}, set()))

    def test_unindexed_explicit_repair_can_be_disabled(self):
        text = 'import vendor.custom.List;\nclass Demo { List value; }\n'
        classes = {'List': ['java.util.List']}
        resolved, ambiguous, unknown = resolve(
            text, {'List'}, classes, {}, repair_unindexed_explicit=False)
        self.assertEqual((resolved, ambiguous, unknown), ({}, {}, set()))

    def test_picker_selection_replaces_same_simple_import(self):
        text = ('import java.awt.List;\n\n'
                'class Demo { List value; }\n')
        updated, added, removed, skipped = reconcile_imports(text, ['java.util.List'])
        self.assertEqual(added, ['java.util.List'])
        self.assertEqual(removed, ['java.awt.List'])
        self.assertEqual(skipped, [])
        self.assertIn('import java.util.List;', updated)
        self.assertNotIn('import java.awt.List;', updated)

    def test_unused_explicit_import_detection_is_conservative(self):
        text = ('import java.util.List;\n'
                'import java.util.Map;\n'
                'import java.util.*;\n'
                'import static java.util.Collections.emptyList;\n'
                'class Demo { List<String> values; }\n')
        self.assertEqual(unused_explicit_imports(text, {'List', 'String'}), ['java.util.Map'])
        updated, added, removed, skipped = reconcile_imports(
            text, [], unused_explicit_imports(text, {'List', 'String'}))
        self.assertEqual(added, [])
        self.assertEqual(removed, ['java.util.Map'])
        self.assertEqual(skipped, [])
        self.assertNotIn('import java.util.Map;', updated)
        self.assertIn('import java.util.*;', updated)
        self.assertIn('import static java.util.Collections.emptyList;', updated)

        docs_only = ('import com.example.Widget;\n'
                     '/** See {@code Widget} for details. */\n'
                     'class Demo {}\n')
        self.assertEqual(unused_explicit_imports(docs_only, set()), [])

        commented = ('import java.util.List;\n'
                     '// kept because this may describe Map\n'
                     'import java.util.Map;\n'
                     'class Demo { List<String> values; }\n')
        updated, _added, removed, skipped = reconcile_imports(commented, [], ['java.util.Map'])
        self.assertEqual(removed, [])
        self.assertEqual(skipped, ['java.util.Map'])
        self.assertIn('import java.util.Map;', updated)

    def test_glob_index_and_incremental_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'module', 'env', 'nested'), exist_ok=True)
            jar = os.path.join(tmp, 'module', 'env', 'nested', 'lib.jar')
            with zipfile.ZipFile(jar, 'w') as f:
                f.writestr('com/google/common/collect/Lists.class', b'')
                f.writestr('com/google/common/collect/Lists$Inner.class', b'')
            source = os.path.join(tmp, 'Example.java')
            with open(source, 'w') as f: f.write('package demo;\npublic class Example {}')
            config = merge(DEFAULTS, {'providers': {'jdk': {'enabled': False}, 'jar_glob': {'enabled': True}}})
            self.assertEqual(jar_paths([tmp], ['**/env/**/*.jar']), [jar])
            cache = os.path.join(tmp, '.smimp', 'index.gz')
            first = ClassIndex(cache).rebuild([tmp], config)
            self.assertEqual(first.by_name['Lists'], ['com.google.common.collect.Lists'])
            self.assertEqual(first.by_name['Example'], ['demo.Example'])
            again = ClassIndex(cache).rebuild([tmp], config)
            self.assertEqual(again.stats['rescanned'], 0)

    def test_external_jar_package_move_reindexes_and_repairs_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.path.join(tmp, 'env')
            os.makedirs(env)
            jar = os.path.join(env, 'library.jar')
            with zipfile.ZipFile(jar, 'w') as f:
                f.writestr('dev/ramar/json/JObject.class', b'old')
            config = merge(DEFAULTS, {
                'providers': {'jdk': {'enabled': False}, 'jar_glob': {'enabled': True, 'patterns': ['env/*.jar']}}
            })
            cache = os.path.join(tmp, '.smimp', 'index.gz')
            first = ClassIndex(cache).rebuild([tmp], config)
            self.assertEqual(first.by_name['JObject'], ['dev.ramar.json.JObject'])

            # Rewrite the same dependency artifact as a package-move update.
            with zipfile.ZipFile(jar, 'w') as f:
                f.writestr('dev/something_else/json/JObject.class', b'new-package')
            second = ClassIndex(cache).rebuild([tmp], config, force=True)
            self.assertEqual(second.by_name['JObject'], ['dev.something_else.json.JObject'])

            source = ('import dev.ramar.json.JObject;\n'
                      'class Demo { JObject value; }\n')
            resolved, ambiguous, unknown = resolve(source, {'JObject'}, second.by_name, {})
            self.assertEqual(resolved, {'JObject': 'dev.something_else.json.JObject'})
            updated, added, removed, skipped = reconcile_imports(source, resolved.values())
            self.assertEqual((added, removed, skipped),
                             (['dev.something_else.json.JObject'], ['dev.ramar.json.JObject'], []))
            self.assertIn('import dev.something_else.json.JObject;', updated)
            self.assertNotIn('import dev.ramar.json.JObject;', updated)

    def test_import_sort_requested_hierarchy(self):
        text = ("package project;\n\n"
                "import java.util.stream.Collectors;\n"
                "import dev.ramar.structs.AsyncField;\n"
                "import dev.ramar.json.JITJObject;\n"
                "import java.util.Array;\n"
                "import dev.ramar.json.JObject;\n"
                "import dev.ramar.structs.Field;\n"
                "import dev.ramar.json.JToken;\n"
                "import java.nio.file.Path;\n"
                "import dev.ramar.json.JArray;\n"
                "\nclass X {}\n")
        expected = ("package project;\n\n"
                    "import dev.ramar.json.JArray;\n"
                    "import dev.ramar.json.JToken;\n"
                    "import dev.ramar.json.JObject;\n"
                    "import dev.ramar.json.JITJObject;\n\n"
                    "import dev.ramar.structs.Field;\n"
                    "import dev.ramar.structs.AsyncField;\n\n\n"
                    "import java.nio.file.Path;\n\n"
                    "import java.util.Array;\n"
                    "import java.util.stream.Collectors;\n\n"
                    "class X {}\n")
        result, warning = format_imports(text)
        self.assertIsNone(warning)
        self.assertEqual(result, expected)
        self.assertEqual(format_imports(result)[0], result)

    def test_import_sort_project_last(self):
        text = ('import com.example.app.Model;\nimport java.util.List;\n'
                'import org.joda.time.DateTime;\nimport com.example.app.Helper;\n'
                'class Thing {}\n')
        result, _ = format_imports(text, project_names=['com.example.app.Helper', 'com.example.app.Model'])
        self.assertEqual(result, ('import org.joda.time.DateTime;\n\n\n'
                                  'import java.util.List;\n\n\n'
                                  'import com.example.app.Model;\n'
                                  'import com.example.app.Helper;\n'
                                  'class Thing {}\n'))

    def test_import_sort_safety_comments_static_crlf_and_duplicates(self):
        text = ('package p;\r\n\r\nimport static java.util.Collections.emptyList;\r\n'
                'import org.x.LongName;\r\nimport org.x.A;\r\n'
                'import org.x.A;\r\n\r\nclass X {}')
        sorted_text, warning = format_imports(text)
        self.assertIsNone(warning)
        self.assertIn('import org.x.A;\r\nimport org.x.LongName;', sorted_text)
        self.assertEqual(sorted_text.count('import org.x.A;'), 1)
        self.assertIn('\r\n\r\n\r\nimport static java.util.Collections.emptyList;', sorted_text)
        self.assertNotIn('\n', sorted_text.replace('\r\n', ''))

        for text in ('import z.Z; // attached\nimport a.A;\nclass C {}',
                     'import z.Z;\n// explain the next import\nimport a.A;\nclass C {}',
                     'import z.Z;\nimport a.A; /* attached */\nclass C {}'):
            self.assertEqual(format_imports(text)[0], text)
            self.assertIsNotNone(format_imports(text)[1])

    def test_sort_after_add_imports_and_with_parent_child_packages(self):
        text = 'package a;\n\nimport java.util.stream.Collectors;\n\nclass X {}'
        updated, added = add_imports(text, ['java.util.List'])
        self.assertEqual(added, ['java.util.List'])
        formatted, warning = format_imports(updated)
        self.assertIsNone(warning)
        self.assertIn('import java.util.List;\nimport java.util.stream.Collectors;', formatted)

    def test_ast_parser(self):
        with tempfile.TemporaryDirectory() as tmp:
            parser = JavaParser(os.path.join(tmp, 'cache'),
                os.path.join(os.path.dirname(__file__), '..', 'java', 'SmimpParser.java'))
            text = '''package demo;
                class App {
                    List<String> entries = Lists.of("");
                    @Nullable ObjectMapper mapper;
                    JsonNode parse(String v) { return mapper.readTree(v); }
                }
            '''
            candidates, reliable = parser.analyze(text)
            parser.close()
            self.assertTrue(reliable)
            self.assertTrue({'List', 'Lists', 'Nullable', 'ObjectMapper', 'JsonNode'}.issubset(candidates), candidates)


if __name__ == '__main__': unittest.main()
