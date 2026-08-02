#!/usr/bin/env python3
import sys

from md_utils import (
    find_header_block,
    parse_header_arg,
    remove_empty_lines,
    resolve_markdown_targets,
    preserve_mtime,
)

def modify_markdown(file_path, header1, header2, output_header):
    """Modify a markdown file according to the specified rules.
    
    Args:
        file_path: Path to the markdown file
        header1: The first heading to find, including leading '#' markers to
            pin the required level (e.g. "# Summary" matches only a level-1
            heading).
        header2: The second heading to find, with the same matching rules as
            header1
        output_header: The new header text to replace header1
    
    Returns:
        True if modifications were made, False otherwise
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find the header blocks
    header1_idx, header1_level, header1_end = find_header_block(lines, header1)
    if header1_idx is None:
        print(f"Error: Header '{header1}' not found in {file_path}")
        return False
    
    header2_idx, header2_level, header2_end = find_header_block(lines, header2)
    if header2_idx is None:
        print(f"Error: Header '{header2}' not found in {file_path}")
        return False
    
    # Extract the content of header2 block (excluding the header line itself)
    # and remove empty lines
    header2_content = remove_empty_lines(lines[header2_idx + 1:header2_end])
    
    # Create the new content by:
    # 1. Keeping everything before header1_end
    # 2. Replacing header1 with output_header
    # 3. Appending header2 content to header1 block
    # 4. Keeping content between header1 and header2 (except header2 itself)
    # 5. Skipping header2 block
    # 6. Keeping everything after header2_end
    
    new_lines = []
    
    # Add everything up to header1 line
    new_lines.extend(lines[:header1_idx])
    
    # Add the new header with the same level as header1
    header_prefix = '#' * header1_level
    new_lines.append(f"{header_prefix} {output_header}\n")
    
    # Add header1 content with empty lines removed
    header1_content = remove_empty_lines(lines[header1_idx + 1:header1_end])
    new_lines.extend(header1_content)
    
    # Add header2 content
    new_lines.extend(header2_content)
    
    # Add content between header1_end and header2_idx (preserving intermediate headers)
    if header1_end < header2_idx:
        new_lines.extend(lines[header1_end:header2_idx])
    
    # Add everything after header2 block
    new_lines.extend(lines[header2_end:])
    
    # Write the modified content back to the file, preserving mtime/atime
    with preserve_mtime(file_path):
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
    
    return True

def process_files(file_paths, header1, header2, output_header):
    """Process multiple markdown files.
    
    Args:
        file_paths: List of file paths to process
        header1: The first header to find
        header2: The second header to find
        output_header: The new header text to replace header1
        
    Returns:
        A tuple of (success_count, failure_count)
    """
    success_count = 0
    failure_count = 0
    
    for file_path in file_paths:
        try:
            if modify_markdown(file_path, header1, header2, output_header):
                print(f"Successfully modified {file_path}")
                success_count += 1
            else:
                print(f"Failed to modify {file_path} - headers not found")
                failure_count += 1
        except Exception as e:
            print(f"Error processing {file_path}: {str(e)}")
            failure_count += 1
    
    return success_count, failure_count

def main():
    if len(sys.argv) != 5:
        print("Usage: python md_merge_headers.py <markdown_file_or_directory> <header1> <header2> <output_header>")
        print('  <header1>/<header2> must include leading # markers indicating their level, e.g. "# Summary" or "### Summary".')
        sys.exit(1)
    
    path = sys.argv[1]
    header1 = sys.argv[2]
    header2 = sys.argv[3]
    output_header = sys.argv[4]
    
    try:
        parse_header_arg(header1)
        parse_header_arg(header2)
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
    
    success_count, failure_count = process_files(markdown_files, header1, header2, output_header)
    
    if len(markdown_files) > 1:
        print(f"\nSummary: {success_count} files modified successfully, {failure_count} files failed")
    
    sys.exit(0 if success_count > 0 else 1)

if __name__ == "__main__":
    main()