#!/usr/bin/env python3
"""Join Markdown files, keeping their frontmatter in a separate file."""

import argparse
from pathlib import Path


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


def join_markdown(output_path, input_paths):
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
        description="Join Markdown files and collect their frontmatter separately."
    )
    parser.add_argument("-o", "--output", required=True, help="Output Markdown file")
    parser.add_argument("files", nargs="+", help="Markdown files to join, in order")
    args = parser.parse_args()

    try:
        join_markdown(args.output, args.files)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
