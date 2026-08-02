#!/usr/bin/env python3
import sys

from md_utils import (
    find_header_block,
    parse_header_arg,
    resolve_markdown_targets,
    preserve_mtime,
)

def remove_section(file_path, header):
    """Remove a markdown section (its header line and content) from a file.

    The section is defined as the header line matching `header` plus everything
    up to (but not including) the next header of the same or shallower level
    (or end of file).

    Args:
        file_path: Path to the markdown file
        header: The heading identifying the section to remove, including
            leading '#' markers to pin the required level (e.g. "# Vault
            todos" matches only a level-1 heading).

    Returns:
        True if the section was removed, False if the header wasn't found
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    header_idx, header_level, block_end = find_header_block(lines, header)
    if header_idx is None:
        print(f"Error: Header '{header}' not found in {file_path}")
        return False

    new_lines = lines[:header_idx] + lines[block_end:]

    with preserve_mtime(file_path):
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

    return True

def process_files(file_paths, header):
    """Remove a section from multiple markdown files.

    Args:
        file_paths: List of file paths to process
        header: The text of the header identifying the section to remove

    Returns:
        A tuple of (success_count, failure_count)
    """
    success_count = 0
    failure_count = 0

    for file_path in file_paths:
        try:
            if remove_section(file_path, header):
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
    if len(sys.argv) != 3:
        print("Usage: python remove_section.py <markdown_file_or_directory> <heading>")
        print('  <heading> must include leading # markers indicating its level, e.g. "# Vault todos" or "### Vault todos".')
        sys.exit(1)

    path = sys.argv[1]
    header = sys.argv[2]

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

    success_count, failure_count = process_files(markdown_files, header)

    if len(markdown_files) > 1:
        print(f"\nSummary: {success_count} files modified successfully, {failure_count} files failed")

    sys.exit(0 if success_count > 0 else 1)

if __name__ == "__main__":
    main()
