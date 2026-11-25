# markdown-utils

Standalone Python 3 scripts for editing markdown headings. Each accepts a single `.md` file
or a directory (recursed). Headings must include their `#` level markers.

```
python md_merge_headers.py <file_or_dir> <heading1> <heading2> <output_heading>
python remove_section.py <file_or_dir> <heading>
python replace_section.py <file_or_dir> <heading> <replace_by>
python md_join.py -o <output_file.md> <file1.md> [file2.md ...]
python md_join.py -o <output_file.md> --replace-ai-recap <file1.md> [file2.md ...]
```

Examples:

```
python md_merge_headers.py data "# Summary" "# Events" "Summary+Events"
python remove_section.py data "# Vault todos"
python replace_section.py data "# Transcription" "Updated transcription summary"
python replace_section.py data "# Transcription" ""
python md_join.py -o combined.md chapter1.md chapter2.md
python md_join.py -o combined.md --replace-ai-recap chapter1.md chapter2.md
```

`md_join.py` joins the files in the given order, removing YAML frontmatter from
the joined document. Glob patterns are supported and their matches are sorted
in natural order (for example, `1.md`, `2.md`, `10.md`). It writes the
collected frontmatter, labeled by source filename, to `combined-frontmatter.md`.
With `--replace-ai-recap`, each `# AI - recap` block through its following
`# Content` heading is replaced by a heading using that file's basename.
