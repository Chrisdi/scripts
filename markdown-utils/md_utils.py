#!/usr/bin/env python3
"""Shared helpers for the markdown-refactor utility scripts.

Keep this module stdlib-only so every script in this repo stays a simple,
standalone Python 3 file that runs identically on Linux and Windows.
"""
import os
import re
from contextlib import contextmanager


def get_header_level(header_line):
    """Get the level of a markdown header based on the number of # characters."""
    match = re.match(r'^(#+)\s+', header_line)
    if match:
        return len(match.group(1))
    return 0


def parse_header_arg(header_arg):
    """Parse a CLI heading argument into (level, text).

    The argument must include leading '#' markers to pin the heading to a
    specific level (e.g. "# Vault todos" for level 1, "### Vault todos" for
    level 3).

    Args:
        header_arg: The raw CLI heading argument

    Returns:
        A tuple (level, header_text)

    Raises:
        ValueError: If header_arg has no leading '#' markers.
    """
    match = re.match(r'^(#+)\s*(.*)$', header_arg.strip())
    if not match:
        raise ValueError(
            f"Heading '{header_arg}' must start with '#' markers indicating its level, "
            'e.g. "# Vault todos" or "### Vault todos"'
        )
    return len(match.group(1)), match.group(2).strip()


def find_header_block(lines, header_arg, start_idx=0):
    """Find a header block in the markdown content.

    Args:
        lines: List of lines in the markdown file
        header_arg: The heading to find, including leading '#' markers to
            require a specific level, e.g. "### Vault todos" only matches a
            level-3 heading.
        start_idx: The index to start searching from

    Returns:
        A tuple containing (header_line_idx, header_level, block_end_idx) or
        (None, None, None) if not found. block_end_idx is the index of the next
        header line of equal or shallower level (or len(lines) if none).
    """
    required_level, header_text = parse_header_arg(header_arg)
    header_pattern = re.compile(r'^#{' + str(required_level) + r'}\s+' + re.escape(header_text) + r'\s*$')

    for i in range(start_idx, len(lines)):
        match = header_pattern.match(lines[i])
        if match:
            block_end = len(lines)

            # Find the end of this block (next header of same or higher level)
            for j in range(i + 1, len(lines)):
                next_level = get_header_level(lines[j])
                if next_level > 0 and next_level <= required_level:
                    block_end = j
                    break

            return i, required_level, block_end

    return None, None, None


def remove_empty_lines(lines):
    """Remove empty lines from a list of lines.

    Args:
        lines: List of lines to process

    Returns:
        A new list with empty lines removed
    """
    return [line for line in lines if line.strip()]


def find_markdown_files(directory):
    """Find all markdown files in a directory and its subdirectories.

    Args:
        directory: The directory to search in

    Returns:
        A list of paths to markdown files
    """
    markdown_files = []

    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith('.md'):
                markdown_files.append(os.path.join(root, file))

    return markdown_files


def resolve_markdown_targets(path):
    """Resolve a CLI path argument into a list of markdown files to process.

    Accepts either a single .md file or a directory, in which case all .md
    files found recursively in it are returned.
    """
    if os.path.isfile(path):
        if not path.lower().endswith('.md'):
            raise ValueError(f"File '{path}' is not a markdown file")
        return [path]

    if os.path.isdir(path):
        return find_markdown_files(path)

    raise ValueError(f"Path '{path}' does not exist")


@contextmanager
def preserve_mtime(file_path):
    """Context manager that preserves a file's atime/mtime across an edit.

    Usage:
        with preserve_mtime(file_path):
            ... read and rewrite file_path ...
    """
    stat_info = os.stat(file_path)
    try:
        yield stat_info
    finally:
        os.utime(file_path, (stat_info.st_atime, stat_info.st_mtime))
