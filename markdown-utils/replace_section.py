#!/usr/bin/env python3
import sys

from md_utils import (
    find_header_block,
    parse_header_arg,
    resolve_markdown_targets,
    preserve_mtime,
)


def replace_section(file_path, header, replace_by):
    """Replace a markdown section (its header line and content) in a file.

    The section is defined as the header line matching `header` plus everything
    up to (but not including) the next header of the same or shallower level
    (or end of file).

    If `replace_by` is an empty string the section is removed (same behaviour
    as remove_section.py). The `replace_by` string may contain the two
    characters ``\n`` which will be converted to real newlines for
    multi-line replacements.

    Args:
        file_path: Path to the markdown file
        header: The heading identifying the section to replace, including
            leading '#' markers to pin the required level (e.g. "# Vault
            todos" matches only a level-1 heading).
        replace_by: String to replace the section with. May contain literal
            '\\n' sequences to indicate line breaks. If empty, the section
            will be removed.

    Returns:
        True if the file was modified, False if the header wasn't found
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    header_idx, header_level, block_end = find_header_block(lines, header)
    if header_idx is None:
        print(f"Error: Header '{header}' not found in {file_path}")
        return False

    # Interpret literal \n sequences as real newlines
    if replace_by:
        replacement = replace_by.replace('\\n', '\n')
        if not replacement.endswith('\n'):
            replacement += '\n'
        replacement_lines = replacement.splitlines(keepends=True)
        new_lines = lines[:header_idx] + replacement_lines + lines[block_end:]
    else:
        # Behaviour identical to remove_section.py when replace_by is empty
        new_lines = lines[:header_idx] + lines[block_end:]

    with preserve_mtime(file_path):
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

    return True


def process_files(file_paths, header, replace_by):
    """Replace a section in multiple markdown files.

    Args:
        file_paths: List of file paths to process
        header: The text of the header identifying the section to replace
        replace_by: Replacement text (may contain literal '\\n')

    Returns:
        A tuple of (success_count, failure_count)
    """
    success_count = 0
    failure_count = 0

    for file_path in file_paths:
        try:
            if replace_section(file_path, header, replace_by):
                print(f"Successfully modified {file_path}")
                success_count += 1
            else:
                print(f"Failed to modify {file_path} - header not found")
                failure_count += 1
        except Exception as e:
            print(f"Error processing {file_path}: {str(e)}")
            failure_count += 1

    return success_count, failure_count


def main():
    if len(sys.argv) != 4:
        print("Usage: python replace_section.py <markdown_file_or_directory> <heading> <replace_by>")
        print("  <heading> must include leading # markers indicating its level, e.g. \"# Vault todos\" or \"### Vault todos\".")
        print("  <replace_by> may include literal \\n+ to indicate newlines; pass an empty string to remove the section.")
        sys.exit(1)

    path = sys.argv[1]
    header = sys.argv[2]
    replace_by = sys.argv[3]

    try:
        parse_header_arg(header)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    try:
        markdown_files = resolve_markdown_targets(path)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not markdown_files:
        print(f"No markdown files found in '{path}'")
        sys.exit(1)

    if len(markdown_files) > 1:
        print(f"Found {len(markdown_files)} markdown files to process")

    success_count, failure_count = process_files(markdown_files, header, replace_by)

    if len(markdown_files) > 1:
        print(f"\nSummary: {success_count} files modified successfully, {failure_count} files failed")

    sys.exit(0 if success_count > 0 else 1)


if __name__ == "__main__":
    main()
