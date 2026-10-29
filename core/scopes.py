"""Project-root-bounded folder selection for batch tools; no Sublime dependency.

Paths are canonicalized before comparisons so neighboring prefixes and symlink
escapes can never turn a one-root sort into a wider filesystem operation.
"""
import os


def canonical(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def within(path, root):
    try:
        return os.path.commonpath((canonical(path), canonical(root))) == canonical(root)
    except (ValueError, OSError):  # Different Windows drive / invalid path
        return False


def normalized_roots(roots):
    result = []
    for root in roots:
        path = canonical(root)
        if os.path.isdir(path) and path not in result:
            result.append(path)
    return result


def owning_root(roots, path):
    if not path:
        return None
    matching = [r for r in normalized_roots(roots) if within(path, r)]
    return max(matching, key=len) if matching else None


def child_folders(current, root, excluded=()):
    """Immediate traversable directories within root (no symlink traversal)."""
    if not within(current, root) or not os.path.isdir(current):
        return []
    try:
        with os.scandir(current) as entries:
            directories = [item.path for item in entries
                           if item.name not in excluded and not item.name.startswith('.smimp')
                           and item.is_dir(follow_symlinks=False)
                           and within(item.path, root)]
    except OSError:
        return []
    return sorted(directories, key=lambda d: (os.path.basename(d).casefold(), d))
