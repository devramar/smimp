"""Dependency-free Java source handling. Syntax scanner is deliberately conservative."""
import re

PKG = re.compile(r"(?m)^[ \t]*package\s+([\w.]+)\s*;")
IMP = re.compile(r"(?m)^[ \t]*import[ \t]+(static[ \t]+)?([\w.*]+)[ \t]*;[ \t]*(?:\r?\n)?")
DECL = re.compile(r"\b(?:class|interface|enum|record|@interface)\s+([A-Za-z_$][\w$]*)")
WORD = re.compile(r"[A-Za-z_$][\w$]*")


def masked(text):
    """Preserve offsets/newlines, hide strings, chars, text blocks and comments."""
    out = list(text)
    i, size = 0, len(text)
    while i < size:
        start = i
        if text.startswith('//', i):
            i = text.find('\n', i)
            if i < 0: i = size
        elif text.startswith('/*', i):
            end = text.find('*/', i + 2)
            i = size if end < 0 else end + 2
        elif text.startswith('"""', i):
            end = text.find('"""', i + 3)
            while end >= 0 and end > 0 and text[end - 1] == '\\':
                end = text.find('"""', end + 3)
            i = size if end < 0 else end + 3
        elif text[i] in ('"', "'"):
            quote = text[i]
            i += 1
            while i < size:
                if text[i] == '\\': i += 2
                elif text[i] == quote:
                    i += 1
                    break
                else: i += 1
        else:
            i += 1
            continue
        for j in range(start, min(i, size)):
            if out[j] not in '\r\n': out[j] = ' '
    return ''.join(out)


def package_name(text):
    match = PKG.search(masked(text))
    return match.group(1) if match else ""


def imports(text):
    clean = masked(text)
    return [(m.group(2), bool(m.group(1))) for m in IMP.finditer(clean)]


def declarations(text):
    """Top-level only, prevents indexing member/anonymous class artifacts as top level."""
    clean = masked(text)
    depth, last = 0, 0
    for match in re.finditer(r"[{}]|\b(?:class|interface|enum|record)\s+[A-Za-z_$][\w$]*|@interface\s+[A-Za-z_$][\w$]*", clean):
        token = match.group()
        if token == '{': depth += 1
        elif token == '}': depth = max(0, depth - 1)
        elif depth == 0:
            name = token.split()[-1]
            if WORD.fullmatch(name):
                yield name
        last = match.end()


def symbol_at(text, offset):
    offset = max(0, min(offset, len(text)))
    for match in WORD.finditer(text[max(0, offset - 200):min(len(text), offset + 200)]):
        a = max(0, offset - 200) + match.start()
        b = max(0, offset - 200) + match.end()
        if a <= offset < b or (offset == b and b > a):
            return match.group()
    return ""


def fallback_candidates(text):
    """Fallback only when no JDK parser; avoid guessing lowercase expressions."""
    clean = masked(text)
    # Skip all tokens contained in package and import declarations.
    clean = PKG.sub(lambda m: ' ' * len(m.group()), clean)
    clean = IMP.sub(lambda m: ' ' * len(m.group()), clean)
    # Types in declarations, generics, annotations, constructor invocations and static receivers.
    potential = set()
    patterns = [
        r'@([A-Z][\w$]*)\b',
        r'\b(?:new|extends|implements|throws|instanceof|permits)\s+([A-Z][\w$]*)\b',
        r'\b([A-Z][\w$]*)\s*<',
        r'\b([A-Z][\w$]*)\s*\[\s*\]',
        r'\b([A-Z][\w$]*)\s*\.',
        r'\b([A-Z][\w$]*)\s+[a-z_$][\w$]*\b',
        r'[<,]\s*([A-Z][\w$]*)\s*[,>]',
    ]
    for pattern in patterns:
        potential.update(re.findall(pattern, clean))
    return potential


def unused_explicit_imports(text, referenced_symbols):
    """Return ordinary explicit imports whose simple type is not referenced.

    Static imports and wildcard imports are deliberately excluded: the lightweight
    type scanner cannot prove whether their members/types are in use. Callers
    should only use this with a reliable AST result, never the lexical fallback.
    """
    referenced = set(referenced_symbols)
    # Preserve any import whose simple name still appears textually outside the
    # import declarations. This intentionally includes comments/Javadocs and
    # strings: false positives merely keep an import, while a false negative
    # could delete one used in syntax the lightweight AST visitor missed.
    without_imports = IMP.sub(lambda m: ''.join('\n' if c == '\n' else '\r' if c == '\r' else ' '
                                                   for c in m.group()), text)
    unused = []
    for qualified, is_static in imports(text):
        if is_static or qualified.endswith('.*'):
            continue
        simple = qualified.rsplit('.', 1)[-1]
        if simple in referenced:
            continue
        if re.search(r'(?<![\w$])' + re.escape(simple) + r'(?![\w$])', without_imports):
            continue
        unused.append(qualified)
    return unused


def _safe_import_line(text, match):
    """An import can be removed only when no trailing comment is attached to it."""
    raw = text[match.start():match.end()]
    if not re.fullmatch(r'[ \t]*import[ \t]+(?:static[ \t]+)?[\w.*]+[ \t]*;[ \t]*(?:\r?\n)?', raw):
        return False
    if not raw.endswith('\n'):
        line_end = text.find('\n', match.end())
        if line_end < 0: line_end = len(text)
        if text[match.end():line_end].strip():
            return False
    return True


