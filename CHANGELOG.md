# Changelog

## 0.5.0

- Repair stale explicit imports when an indexed class moves to a new package.
- Make explicit `Ctrl+I` selections replace an older same-simple-name import instead of creating a conflict.
- Conservatively remove unused ordinary explicit imports after a successful JDK AST parse.
- Preserve static imports, wildcard imports, and comment-associated imports during cleanup.
- Add `auto_import.repair_unindexed_explicit_imports` and `auto_import.remove_unused_explicit_imports` settings.
- Add regression coverage for dependency JAR package moves and index refresh behavior.

## 0.4.0

- Add scope selection before project-wide import sorting.
- Support active file folder, owning Sublime root, all project roots, and a root-bounded folder browser.
- Prevent directory navigation above configured Sublime project roots.
- Add multi-root scope and safety regression coverage.

## 0.3.0

- Add project-wide import sorting with preview and batch rollback.
- Skip dirty buffers and unsafe/comment-attached import blocks.
- Add stale-file preflight checks before multi-file writes.

## 0.2.0

- Add smimp's opinionated import formatter.
- Sort dependencies/private packages first, JDK second, project classes last.
- Add package hierarchy spacing and class-name-length ordering.
- Sort automatically after import insertion by default.
- Add `smimp: Sort Imports in File`.

## 0.1.0

- Initial smimp release.
- Cursor-aware fuzzy import picker (`Ctrl+I`).
- Automatic current-file imports (`Ctrl+Shift+I`) with ambiguous/unambiguous modes and review.
- Preferred import decisions.
- Project source, JDK and optional JAR-glob class discovery.
- JDK compiler AST helper with lexical fallback.
- Project/package batch import commands and manifest-based rollback.
