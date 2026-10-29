"""Safe, project-agnostic import sorting for Java source buffers.

Only import statements and whitespace between them may be reorganized. Comments
or other text inside the import range prevent sorting rather than being moved.
"""
import re
from .java_source import IMP, masked

_JDK_PREFIXES = ('java.', 'javax.', 'jdk.')


def import_names(text):
    """Return fully qualified names currently imported by a Java file."""
    return [(match.group(2), bool(match.group(1))) for match in IMP.finditer(masked(text))]


def _package(qualified, is_static):
    if qualified.endswith('.*'):
        # For static on-demand imports, the owner type precedes the .*.
        return qualified[:-2] if is_static else qualified[:-2]
    if is_static:
        # Static method/field/class import: the type owner is before last dot.
        return qualified.rsplit('.', 1)[0]
    return qualified.rsplit('.', 1)[0] if '.' in qualified else ''


def _category(name, project_names, project_prefixes):
    # Index-based source classification wins, including static members and wildcards.
    if name in project_names or any(name.startswith(p + '.') for p in project_names):
        return 2
    if any(name == prefix or name.startswith(prefix + '.') for prefix in project_prefixes):
        return 2
    if name.startswith(_JDK_PREFIXES):
        return 1
    return 0


def _blank_count(previous, following):
    """Number of *empty lines* between two imports within one category."""
    old = previous.split('.') if previous else []
    new = following.split('.') if following else []
    shared = 0
    for a, b in zip(old, new):
        if a != b:
            break
        shared += 1
    if shared == min(len(old), len(new)):
        return 0  # same package or parent/child packages
    return 1 if shared else 2  # sibling namespace vs unrelated namespace


def _sort_key(item):
    # Arrange package paths alphabetically, and simple class names within each
    # exact package by character length then case-insensitive alphabetical order.
    name, static = item
    package = _package(name, static)
    simple = name.rsplit('.', 1)[-1]
    return (package.lower(), len(simple), simple.casefold(), name)


def format_imports(text, project_names=(), project_prefixes=()):
    """Return (formatted_text, warning). Warning is set if no safe rewrite exists.

    The import section is rewritten in a single contiguous edit, leaving header,
    package statement and body byte-identical. CRLF is preserved.
    """
    clean = masked(text)
    matches = list(IMP.finditer(clean))
    if not matches:
        return text, None

    # IMP is anchored at line starts; do not move import-attached comments.
    start, end = matches[0].start(), matches[-1].end()
    pointer = start
    for match in matches:
        if text[pointer:match.start()].strip():
            return text, 'Skipped sorting: comments or other content between imports.'
        raw = text[match.start():match.end()]
        if not re.fullmatch(r'[ \t]*import[ \t]+(?:static[ \t]+)?[\w.*]+[ \t]*;[ \t]*(?:\r?\n)?', raw):
            return text, 'Skipped sorting: an import has an attached comment.'
        pointer = match.end()
        if not raw.endswith('\n'):
            # A trailing // or /* comment belongs to this particular import;
            # reordering it could attach that comment to a different class.
            line_end = text.find('\n', match.end())
            if line_end < 0:
                line_end = len(text)
            if text[match.end():line_end].strip():
                return text, 'Skipped sorting: an import has an attached comment.'

    # Sorting duplicates is safe; selecting unique (type, name) preserves semantics.
    entries = list(dict.fromkeys((match.group(2), bool(match.group(1))) for match in matches))
    project_names = set(project_names)
    project_prefixes = tuple(str(x).rstrip('.') for x in project_prefixes if x)
    entries.sort(key=lambda x: (int(x[1]),
                _category(x[0], project_names, project_prefixes), _sort_key(x)))

    sep = '\r\n' if '\r\n' in text else '\n'
    out = []
    last_category, last_static, last_package = None, None, None
    for name, static in entries:
        cat = _category(name, project_names, project_prefixes)
        package = _package(name, static)
        if out:
            blanks = (2 if static != last_static or cat != last_category else
                      _blank_count(last_package, package))
            out.extend([''] * blanks)
        out.append('import {}{};'.format('static ' if static else '', name))
        last_category, last_static, last_package = cat, static, package

    # Preserve whether the original final import had a line terminator.
    final_break = sep if matches[-1].group().endswith(('\n', '\r')) else ''
    replacement = sep.join(out) + final_break
    return text[:start] + replacement + text[end:], None
