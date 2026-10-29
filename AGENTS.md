# AGENTS.md

This file is the working guide for coding agents contributing to **smimp**.

smimp is a Sublime Text 4 plugin for Java import discovery, resolution, repair, cleanup, and formatting. The project deliberately stays lightweight and build-system agnostic. Changes should preserve that property unless the repository documentation explicitly establishes a new architectural direction.

## Before you change anything

Read these repository documents first:

1. `README.md` — user-facing behavior, configuration, commands, and current feature set.
2. `GET STARTED.md` — architecture, request flows, extension points, and design rationale.
3. `INSTALL.md` — supported installation and runtime assumptions.
4. `CHANGELOG.md` — existing behavior and version history.
5. **Everything relevant in `docs/`.**

### `docs/` is required reading for contributors

The `docs/` directory contains contribution rules, architectural notes, conventions, decisions, and other project-specific guidance that may be newer or more specific than this file.

**Before implementing, refactoring, reviewing, or proposing a change, inspect `docs/` and read every document relevant to the work.** If guidance in `docs/` is more specific than general guidance in this file, follow the more specific repository guidance. Do not assume an established behavior is accidental before checking whether it is documented there.

When adding a feature that establishes a new convention, architecture rule, provider contract, user-visible behavior, or maintenance requirement, update the appropriate documentation in `docs/` as part of the same change when applicable.

## Core design rule

Keep these responsibilities separate:

```text
DISCOVER CLASSES  ->  PARSE SOURCE  ->  RESOLVE NAMES  ->  EDIT / FORMAT SOURCE
    providers          parser            resolver             editor layer
```

In practical terms:

- **Providers** discover classes. They may understand a build system, filesystem layout, JAR source, or other dependency mechanism.
- **Parser code** identifies class-like references and source structure. It must not care where classes came from.
- **Resolver code** chooses among indexed candidates and preferences. It must not become Gradle-, Maven-, JRunner-, or filesystem-layout-aware.
- **Editor/formatter code** applies source changes safely. It should not discover dependencies or make semantic classpath decisions.

A new Gradle integration, for example, belongs behind a provider boundary. Do not teach the core resolver how Gradle works.

## Build-system agnosticism

The core must not assume that Java projects use:

- JRunner;
- Gradle;
- Maven;
- a particular `env/`, `lib/`, `build/`, or dependency directory;
- a specific compiler invocation;
- a fully reconstructed project classpath.

Optional providers may make those assumptions inside their own implementation when explicitly configured.

The existing JAR glob provider is an example: `**/env/**/*.jar` can be useful for JRunner projects, but that convention must remain optional configuration rather than core behavior.

## Correctness philosophy

smimp is allowed to be helpful when adding imports, but it must be conservative when deleting or rewriting code.

Prefer:

- asking the user when import resolution is genuinely ambiguous;
- preserving an uncertain import rather than deleting it;
- skipping a file rather than applying a stale multi-file edit;
- failing one provider without disabling unrelated providers;
- leaving source unchanged when analysis confidence is insufficient.

Do not silently guess an ambiguous class merely because one candidate is common. Use `preferred_imports` for deterministic user-approved choices.

### Stale imports

An explicit import is valid only if the corresponding qualified class is still known to smimp when stale-import repair is enabled. A matching simple name alone is not enough.

Example:

```java
import dev.ramar.json.JObject;

JObject object;
```

If `dev.ramar.json.JObject` disappears and `dev.something_else.json.JObject` is now the unique indexed candidate, auto-import may propose replacement of the stale import.

If the index may intentionally be incomplete, respect the `repair_unindexed_explicit_imports` setting.

### Dead imports

Deletion has a higher confidence requirement than insertion.

Do not broaden dead-import removal so that the lexical fallback deletes imports. Existing intent is:

- successful JDK AST analysis may support conservative unused-import cleanup;
- lexical fallback may suggest/add imports but must not delete based on uncertain analysis;
- static imports, wildcard imports, and comment-associated imports should be preserved unless a future documented design explicitly handles them safely.

## Sublime Text constraints

Sublime's UI thread must stay responsive.

Potentially expensive work such as:

- scanning source trees;
- indexing JARs;
- rebuilding JDK indexes;
- parsing Java;
- performing project-wide analysis;

should run asynchronously where the existing architecture expects asynchronous work.

Source modifications must ultimately happen through Sublime-safe edit commands.

### Undo behavior

For a single active file, smimp aims to make one logical operation one normal Sublime undo step. Import insertion, replacement, cleanup, and formatting performed as part of the same action should not unexpectedly require a long sequence of `Ctrl+Z` presses.

For multi-file operations, preserve the batch safety model and `smimp: Revert Last Batch` behavior rather than pretending Sublime has a global cross-buffer undo stack.

### Dirty and stale files

Multi-file operations must not blindly overwrite files that changed after analysis/review. Preserve or strengthen existing dirty-buffer, fingerprint, and stale-state checks.

## Import resolution behavior

`preferred_imports` is the primary mechanism for persistent ambiguity decisions:

```json
{
  "preferred_imports": {
    "List": "java.util.List"
  }
}
```

Do not add parallel alias/remapping concepts unless there is a clear use case that cannot be represented cleanly by preferred imports.

A preferred import should select a class that actually exists in the active index. Preferences should not manufacture unresolved classes.

## Import formatter behavior

The formatter is intentionally opinionated. Current top-level ordering is:

1. dependency/private/third-party imports;
2. JDK imports (`java`, `javax`, `jdk`);
3. current-project imports.

