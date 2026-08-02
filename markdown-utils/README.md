# markdown-utils

Standalone Python 3 scripts for editing markdown headings. Each accepts a single `.md` file
or a directory (recursed). Headings must include their `#` level markers.

```
python md_merge_headers.py <file_or_dir> <heading1> <heading2> <output_heading>
python remove_section.py <file_or_dir> <heading>
```

Examples:

```
python md_merge_headers.py data "# Summary" "# Events" "Summary+Events"
python remove_section.py data "# Vault todos"
```
