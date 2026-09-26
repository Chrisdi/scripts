#!/bin/bash
#
# make_audiobook.sh - Combine M4A files into a single M4B audiobook with chapters
#
# Usage: ./make_audiobook.sh <input_dir> <file_pattern> <title> <author> [output_file]
#
# Example: ./make_audiobook.sh ./chapters "*.m4a" "The Great Book" "Jane Doe"
#

set -euo pipefail

# ---------- Argument parsing ----------
if [ $# -lt 4 ]; then
  echo "Usage: $0 <input_dir> <file_pattern> <title> <author> [output_file]" >&2
  echo "Example: $0 ./chapters '*.m4a' 'The Great Book' 'Jane Doe'" >&2
  exit 1
fi

INPUT_DIR="$1"
FILE_PATTERN="$2"
TITLE="$3"
AUTHOR="$4"
OUTPUT="${5:-$TITLE.m4b}"

if [ ! -d "$INPUT_DIR" ]; then
  echo "Error: input directory '$INPUT_DIR' does not exist" >&2
  exit 1
fi

# ---------- Check dependencies ----------
for cmd in ffmpeg ffprobe; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: '$cmd' is not installed or not in PATH" >&2
    exit 1
  fi
done

# ---------- Create temp files ----------
TMPDIR=$(mktemp -d -t audiobook.XXXXXX)
trap 'rm -rf "$TMPDIR"' EXIT

CHAPTERS_FILE="$TMPDIR/chapters.txt"
LIST_FILE="$TMPDIR/list.txt"

# ---------- Collect input files (sorted) ----------
# Using null-delimited find + sort for safety with spaces/special chars
mapfile -d '' FILES < <(
  find "$INPUT_DIR" -maxdepth 1 -type f -name "$FILE_PATTERN" -print0 | sort -z
)

if [ ${#FILES[@]} -eq 0 ]; then
  echo "Error: no files matching '$FILE_PATTERN' found in '$INPUT_DIR'" >&2
  exit 1
fi

echo "Found ${#FILES[@]} input file(s)."

# ---------- Generate chapters metadata ----------
{
  echo ";FFMETADATA1"
  echo "title=$TITLE"
  echo "artist=$AUTHOR"
  echo "album=$TITLE"
  echo "genre=Audiobook"

  START=0
  i=1
  for f in "${FILES[@]}"; do
    DUR=$(ffprobe -v error -show_entries format=duration \
                   -of default=noprint_wrappers=1:nokey=1 "$f")

    # Convert seconds (float) to integer milliseconds using awk (portable, no bc)
    DUR_MS=$(awk -v d="$DUR" 'BEGIN { printf "%d", d * 1000 }')
    END=$((START + DUR_MS))

    # Strip extension from filename for the chapter title
    BASENAME=$(basename "$f")
    CHAPTITLE="${BASENAME%.*}"

    echo ""
    echo "[CHAPTER]"
    echo "TIMEBASE=1/1000"
    echo "START=$START"
    echo "END=$END"
    echo "title=Ch $i - $CHAPTITLE"

    START=$END
    i=$((i + 1))
  done
} > "$CHAPTERS_FILE"

# ---------- Generate concat list ----------
: > "$LIST_FILE"
for f in "${FILES[@]}"; do
  # Escape single quotes for ffmpeg concat format
  ESCAPED=${f//\'/\'\\\'\'}
  echo "file '$ESCAPED'" >> "$LIST_FILE"
done

# ---------- Build the audiobook ----------
echo "Building audiobook: $OUTPUT"
ffmpeg -hide_banner -loglevel warning -stats \
  -f concat -safe 0 -i "$LIST_FILE" \
  -i "$CHAPTERS_FILE" \
  -map_metadata 1 \
  -c:a aac -b:a 128k \
  -movflags +faststart \
  "$OUTPUT"

echo "Done: $OUTPUT"