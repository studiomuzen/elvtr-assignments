#!/usr/bin/env python3
"""
JSON Schema Validator for Ambush! Game Data

Validates JSON data files against schemas using jsonschema (Draft 2020-12).
Maps data files to schemas by directory convention:
  - Squads/*.json → scripts/schemas/squad.schema.json

Usage:
  python scripts/validate_data.py [path]

If no path is given, defaults to ELVATR GAME 1/Assets/Data/ (relative to repo root).
Paths may be files or directories; directories are walked recursively.

Output:
  Prints OK/FAIL lines for each file, summary at end.
  Exits 0 on success, 1 on first validation failure.
"""

import sys
import json
import pathlib
from typing import Dict, List, Optional, Tuple


def get_schema_for_file(file_path: pathlib.Path) -> Optional[pathlib.Path]:
    """
    Determine schema path for a data file based on directory convention.

    Squads/*.json → scripts/schemas/squad.schema.json
    techtree.json (in Assets/Data/) → scripts/schemas/techtree.schema.json
    squad_veterancy.json (in Assets/Data/) → scripts/schemas/squad_veterancy.schema.json
    Maps/*.json → None (skipped with warning)

    Returns None if no schema matches (will be skipped with a warning).
    """
    # Get the immediate parent directory name
    parent_name = file_path.parent.name
    file_name = file_path.name

    schema_dir = pathlib.Path(__file__).parent / "schemas"
    posix = file_path.as_posix()

    if parent_name == "Squads":
        return schema_dir / "squad.schema.json"
    if file_name == "techtree.json":
        return schema_dir / "techtree.schema.json"
    if file_name == "squad_veterancy.json":
        return schema_dir / "squad_veterancy.schema.json"
    if file_name == "terrain_speed.json":
        return schema_dir / "terrain_speed.schema.json"
    if parent_name == "Maps":
        return schema_dir / "map_manifest.schema.json"
    if parent_name == "levels":
        return schema_dir / "level.schema.json"

    # Cross-dir: .claude/state/project.json and .claude/messages/<id>.json
    if posix.endswith(".claude/state/project.json"):
        return schema_dir / "project_state.schema.json"
    if (".claude/messages/" in posix or posix.startswith(".claude/messages/")) and file_name.endswith(".json"):
        return schema_dir / "message.schema.json"

    return None


def load_schema(schema_path: pathlib.Path) -> Dict:
    """Load a JSON schema from disk."""
    try:
        with open(schema_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Failed to load schema {schema_path}: {e}")


def validate_file(file_path: pathlib.Path, schema_path: pathlib.Path) -> Tuple[bool, List[str]]:
    """
    Validate a JSON file against a schema.

    Returns: (is_valid, error_list)
    where error_list is empty on success, or contains one error per validation failure.
    """
    try:
        import jsonschema
    except ImportError:
        raise RuntimeError("jsonschema not installed. Install with: pip install jsonschema")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        return False, [f"Failed to load JSON: {e}"]

    try:
        schema = load_schema(schema_path)
    except RuntimeError as e:
        return False, [str(e)]

    validator = jsonschema.Draft202012Validator(schema)
    errors = []

    for error in sorted(validator.iter_errors(data), key=lambda e: e.absolute_path):
        # Construct JSON pointer from path
        path_parts = [str(p) for p in error.absolute_path]
        json_pointer = "/" + "/".join(path_parts) if path_parts else ""

        # Get a descriptive message
        message = error.message
        errors.append(f"{json_pointer}: {message}")

    return len(errors) == 0, errors


def walk_data_directory(root_path: pathlib.Path) -> List[pathlib.Path]:
    """
    Walk a directory tree, returning all .json files.
    Skips .meta files and anything under a schemas/ folder.
    """
    json_files = []

    if root_path.is_file():
        if root_path.suffix == ".json" and not root_path.name.endswith(".meta"):
            json_files.append(root_path)
    elif root_path.is_dir():
        for item in sorted(root_path.rglob("*.json")):
            # Skip .meta files
            if item.name.endswith(".meta"):
                continue
            # Skip anything under schemas/ folder
            if "schemas" in item.parts:
                continue
            json_files.append(item)

    return json_files


def get_relative_path(file_path: pathlib.Path, repo_root: pathlib.Path) -> str:
    """Return file path relative to repo root."""
    try:
        return str(file_path.relative_to(repo_root))
    except ValueError:
        return str(file_path)


def main():
    """Main entry point."""
    # Determine input path
    if len(sys.argv) > 1:
        input_path = pathlib.Path(sys.argv[1])
    else:
        # Default to ELVATR GAME 1/Assets/Data/ relative to repo root
        script_dir = pathlib.Path(__file__).parent
        repo_root = script_dir.parent
        input_path = repo_root / "ELVATR GAME 1" / "Assets" / "Data"

    repo_root = pathlib.Path(__file__).parent.parent

    # Normalize the input path
    if not input_path.exists():
        print(f"Error: path does not exist: {input_path}", file=sys.stderr)
        return 1

    # Walk and collect JSON files
    json_files = walk_data_directory(input_path)

    if not json_files:
        print("No JSON files found.")
        print("0 passed, 0 failed, 0 skipped.")
        return 0

    passed = 0
    failed = 0
    skipped = 0
    failures = []

    for file_path in json_files:
        rel_path = get_relative_path(file_path, repo_root)

        schema_path = get_schema_for_file(file_path)

        if schema_path is None:
            print(f"WARNING {rel_path}  (no schema found; skipped)")
            skipped += 1
            continue

        # Validate
        is_valid, errors = validate_file(file_path, schema_path)

        schema_name = schema_path.name

        if is_valid:
            print(f"OK  {rel_path}  (schema: {schema_name})")
            passed += 1
        else:
            failed += 1
            for error in errors:
                print(f"FAIL  {rel_path}  {error}")
                failures.append((rel_path, error))

    # Summary line
    print(f"{passed} passed, {failed} failed, {skipped} skipped.")

    if failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
