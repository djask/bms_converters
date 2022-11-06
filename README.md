# Mania to BMSON converter
Simple utility for converting osu mania beatmaps into BMSON format. 
Unfortunately mp3 has an unreliable delay so you will most likely need to mess around with the offset in order for the notes to line up with music

Beatoraja would require around a 150ms offset (however this may vary between machines)
For some reason the bemuse previewer works fine with 0ms so maybe this is just a problem with the mp3 decoder on some implementations

## Usage
`python chart_mania.py -h`

## TODO
- Add file watcher to automatically process and delete downloaded beatmaps
- Add the other timing types
- Images not working properly
- Fix issues with the offsets

