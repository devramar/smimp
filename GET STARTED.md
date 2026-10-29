# Getting started with the smimp codebase

This document is the fast architectural tour for someone opening the repository for the first time. It explains what owns what, how a key press becomes an import edit, and where to extend smimp without coupling it to a build system.

## The central idea

smimp separates four jobs that are easy to accidentally mix together:

```text
DISCOVER CLASSES  ->  PARSE SOURCE  ->  RESOLVE NAMES  ->  EDIT/FORMAT SOURCE
    providers          parser            resolver          java_source/import_sort
```

A provider answers **"which fully qualified classes exist?"**. It should not decide which one the user meant.

The parser answers **"which class-like names appear to need resolution?"**. It should not know whether a class came from Gradle, JRunner, a JAR glob, or project source.

The resolver answers **"given `List`, what indexed candidates are legal choices and is one preferred?"**. It consumes the unified index and settings only.

The editor layer answers **"how do we apply the chosen imports safely and format the import block?"**.

Keeping those boundaries intact is what lets smimp work for a plain folder, a JRunner project, a Gradle project, or a future discovery provider without redesigning the rest of the plugin.

## Repository map

```text
smimp.py
    Sublime Text integration. Commands, quick panels, reviews, asynchronous work,
    batch manifests, settings commands, and orchestration live here.

core/config.py
    Defaults, recursive settings merge, project-root selection and `.smimp.json` loading.

core/java_source.py
    Java package/import parsing, cursor symbol extraction, lexical fallback candidates,
    import reconciliation, stale-import replacement and conservative unused-import analysis.

core/parser.py
    Manages the JDK AST helper process and falls back to lexical parsing when unavailable.

core/resolver.py
    Maps unresolved simple names onto indexed classes, existing imports and preferred imports.

core/import_sort.py
    Implements smimp's opinionated grouping/spacing/sorting format.

core/scopes.py
    Path/root helpers used by scoped project formatting.

providers/index.py
    Unified ClassIndex plus source, JDK and configured JAR discovery/caching.

java/SmimpParser.java
    Tiny helper built with `javac` and run outside the Sublime Python host. Uses the JDK
    compiler AST API to identify class-like source references without compiling the project.

tests/
    Pure-core tests plus simulated Sublime APIs for multi-file review/commit/revert behavior.
```

## Flow: `Ctrl+I`

Suppose the source contains:

```java
List<String> names = Lists.of("A");
```

and the caret is inside `List`.

The rough flow is:

```text
Ctrl+I
  |
  v
smimp_import_at_cursor
  |
  +--> core.java_source.symbol_at(view text, caret)
  |        -> "List"
  |
  +--> ClassIndex lookup / native Sublime quick panel
  |        -> java.util.List
  |        -> java.awt.List
  |        -> ...
  |
  +--> user chooses java.util.List
  |
  +--> reconcile_imports(...)
  |        - replace a conflicting old same-simple-name import if necessary
  |        - insert the selected qualified import
  |
  +--> format_imports(...) when import_sort.on_insert = true
  |
  v
one Sublime TextCommand edit transaction
```

The entire insertion + sort is intentionally one normal editor undo step.

## Flow: `Ctrl+Shift+I`

Auto import is more involved:

```text
Ctrl+Shift+I
  |
  +--> choose mode
  |      Attempt all
  |      Only unambiguous
  |
  +--> parse active buffer
  |      JDK AST helper when available
  |      conservative lexical fallback otherwise
  |
  +--> collect candidate simple names
  |
  +--> resolver.resolve(...)
  |      existing valid explicit import?
  |      preferred import?
  |      exactly one indexed candidate?
  |      ambiguity?
  |
  +--> queue ambiguity decisions when allowed
  |
  +--> calculate additions / stale replacements / safe removals
  |
  +--> review
  |
  +--> one edit transaction
  v
normal Ctrl+Z can undo it
```

### Why stale imports need special treatment

An explicit import is not considered valid merely because its simple name matches the reference.

For example:

```java
import dev.ramar.json.JObject;

JObject obj;
```

If `dev.ramar.json.JObject` no longer exists in the current class index, smimp re-resolves `JObject`. If the new indexed class is uniquely:

```text
dev.something_else.json.JObject
```

then the review proposes replacing the old import with the new one.

This behavior is controlled by:

```json
{
  "auto_import": {
    "repair_unindexed_explicit_imports": true
  }
}
```

Disable it only when a project's real classpath intentionally contains libraries that none of smimp's providers index.

## Unused-import cleanup

Deletion is intentionally held to a higher confidence bar than addition.

smimp removes unused ordinary explicit imports only after a successful JDK AST scan. The lexical fallback is allowed to suggest additions but **never** delete imports.

The cleanup also preserves:

- static imports;
- wildcard imports;
- comment/Javadoc-associated imports;
- cases where smimp cannot safely prove the edit.

This asymmetry is deliberate: a missed cleanup is preferable to silently deleting a meaningful import.

## Class discovery providers

`providers/index.py` produces one unified index regardless of origin. A conceptual class record is:

```text
simple name:     JObject
qualified name:  dev.something_else.json.JObject
origin:          /path/to/dependency.jar
provider:        jar
```

The current providers are:

### Project sources

Scans `.java` files under Sublime project roots while honoring excluded directories such as `build`, `target`, `.gradle`, and `.git`.

### JDK

Indexes public Java/Javax/JDK classes from the installed JDK's module files.

### JAR glob

Enumerates `.class` ZIP entry names from JARs matching configured patterns. It does **not** decompress or execute classes.

