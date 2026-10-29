"""Settings merge and project-root selection. No Sublime dependency."""
import copy
import json
import os

DEFAULTS = {
    "providers": {
        "sources": {"enabled": True, "exclude_dirs": [".git", ".gradle", ".idea", "build", "target", "out", "node_modules", ".smimp"]},
        "jdk": {"enabled": True},
        "jar_glob": {"enabled": False, "patterns": ["**/env/**/*.jar"]}
    },
    "preferred_imports": {},
    "auto_import": {"repair_unindexed_explicit_imports": True, "remove_unused_explicit_imports": True},
    "import_sort": {"on_insert": True, "project_package_prefixes": []},
    "java_executable": "java",
    "javac_executable": "javac",
    "parser": "javac",  # javac AST with conservative lexical fallback
    "max_picker_items": 75000,
    "max_batch_files": 5000
}


def merge(base, overrides):
    result = copy.deepcopy(base)
    for key, val in overrides.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def project_root(folders, filename):
    filename = os.path.realpath(filename) if filename else ""
    matching = [os.path.realpath(f) for f in folders if filename and
                (filename == os.path.realpath(f) or filename.startswith(os.path.realpath(f) + os.sep))]
    return max(matching, key=len) if matching else (folders[0] if folders else None)


def load_project_config(root):
    if not root:
        return {}
    file = os.path.join(root, ".smimp.json")
    if not os.path.isfile(file):
        return {}
    with open(file, encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError(".smimp.json must contain an object")
    return config
