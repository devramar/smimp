# Installing smimp

smimp targets **Sublime Text 4** and uses Sublime's Python 3.8 plugin host. For the best parser behavior, install a **JDK 11 or newer** and make both `java` and `javac` available to Sublime.

## Development install from this repository

This repository is deliberately laid out so the repository root is also the Sublime package directory.

1. In Sublime Text choose **Preferences → Browse Packages…**.
2. Close the file browser path somewhere convenient to copy/clone from.
3. Clone this repository as a directory named **`smimp`** directly inside Sublime's `Packages` directory.

Conceptually:

```text
<Packages>/
└── smimp/
    ├── smimp.py
    ├── core/
    ├── providers/
    ├── java/
    └── ...
```

The important path is:

```text
<Packages>/smimp/smimp.py
```

After cloning or updating, use **Developer → Reload Plugins** or restart Sublime Text.

## Install from a release/source ZIP

If you have a repository ZIP rather than a Git clone:

1. Extract the ZIP.
2. Copy the resulting `smimp` directory into **Preferences → Browse Packages…**.
3. Confirm `Packages/smimp/smimp.py` exists.
4. Reload Sublime plugins or restart Sublime.

When upgrading, replace the package files. Your global settings under `Packages/User/` and per-project `.smimp.json` files are separate and can remain in place.

## Confirm the plugin loaded

Open Sublime's Command Palette and type:

```text
smimp:
```

You should see commands such as:

- `smimp: Import Class at Cursor`
- `smimp: Auto Import File`
- `smimp: Sort Imports in File`
- `smimp: Show Index Status`

If they do not appear, open **View → Show Console** and look for a Python traceback during plugin loading.

## Verify Java/JDK access

smimp can fall back to lexical analysis, but the JDK AST helper gives the safest automatic-import and unused-import behavior.

From a terminal, verify:

```bash
java -version
javac -version
```

If those work in your shell but Sublime cannot find them, configure absolute executable paths with **Command Palette → smimp: Open Global Settings**:

```json
{
  "java_executable": "/absolute/path/to/java",
  "javac_executable": "/absolute/path/to/javac"
}
```

On Windows, use normal JSON escaping for backslashes, for example:

```json
{
  "java_executable": "C:\\Program Files\\Java\\jdk-25\\bin\\java.exe",
  "javac_executable": "C:\\Program Files\\Java\\jdk-25\\bin\\javac.exe"
}
```

## First project

With a Java file open:

1. Put the caret inside a class identifier such as `List`.
2. Press **Ctrl+I**.
3. Select a class from the fuzzy picker.
4. Press **Ctrl+Z** once if you want to revert the insertion and associated sorting.
5. Press **Ctrl+Shift+I** to try automatic imports for the whole active file.

The shipped key bindings are scoped to Java syntax only. If `Ctrl+I` or `Ctrl+Shift+I` conflicts with your own bindings, override them in `Packages/User/Default (<OS>).sublime-keymap`.

## Configure dependency JARs

Project sources and JDK classes are indexed by default. Arbitrary dependency JARs are opt-in.

Use **Command Palette → smimp: Open Project Settings** and configure patterns relative to a Sublime project root:

```json
{
  "providers": {
    "jar_glob": {
      "enabled": true,
      "patterns": [
        "**/env/**/*.jar",
        "libs/**/*.jar"
      ]
    }
  }
}
```

Then run:

```text
smimp: Rebuild Class Index
```

and inspect:

```text
smimp: Show Index Status
```

The `env` example is just a configured glob. smimp does not otherwise know what JRunner is, and the same provider can point at any resolved JAR directory.

## Per-project and global settings

Global settings:

```text
Packages/User/smimp.sublime-settings
```

Project-root settings:

```text
<root>/.smimp.json
```

When a Sublime project has multiple root folders, the active file determines which root's `.smimp.json` applies. Project settings recursively override the global defaults.

## Package Control status

This repository layout is suitable for keeping smimp under Git and for a future Package Control submission, but smimp is **not automatically published to Package Control merely by creating this repository**. Package Control publication should be treated as a separate release step.

## Uninstall

Delete the `Packages/smimp` directory and reload Sublime plugins. Optionally remove:

```text
Packages/User/smimp.sublime-settings
```

and any `.smimp.json` files you created in projects.
