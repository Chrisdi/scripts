#!/bin/bash

echo ";FFMETADATA1"
echo "title=My Audiobook"
echo "artist=Author Name"
echo "genre=Audiobook"

START=0
i=1
for f in *.m4a; do
  DUR=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$f")
  DUR_MS=$(echo "$DUR * 1000 / 1" | bc)
  END=$((START + DUR_MS))
  echo ""
  echo "[CHAPTER]"
  echo "TIMEBASE=1/1000"
  echo "START=$START"
  echo "END=$END"
  echo "title=Ch $i - $(basename $f)"
  START=$END
  i=$((i + 1))
done


for f in *.m4a; do 
  echo "file '$PWD/$f'" >> list.txt;
done

ffmpeg -f concat -safe 0 -i list.txt -i chapters.txt  -map_metadata 1 -c:a aac -b:a 128k -movflags +faststart output.m4b

