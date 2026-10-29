# smimp

**smimp** is a Java import picker, auto-importer, stale-import repairer, and opinionated import formatter for **Sublime Text 4**.

It is intentionally **build-system agnostic**. The core does not know how [JRunner](https://github.com/devramar/jrunner), Gradle, Maven, or another build system compiles a project. Instead, independent discovery providers contribute classes to a shared index. Project source discovery and JDK discovery work out of the box; JAR discovery is optional and configured with globs.

Current repository version: **0.5.0**.

## What it does

- **`Ctrl+I` — import at cursor.** Put the caret inside `List`, `JObject`, `Lists`, etc. and smimp opens a native fuzzy picker prefiltered to that symbol.
- **`Ctrl+Shift+I` — auto-import the current Java file.** Choose **Attempt all** or **Only unambiguous**, resolve ambiguities through a picker, review the result, then apply it as one normal undoable Sublime edit.
- **Repairs moved classes.** If `dev.ramar.json.JObject` disappears and the indexed class is now `dev.something_else.json.JObject`, smimp treats the old explicit import as stale and resolves `JObject` again.
- **Removes dead ordinary imports conservatively.** Unused explicit imports are removed only when the JDK AST scan succeeds. Static/wildcard imports and comment-attached imports are left alone.
- **Preferred imports.** Teach smimp that `List` means `java.util.List`, globally or per project.
- **Optional JAR indexing.** Point a provider at resolved dependency JARs without teaching the core anything about your build system.
- **Import formatting.** Sort one file, a folder subtree, one Sublime project root, or every project root using smimp's package grouping rules.
- **Batch safety.** Multi-file operations preview before writing, refuse stale/dirty files, and can be reverted with `smimp: Revert Last Batch`.

## Quick start

1. Read [INSTALL.md](INSTALL.md) and install the repository as `Packages/smimp`.
2. Ensure a **JDK 11+** is available (`java` and `javac`), or configure their paths in smimp settings.
3. Open a Java project in Sublime Text.
4. Put the caret in a class name and press **Ctrl+I**.
5. Press **Ctrl+Shift+I** to auto-import the whole active file.
6. Open the Command Palette and search for **`smimp:`** to see the full command set.

If you want the architecture and extension points rather than just usage, start with [GET STARTED.md](GET%20STARTED.md).

## Main commands

| Command | Purpose |
| --- | --- |
| `smimp: Import Class at Cursor` | Fuzzy import picker seeded with the symbol under the caret. |
| `smimp: Auto Import File` | Resolve missing imports, repair stale imports, and optionally remove unused imports. |
| `smimp: Sort Imports in File` | Apply only the import formatter to the active file. |
| `smimp: Sort Imports in Current Project (Choose Scope)` | Pick current folder/root/all roots/browsed subtree, preview, then format matching Java files. |
| `smimp: Import Classes in Project` | Auto-import Java files across the current Sublime project. |
| `smimp: Import Classes in Package` | Auto-import only a package and its subpackages. |
| `smimp: Add Preferred Import` | Add a deterministic resolution rule. |
| `smimp: Open Project Settings` | Open/create the current root's `.smimp.json`. |
| `smimp: Open Global Settings` | Open `Packages/User/smimp.sublime-settings`. |
| `smimp: Rebuild Class Index` | Force all enabled providers to rescan. |
| `smimp: Show Index Status` | Display indexed type/provider totals. |
| `smimp: Resume Import Review` | Return to a pending review after opening its preview. |
| `smimp: Revert Last Batch` | Safely restore the most recent multi-file batch. |

The default key bindings apply only when Sublime reports the active syntax as `source.java`.

## Configuration

Global settings live in:

```text
Packages/User/smimp.sublime-settings
```

Per-project-root settings live in:

```text
<project-root>/.smimp.json
```

Project settings recursively override global settings. A representative configuration is:

```json
{
  "providers": {
    "sources": {
      "enabled": true
    },
    "jdk": {
      "enabled": true
    },
    "jar_glob": {
      "enabled": true,
      "patterns": ["**/env/**/*.jar", "libs/**/*.jar"]
    }
  },
  "preferred_imports": {
    "List": "java.util.List",
    "Date": "java.time.LocalDate"
  },
  "auto_import": {
    "repair_unindexed_explicit_imports": true,
    "remove_unused_explicit_imports": true
  },
  "import_sort": {
    "on_insert": true,
    "project_package_prefixes": []
  },
  "java_executable": "java",
  "javac_executable": "javac",
  "parser": "javac",
  "max_batch_files": 5000
}
```

### Optional JAR provider

The JAR provider is disabled by default. It only knows about the patterns you give it:

```json
{
  "providers": {
    "jar_glob": {
      "enabled": true,
      "patterns": ["**/env/**/*.jar"]
    }
  }
}
```

That pattern is useful for JRunner-style projects, but it is **not** assumed anywhere else in smimp. A Gradle project can instead point at whichever directory contains its resolved JARs, and a future Gradle provider can be added without changing the resolver.

## Preferred imports

Ambiguous classes are never guessed just because one candidate looks familiar. A preferred import turns a repeated decision into a deterministic rule:

```json
{
  "preferred_imports": {
    "List": "java.util.List"
  }
}
```

The preferred fully qualified class must exist in the current index. Ambiguity dialogs can save a choice globally or into the current project automatically.

## Import formatting

smimp's formatter groups imports in this order:

1. non-project/private or third-party packages;
2. JDK packages (`java`, `javax`, `jdk`);
3. classes belonging to the current project.

Within an exact package, classes are sorted by **class-name character length**, then alphabetically for ties. Parent/child package branches stay together; sibling branches get one blank line; unrelated namespaces/categories get two. Static imports are sorted separately after ordinary imports.

Project membership is normally derived from indexed source classes. Extra project prefixes can be declared when generated/unindexed classes need to be treated as local:

```json
{
  "import_sort": {
    "project_package_prefixes": ["com.example.app"]
  }
}
```

## Parser model

smimp ships `java/SmimpParser.java`. At runtime it compiles this helper into Sublime's cache and keeps a small Java process available to parse buffers using the JDK compiler AST API. It **does not compile the user's project**, execute Gradle/Maven/JRunner, or require smimp to reconstruct a build classpath.

If the AST helper is unavailable, smimp falls back to a conservative lexical scanner. The fallback can still suggest imports, but it will not perform deletion-oriented cleanup such as unused-import removal.

## Development

Run the core test suite from the directory **containing** the repository folder:

```bash
python -m unittest discover -s smimp/tests -v
```

The tests cover indexing, JAR invalidation, stale import repair, parser behavior, preferred imports, formatting, scope selection, project batch application, and rollback.

Repository layout:

```text
smimp/
├── smimp.py                  # Sublime commands, UI and orchestration
├── core/                     # parsing glue, resolution, source editing, sorting, scopes
├── providers/                # project/JDK/JAR class discovery and index cache
├── java/SmimpParser.java     # JDK AST helper
├── tests/                    # core and simulated-Sublime regression tests
├── *.sublime-*               # commands, keymaps and default settings
├── README.md
├── INSTALL.md
├── GET STARTED.md
└── CHANGELOG.md
```

See [GET STARTED.md](GET%20STARTED.md) for a deeper tour of the request flow and extension points.

## Current limitations

smimp is intentionally not a full Java language server or symbol solver. Visibility rules, module exports, wildcard/static shadowing, multi-release JAR subtleties, locally shadowed uppercase identifiers, and heavily broken/incomplete Java may require manual selection. Large classpaths are also ultimately displayed through Sublime's native quick panel, so enormous indexes can make picker filtering less immediate.

This repository does not currently declare an open-source license. Choose and add one before publishing it as reusable licensed software.
