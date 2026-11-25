#!/usr/bin/env python3
"""Join Markdown files, keeping their frontmatter in a separate file."""

import argparse
import glob
from pathlib import Path
import re


AI_RECAP_PATTERN = re.compile(
    r"(?ms)^# AI - recap[ \t]*\n.*?^# Content[ \t]*(?:\n|$)"
)


def split_frontmatter(content, file_path):
    """Return (body, frontmatter), where frontmatter excludes its delimiters."""
    lines = content.splitlines(keepends=True)
    if not lines:
        return content, None

    first_line = lines[0].rstrip("\r\n")
    if first_line.startswith("\ufeff"):
        first_line = first_line[1:]
    if first_line != "---":
        return content, None

    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") in ("---", "..."):
            return "".join(lines[index + 1:]), "".join(lines[1:index])

    raise ValueError(f"Unclosed frontmatter in '{file_path}'")


def replace_ai_recap(content, file_name):
    """Replace the AI recap and Content headings with a filename heading."""
    return AI_RECAP_PATTERN.sub(f"# {file_name}\n", content, count=1)


def natural_sort_key(path):
    """Return a sort key that orders numeric filename segments naturally."""
    path_text = str(path)
    parts = tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", path_text)
    )
    return parts, path_text.casefold(), path_text


def expand_input_files(file_patterns):
    """Expand each input pattern in place, naturally sorting its matches."""
    input_paths = []
    for pattern in file_patterns:
        matches = glob.glob(pattern)
        if not matches:
            raise ValueError(f"No files match '{pattern}'")
        input_paths.extend(Path(path) for path in sorted(matches, key=natural_sort_key))
    return input_paths


def join_markdown(output_path, input_paths, replace_recap=False):
    """Write joined Markdown and a companion file containing source frontmatter."""
    output_path = Path(output_path)
    frontmatter_path = output_path.with_name(
        f"{output_path.stem}-frontmatter{output_path.suffix}"
    )
    input_paths = [Path(path) for path in input_paths]

    output_paths = {output_path.resolve(), frontmatter_path.resolve()}
    if any(path.resolve() in output_paths for path in input_paths):
        raise ValueError("Output files must not overwrite an input Markdown file")

    bodies = []
    frontmatter_blocks = []
    for path in input_paths:
        content = path.read_text(encoding="utf-8")
        body, frontmatter = split_frontmatter(content, path)
        if replace_recap:
            body = replace_ai_recap(body, path.stem)
        bodies.append(body.strip("\r\n"))
        if frontmatter is not None:
            frontmatter_blocks.append(f"## {path}\n\n{frontmatter.rstrip()}")

    joined_body = "\n\n".join(body.rstrip() for body in bodies if body.strip())
    frontmatter_content = "\n\n".join(frontmatter_blocks)

    output_path.write_text(
        f"{joined_body}\n" if joined_body else "",
        encoding="utf-8",
    )
    frontmatter_path.write_text(
        f"{frontmatter_content}\n" if frontmatter_content else "",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Join Markdown files and collect their frontmatter separately. "
            "Glob matches are naturally sorted."
        )
    )
    parser.add_argument("-o", "--output", required=True, help="Output Markdown file")
    parser.add_argument(
        "--replace-ai-recap",
        action="store_true",
        help="Replace each '# AI - recap' block through '# Content' with its filename heading",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Markdown files or glob patterns to join, in order",
    )
    args = parser.parse_args()

    try:
        join_markdown(
            args.output,
            expand_input_files(args.files),
            replace_recap=args.replace_ai_recap,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
