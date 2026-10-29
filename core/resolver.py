"""Pure import resolution: never guess between distinct qualified names."""
from .java_source import package_name, imports, declarations


def resolve(text, symbols, by_name, preferences, repair_unindexed_explicit=True):
    pkg = package_name(text)
    imp = imports(text)
    declared = set(declarations(text))
    # An explicit import only satisfies a symbol if that exact FQN still exists
    # in the current class index. This lets a moved dependency class be repaired:
    #   import old.pkg.JObject;  ->  import new.pkg.JObject;
    explicit = {}
    for qualified, is_static in imp:
        if not is_static and not qualified.endswith('.*'):
            explicit.setdefault(qualified.rsplit('.', 1)[-1], set()).add(qualified)
    wildcards = {q[:-2] for q, is_static in imp if not is_static and q.endswith('.*')}
    resolved, ambiguous, unknown = {}, {}, set()
    for name in sorted(set(symbols)):
        if not name or not name[0].isupper() or name in declared:
            continue
        all_candidates = sorted(set(by_name.get(name, [])))
        existing = explicit.get(name, ())
        if any(q in all_candidates for q in existing):
            continue
        # Existing imports that the configured index cannot see are normally
        # trusted when repair is disabled. With repair enabled, a referenced
        # simple name is resolved again against current candidates, allowing a
        # dependency package move to be repaired during auto-import.
        if existing and not repair_unindexed_explicit:
            continue
        if name in ('String', 'Object', 'Class', 'System', 'Math', 'Thread', 'Exception', 'Override', 'Deprecated'):
            # Only skip when this symbol resolves to java.lang by class index.
            if 'java.lang.' + name in all_candidates: continue
        if ('java.lang.' + name in all_candidates or
            any(q.rsplit('.', 1)[0] == pkg for q in all_candidates) or
            any(q.rsplit('.', 1)[0] in wildcards for q in all_candidates)):
            continue
        candidates = [q for q in all_candidates if q.rsplit('.', 1)[0] != pkg]
        if not candidates:
            unknown.add(name)
            continue
        pref = preferences.get(name)
        if pref in candidates:
            resolved[name] = pref
        elif len(candidates) == 1:
            resolved[name] = candidates[0]
        else:
            ambiguous[name] = candidates
    return resolved, ambiguous, unknown