JAR indexes are cached with size/mtime invalidation, so changing a dependency JAR causes its class list to be rebuilt without forcing unrelated files to be rescanned.

## Adding a new provider

A Gradle integration is the obvious example.

The provider should do one thing: discover classes/dependency artifacts and feed qualified class names into the existing index shape. It may call Gradle or understand Gradle-specific files internally if that is the provider's job.

It should **not**:

- change `core/resolver.py` to understand Gradle;
- change the parser to understand Gradle;
- make the rest of smimp depend on a Gradle installation;
- turn Gradle's notion of precedence into an automatic semantic choice for ambiguous imports.

The same principle applies to Maven, Bazel, JRunner-specific metadata, or any future source of classes.

## Preferred imports

`preferred_imports` resolves repeated ambiguity without aliases or candidate rewriting:

```json
{
  "preferred_imports": {
    "List": "java.util.List",
    "Date": "java.time.LocalDate"
  }
}
```

The value must exist in the active index. This keeps preferences honest: they select among current classes rather than inventing classes that smimp cannot see.

The ambiguity UI can save choices either globally or to the current root's `.smimp.json`.

## Import formatting model

The formatter classifies each import into one of three top-level categories:

```text
1. dependency/private/third-party
2. JDK
3. current project
```

Within a category, package relationships determine blank lines:

```java
import dev.ramar.json.JArray;
import dev.ramar.json.JToken;
import dev.ramar.json.JObject;
import dev.ramar.json.JITJObject;

import dev.ramar.structs.Field;
import dev.ramar.structs.AsyncField;


import java.nio.file.Path;


import java.util.Array;
import java.util.stream.Collectors;
```

Within an exact package, class names are sorted by character count and then alphabetically. Parent/child package branches remain adjacent; sibling branches get one blank line; unrelated namespaces/categories get two.

The formatter refuses to reorder an import block when comments or other non-whitespace text make ownership ambiguous. This is another intentional "do nothing rather than guess" rule.

## Multi-root project scopes

A Sublime project can contain unrelated roots such as:

```text
/whatever/projects/folder_one
/somewhere/else/folder_two
```

The scoped sorting UI treats each root as a navigation boundary. The folder browser can move down or up to the owning root, but it never traverses above a registered project root. "All project roots" is an explicit choice rather than the default.

`core/scopes.py` contains the path primitives; the picker/orchestration lives in `smimp.py`.

## Batch changes and rollback

Single-buffer edits use normal Sublime undo.

Cross-file operations cannot be represented by one global Ctrl+Z because Sublime undo history belongs to each buffer. smimp therefore records a batch manifest containing enough pre/post state to safely implement:

```text
smimp: Revert Last Batch
```

Before applying or reverting a batch, smimp verifies that files have not changed since the review/operation. It refuses the operation rather than partially overwriting newer work.

Clean files already open in Sublime are edited in their buffers; closed files are written atomically on disk. Dirty open buffers are skipped/refused for batch mutation.

## Configuration precedence

The base defaults are in `smimp.sublime-settings` / `core/config.py`.

Runtime configuration is effectively:

```text
defaults
   <- global Packages/User/smimp.sublime-settings
      <- owning project root's .smimp.json
```

Nested objects are recursively merged, so changing one provider option does not erase unrelated provider settings.

## Threading rule

Do not scan project trees, enumerate JARs, compile/start the parser helper, or perform other potentially slow work on Sublime's UI thread.

The existing orchestration moves expensive discovery/analysis work away from the editor thread and returns to Sublime for UI and edits. Preserve that model when extending features.

## Testing

From the directory containing `smimp/`:

```bash
python -m unittest discover -s smimp/tests -v
```

At version 0.5.0 there are regression tests for:

- symbol-at-cursor detection;
- source/JDK/JAR indexing;
- incremental JAR cache invalidation;
- package moves and stale import repair;
- preferred and ambiguous resolution;
- AST parsing and lexical fallback behavior;
- conservative unused-import removal;
- formatting hierarchy, CRLF and duplicate handling;
- single-edit insertion data;
- multi-file sort review/apply/revert;
- stale-file preflight protection;
- dirty/generated/commented-file skipping;
- multi-root scope navigation and root boundaries.

Some project/batch tests use a simulated Sublime API because normal Python test runners do not execute inside the real Sublime host. Before a release, also do a manual GUI smoke test.

## Useful extension checklist

When adding a feature, ask:

1. **Is this discovery, parsing, resolution, or editing?** Put it in the corresponding layer.
2. **Does it require knowledge of a build system?** If yes, keep that knowledge inside an optional provider/integration.
3. **Can a false positive destroy code?** If yes, require a stronger parser/review guarantee or skip the edit.
4. **Does it touch multiple files?** Use the batch preflight/manifest model rather than pretending Ctrl+Z is project-global.
5. **Can the operation block Sublime's UI?** Move the expensive work off the UI thread.
6. **Can it be expressed as a setting instead of a hardcoded personal preference?** Prefer configuration.
7. **Does an existing test fixture cover the risky behavior?** Add a regression test before changing it.

## Good first changes

For a new contributor, relatively contained improvements include:

- another optional class discovery provider;
- richer `Show Index Status` diagnostics;
- additional import-format settings while preserving the current defaults;
- better package/root status labels in quick panels;
- parser regression cases for newer Java syntax;
- performance profiling for very large class indexes.

The most important rule is simple: **smimp should know what classes are available without needing to know how the user's project is built.**