Within package groups, preserve the documented package grouping, blank-line behavior, and class-name length ordering unless a change explicitly updates the formatting specification.

Project membership should continue to come from indexed project source classes plus explicit configuration such as `project_package_prefixes`, not from hardcoded package names.

Be careful with comments around import blocks. If moving an import could detach or misassociate a comment, prefer not to reorder/delete it unless comment ownership is known.

## Project roots and scopes

A Sublime project may contain multiple unrelated root folders. Treat each root as a real boundary.

For scoped operations:

- the active file's containing project root can be detected and used as a scope;
- folder navigation must not escape above a configured Sublime project root;
- "all project roots" must remain an explicit broad scope;
- do not unexpectedly turn a local/folder action into a whole-project action.

When adding new batch commands, make the affected scope obvious before files are modified.

## Providers and indexing

Provider failures should be isolated where possible. One unavailable optional source of classes should not make ordinary project-source imports unusable.

For JAR indexing:

- enumerate archive entries rather than extracting entire JARs;
- continue using efficient cache invalidation based on file identity/mtime/size or a stronger documented mechanism;
- exclude anonymous/synthetic/non-importable class entries where practical;
- avoid executing dependency code.

If adding a provider, normalize its output into the same unified class-index representation consumed by the resolver.

## Java parser helper

`java/SmimpParser.java` exists to use the JDK compiler AST API without making smimp compile or execute the user's project.

Changes to the helper should preserve these properties:

- it analyzes source supplied by smimp;
- it does not run the project's build;
- it does not execute user code;
- it does not require the core to know how the project compiler is configured;
- failure should degrade toward the conservative fallback rather than corrupt source.

Keep protocol changes between Python and the Java helper explicit and tested on both sides.

## Configuration compatibility

Global settings live in:

```text
Packages/User/smimp.sublime-settings
```

Project-root settings live in:

```text
<project-root>/.smimp.json
```

When adding settings:

- provide a safe default;
- preserve existing configurations;
- document the setting in the appropriate user-facing docs;
- prefer additive configuration over breaking renames;
- merge project settings consistently with the existing recursive override behavior.

## Command and UI conventions

User-facing commands should use the `smimp:` prefix in the Command Palette.

Prefer native Sublime interactions such as quick panels and input handlers over custom UI where practical.

For automatic actions:

- show review/confirmation when the operation is broad or may rewrite multiple imports/files;
- expose ambiguities instead of hiding them;
- keep the default choice safe and unsurprising;
- retain a straightforward manual path (`Ctrl+I`) when automation cannot decide confidently.

## Testing requirements

Run the full test suite for every behavioral change:

```bash
python -m unittest discover -s smimp/tests -v
```

Run it from the directory containing the `smimp/` repository folder, matching the documented repository setup.

Add regression tests for bug fixes. A bug is not considered fully fixed if the exact failure mode is not represented by a test when it is reasonably testable.

Relevant existing coverage includes:

- source/JDK/JAR indexing;
- JAR cache invalidation;
- cursor symbol detection;
- parser and lexical fallback behavior;
- preferred imports;
- stale-import repair;
- conservative dead-import cleanup;
- import formatting;
- multi-root scope selection;
- project-wide review/application;
- stale-file rejection;
- batch rollback.

If a change touches Sublime integration that cannot be exercised in the pure-core suite, add or extend simulated-Sublime tests where possible and clearly note any remaining live-GUI validation requirement.

## Documentation expectations

Update documentation when user-visible behavior changes. At minimum consider:

- `README.md` for public features/settings/commands;
- `INSTALL.md` for installation/runtime/dependency changes;
- `GET STARTED.md` for architecture or contributor-facing implementation changes;
- `CHANGELOG.md` for release-visible changes;
- `docs/` for project contribution rules, architecture decisions, or focused technical guidance.

Do not leave a substantial feature discoverable only by reading source code.

## Repository hygiene

Do not commit:

- generated Python bytecode;
- Sublime caches;
- generated Java helper class files;
- local environment/editor state;
- test scratch data;
- dependency JARs unless the repository explicitly adopts them as fixtures.

Do not invent or change the project's software license without an explicit maintainer decision.

Avoid introducing dependencies when the standard library or existing architecture can solve the problem cleanly. smimp should remain easy to install as a Sublime package.

## Change discipline

Before editing code:

1. identify which architectural layer owns the change;
2. inspect relevant code and tests;
3. read relevant `docs/` guidance;
4. preserve public behavior that is unrelated to the task;
5. implement the smallest coherent change;
6. add regression coverage;
7. run the full suite;
8. update documentation when behavior/configuration/architecture changes.

Do not perform broad refactors merely because a file could be organized differently. Refactor when it materially improves the requested change, correctness, maintainability, or a documented project direction.

## Useful starting points

For most work, begin here:

- `smimp.py` — Sublime commands, UI, async orchestration, reviews, batch application and rollback.
- `core/java_source.py` — Java import/source analysis and reconciliation.
- `core/resolver.py` — candidate resolution and preferences.
- `core/import_sort.py` — formatting rules.
- `core/parser.py` + `java/SmimpParser.java` — AST helper lifecycle/protocol.
- `providers/index.py` — class discovery and cache behavior.
- `core/scopes.py` — project-root and folder scope logic.
- `tests/` — executable specification for existing behavior.

When uncertain about intended behavior, prefer the combination of current tests, repository documentation, and explicit maintainer instructions over assumptions.