def remove_imports(text, qualified_names):
    """Safely remove explicit non-static imports by qualified name.

    Returns ``(updated, removed, skipped)``. Imports with attached comments are
    left untouched so smimp never strands or reassigns a comment.
    """
    wanted = set(qualified_names)
    if not wanted:
        return text, [], []
    clean = masked(text)
    matches = list(IMP.finditer(clean))
    spans, removed, skipped = [], [], []
    for i, match in enumerate(matches):
        qualified, is_static = match.group(2), bool(match.group(1))
        if is_static or qualified not in wanted:
            continue
        # A comment between adjacent imports may describe either side. Leave the
        # target alone instead of orphaning or reassigning that comment.
        before = text[matches[i - 1].end():match.start()] if i else ''
        after = text[match.end():matches[i + 1].start()] if i + 1 < len(matches) else ''
        if (not _safe_import_line(text, match) or
                (before.strip() and i > 0) or (after.strip() and i + 1 < len(matches))):
            skipped.append(qualified)
            continue
        spans.append((match.start(), match.end()))
        removed.append(qualified)
    if not spans:
        return text, [], skipped
    out, cursor = [], 0
    for start, end in spans:
        out.append(text[cursor:start])
        cursor = end
    out.append(text[cursor:])
    updated = ''.join(out)
    # If cleanup removed the final ordinary import, collapse the now-empty
    # package/import gap back to the conventional single blank line.
    if removed and not imports(updated):
        clean_updated = masked(updated)
        package = PKG.search(clean_updated)
        if package:
            sep = '\r\n' if '\r\n' in updated else '\n'
            tail = updated[package.end():]
            blanks = re.match(r'(?:[ \t]*\r?\n)+', tail)
            if blanks:
                updated = updated[:package.end()] + sep * 2 + tail[blanks.end():]
    return updated, removed, skipped


def conflicting_explicit_imports(text, additions):
    """Existing explicit imports that conflict by simple name with additions."""
    chosen = {name.rsplit('.', 1)[-1]: name for name in additions if '.' in name}
    conflicts = []
    for qualified, is_static in imports(text):
        if is_static or qualified.endswith('.*'):
            continue
        simple = qualified.rsplit('.', 1)[-1]
        replacement = chosen.get(simple)
        if replacement and replacement != qualified:
            conflicts.append(qualified)
    return conflicts


def reconcile_imports(text, additions, removals=()):
    """Remove stale/dead imports, replace simple-name conflicts, then add imports.

    Explicit picker selections naturally replace an older import of the same
    simple class name. Automatic import can additionally provide proven-unused
    imports in ``removals``. Returns ``(text, added, removed, skipped_removals)``.
    """
    additions = list(dict.fromkeys(name for name in additions if name))
    to_remove = list(dict.fromkeys(list(removals) + conflicting_explicit_imports(text, additions)))
    updated, removed, skipped = remove_imports(text, to_remove)

    # If a conflicting import could not be removed safely (typically an attached
    # comment), do not add a second import with the same simple name.
    blocked_simples = {name.rsplit('.', 1)[-1] for name in skipped}
    safe_additions = [name for name in additions if name.rsplit('.', 1)[-1] not in blocked_simples]
    updated, added = add_imports(updated, safe_additions)
    return updated, added, removed, skipped


def add_imports(text, names):
    """Return updated source without reordering existing imports or touching body."""
    clean = masked(text)
    existing = {qualified for qualified, static in imports(text) if not static}
    pkg = package_name(text)
    line_sep = '\r\n' if '\r\n' in text else '\n'
    missing = sorted({name for name in names if name and name not in existing and
                      '.' in name and not name.startswith('java.lang.') and
                      name.rsplit('.', 1)[0] != pkg})
    if not missing: return text, []
    imports_block = ''.join('import {};' .format(name) + line_sep for name in missing)
    positions = list(IMP.finditer(clean))
    if positions:
        # Add after last import line, preserving existing ordering and comments.
        at = positions[-1].end()
        if at == len(text) or text[at - 1] not in '\r\n': imports_block = line_sep + imports_block
        if at < len(text) and text[at] not in '\r\n': imports_block += line_sep
        return text[:at] + imports_block + text[at:], missing
    package = PKG.search(clean)
    if package:
        # Consume blank lines only; leave any comments after the package intact.
        at = package.end()
        rest = text[at:]
        blanks = re.match(r'(?:[ \t]*\r?\n)*', rest).end()
        return text[:at] + line_sep * 2 + imports_block + line_sep + rest[blanks:], missing
    # Insert after any consecutive licence/header comments, not inside them.
    pos = 0
    while pos < len(text):
        spaces = re.match(r'[ \t\r\n]*', text[pos:])
        pos += spaces.end()
        if text.startswith('//', pos):
            end = text.find('\n', pos)
            pos = len(text) if end < 0 else end + 1
        elif text.startswith('/*', pos):
            end = text.find('*/', pos + 2)
            if end < 0: break
            pos = end + 2
        else:
            break
    if pos and pos < len(text) and text[pos - 1] not in '\r\n': imports_block = line_sep + imports_block
    return text[:pos] + imports_block + line_sep + text[pos:], missing
