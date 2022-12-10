# Mania to BMSON converter
Simple utility for converting osu mania beatmaps into BMSON format. 
Unfortunately mp3 has an unreliable delay so you will most likely need to mess around with the offset in order for the notes to line up with music

Beatoraja would require around a -95ms offset from testing (however this may vary between machines)
For some reason the bemuse previewer works fine with -5ms so maybe this is just a problem with the mp3 decoder on some implementations

Supports SV changes and other basic timing points, hitsounds should also work but not fully tested

## Usage
`python chart_mania.py -h`

## TODO
- Add file watcher to automatically process and delete downloaded beatmaps
- Fix issues with the offsets

