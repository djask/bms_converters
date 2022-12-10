import json
import logging
import os
import re
import sys
from math import floor
from zipfile import ZipFile
import glob
from optparse import OptionParser

LOGGER = logging.getLogger(__name__)


def unzip_osz(filepath, dst):
    filename, ext = os.path.splitext(filepath)
    dstpath = os.path.join(dst, os.path.basename(filename))
    LOGGER.info(dstpath)
    with ZipFile(filepath, "r") as z:
        if not os.path.exists(dstpath):
            os.mkdir(dstpath)
        z.extractall(path=dstpath)

    return dstpath


def get_beatmap_data(filepath):
    """Reads osu file and returns metadata. Cannot use ini parser reliably as it is not a proper INI file

    Sometimes the osu file leaves comments, so it is more reliable to parse this section manually and
    get the information that we need

    Top sections contain metadata with key:val split
    Bottom sections are a list of objects with ,: separated parameters
    """
    f = open(filepath, "rb")
    f.seek(0)

    metadata = {}
    objs = {}

    # first line is osu file format
    metadata["format"] = re.match("osu file format (.+)", f.readline().decode()).group(
        1
    )
    LOGGER.info(f"Got file format {metadata['format']}")

    obj_headers = ["Events", "TimingPoints", "HitObjects"]

    # 0 = skip, 1 = keyval, 2 = parameterlist
    linefmt = 1
    section = None
    for line in f:
        line = line.decode()
        line = line.strip("\r\n")
        if re.match("\/\/", line) or not line or line == "":
            continue

        # anything with obj lists
        obj_headers = ["Events", "TimingPoints", "HitObjects"]

        # [Section] header
        matches = re.match("\[(.+)\]", line)
        if matches and matches.group(1):
            section = matches.group(1)

            if section == "Editor":
                linefmt = 0

            # everything events and below is object list
            elif section in obj_headers:
                linefmt = 2
                objs[section] = []

            else:
                linefmt = 1

        elif linefmt == 0:
            continue
        elif linefmt == 1:
            key, val = list(map(lambda x: x.strip(" "), line.split(":")))
            metadata[key] = val
        elif linefmt == 2:
            vals = list(map(lambda x: x.strip(" "), line.split(",")))
            objs[section].append(vals)
    return metadata, objs


def sanitise_metadata(m):
    for k, v in m.items():
        for fn in (int, float):
            try:
                m[k] = fn(v)
            except:
                continue

    return m


def sanitise_event(e):
    ret = {}

    if len(e) < 2:
        LOGGER.error(f"Unparseable event {e}")

    if e[0] == "0":
        ret["eventType"] = "bg"
    elif e[0] == "Video":
        ret["eventType"] = "vid"
    else:
        ret["eventType"] = "unused"

    ret["startTime"] = float(e[1])

    idx = 0
    if e[0] in ["0", "Video"]:
        ret["file"] = e[2].strip('"')
        ret["x"] = int(e[3])
        ret["y"] = int(e[4])
    else:
        idx = 0
        for p in e[2:]:
            ret[f"param{idx}"].append(p)
            idx += 1

    # not supporting anything else right now

    return ret


def sanitise_timing(e):
    ret = {}

    ret["uninherited"] = True if e[6] == "1" else False

    # this can either be measure value, or SV change
    if ret["uninherited"]:
        ret["beatLength"] = float(e[1])
    else:
        ret["sv_mult"] = -1.0 / (float(e[1]) / 100.0)

    ret["time"] = int(e[0])
    ret["meter"] = int(e[2])
    ret["sampleSet"] = int(e[3])
    ret["sampleIndex"] = int(e[4])
    ret["volume"] = int(e[5])
    ret["effects"] = int(e[7])

    return ret


def sanitise_mania_hitobj(e, n):
    ret = {}

    ret["lane"] = floor(int(e[0]) * n / 512)
    ret["time"] = int(e[2])
    type_int = int(e[3])

    # note last variable is empty as .osu has trailing :
    tail = e[5].split(":")

    if (type_int >> 0) & 1:
        ret["ln"] = False
    elif (type_int >> 7) & 1:
        ret["ln"] = True
        ret["time_end"] = int(tail[0])
    ret["hitSound"] = int(e[4])
    ret["sample"] = tail[-2]

    return ret


def _measure_time_from_bpm(bpm):
    return 1 / (bpm / 60 / 1000)


def _bpm_from_measure_time(ms):
    return 1 / ms * 1000 * 60


def mania_calc_offset(timings):
    """Calculate the required offset from start for timings

    BMS gets measures from the BPM value, we can offset the measure by changing BPM
    Calculate how much offset by checking the first timing point for the BPM
    (this would be 1/beatLength * 1000 * 60)
    """

    first_timing = [x for x in timings if x["uninherited"]][0]
    initial_bpm = 1 / first_timing["beatLength"] * 1000 * 60
    LOGGER.info(f"Got first timing BPM {initial_bpm}")

    offset_ms = (first_timing["time"] / first_timing["beatLength"] % 1) * first_timing[
        "beatLength"
    ]

    # how much the audio needs to shift in order to create a full measure at start of track
    shift_ms = first_timing["beatLength"] - offset_ms
    LOGGER.info(f"Got offset of {shift_ms}")

    return initial_bpm, shift_ms


def mania_add_offset(obj, offset):
    obj["time"] += offset
    if "time_end" in obj:
        obj["time_end"] += offset
    return obj


def _mania_ms_to_pulse(ms, measure_ms, resolution):
    """Given an osumania hitobj, convert the ms into pulse"""
    measure_pulse = (ms / measure_ms) * resolution
    return measure_pulse


def extract_osz(filepath):
    with ZipFile(filepath, "r") as osz:
        osz.extractall()


def bmson_gen_note(maniaobj, beat_ms):
    """Generate bmson note from osumania objects and timings"""
    note = {}
    note["x"] = maniaobj["lane"] + 1

    note["y"] = _mania_ms_to_pulse(maniaobj["time"], beat_ms, 240)
    note["y"] = int(round(note["y"], 1))

    if not maniaobj["ln"]:
        note["l"] = 0
    else:
        diff = maniaobj["time_end"] - maniaobj["time"]
        note["l"] = _mania_ms_to_pulse(diff, beat_ms, 240)
        note["l"] = int(round(note["l"], 1))

    return note


def bmson_group_mania_soundchannels(hitobjs, timings):
    """bmson format groups notes with the same hitsounds together"""

    # the current measure object
    timings_i = iter(timings)
    m_idx = next(timings_i, None)
    if not m_idx:
        LOGGER.error("No timings in list")
        return

    sound_channels = []
    default_channel = {"notes": []}

    last_note = 0
    for o in hitobjs:

        # timing change
        if m_idx["time"] <= o["time"]:
            m_idx = next(timings_i, m_idx)

        sample = o["sample"]
        if sample != "default":
            channel_obj = next(
                filter(lambda x: x["name"] == sample, sound_channels), None
            )
        else:
            channel_obj = default_channel
        if not channel_obj:
            channel_obj = {"name": sample, "notes": []}
            sound_channels.append(channel_obj)

        note_obj = bmson_gen_note(o, m_idx["beatLength"])
        channel_obj["notes"].append(note_obj)
        last_note = max(last_note, note_obj["y"])

    sound_channels.append(default_channel)

    return sound_channels, last_note


def bmson_gen_main_audio_info(pulse, audiofile):
    """Generates the main audio file name in osumania at the correct offset"""
    channel_obj = {"name": audiofile, "notes": []}

    start_obj = {"x": 0, "y": pulse, "c": True}
    channel_obj["notes"].append(start_obj)

    return channel_obj


def bmson_gen_info(metadata):
    info = {}
    info["title"] = metadata["TitleUnicode"]
    info["subtitle"] = metadata["Version"]
    info["artist"] = metadata["ArtistUnicode"]
    info["subartists"] = [f'obj:{metadata["Creator"]}']
    info["genre"] = "O!M Converted"
    info["mode_hint"] = "beat-7k"
    info["level"] = 0
    info["preview_music"] = metadata["AudioFilename"]
    info["resolution"] = 240

    return info


def bmson_gen_barlines(timings, last, resolution):
    pulse = 0

    # time signature
    sig = 4

    bars = []
    timings_i = iter(timings)
    m_idx = next(timings_i, None)
    t_pulse = _mania_ms_to_pulse(m_idx["time"], m_idx["beatLength"], resolution)

    while pulse < last:
        if t_pulse <= pulse:
            m_idx = next(timings_i, m_idx)
            t_pulse = _mania_ms_to_pulse(m_idx["time"], m_idx["beatLength"], resolution)
        bars.append({"y": pulse})
        pulse += resolution * 4
    return bars


def bmson_gen_bga(bg):
    # only images for now
    bga = {
        "bga_header": [{"id": 0, "name": bg}],
        "bga_events": [{"id": 0, "y": 0}],
        "layer_events": [],
        "poor_events": [],
    }
    return bga


def convert_mania_chart(filepath, dstpath, extra_offset):
    LOGGER.info(f"Converting {filepath}")
    chart_data, chart_objs = get_beatmap_data(filepath)

    # sanitise collected data
    chart_data = sanitise_metadata(chart_data)

    if chart_data["CircleSize"] != 7:
        return

    chart_events_all = list(map(sanitise_event, chart_objs["Events"]))
    chart_events = list(filter(lambda x: x["eventType"] != "unused", chart_events_all))
    chart_timings = list(map(sanitise_timing, chart_objs["TimingPoints"]))
    chart_hitobjs = list(
        map(
            lambda x: sanitise_mania_hitobj(x, chart_data["CircleSize"]),
            chart_objs["HitObjects"],
        )
    )

    # calculate offset for measures
    bpm, offset = mania_calc_offset(chart_timings)
    bpm = round(bpm, 3)
    offset = round(offset, 3)

    chart_hitobjs = list(
        map(lambda x: mania_add_offset(x, offset + extra_offset), chart_hitobjs)
    )
    chart_timings = list(
        map(lambda x: mania_add_offset(x, offset + extra_offset), chart_timings)
    )

    # split into timings bpm and sv changes
    chart_bpms = list(filter(lambda x: x["uninherited"], chart_timings))
    chart_sv = list(filter(lambda x: not x["uninherited"], chart_timings))

    for i in chart_hitobjs[0:5]:
        print(i)
    for i in chart_bpms:
        print(i)

    """BMS Chart processing"""
    # make info dictionary
    info = bmson_gen_info(chart_data)

    # add timing data
    info["init_bpm"] = bpm
    bg = next(filter(lambda x: x["eventType"] == "bg", chart_events), "")["file"]
    info["eyecatch_image"] = bg
    info["back_image"] = bg

    print(info)

    # make sound channels
    channels, last = bmson_group_mania_soundchannels(chart_hitobjs, chart_bpms)

    # calc pulse for first audio
    first_length = chart_bpms[0]["beatLength"]
    pulse = _mania_ms_to_pulse(offset + chart_data["AudioLeadIn"], first_length, 240)
    pulse = int(pulse)

    channels.append(bmson_gen_main_audio_info(pulse, chart_data["AudioFilename"]))

    bmson = {
        "version": "1.0.0",
        "info": info,
        "bga": bmson_gen_bga(bg),
        "bpm_events": [],
        "lines": bmson_gen_barlines(chart_bpms, last, 240),
        "stop_events": [],
        "sound_channels": channels,
    }

    filebase = os.path.basename(filepath)
    dstfile = os.path.join(dstpath, f"{filebase}.bmson")
    with open(dstfile, "w") as f:
        json.dump(bmson, f, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = OptionParser()
    parser.add_option("-z", "--osz", dest="osz", help="mania beatmap to convert")
    parser.add_option("-d", "--dst", dest="dst", help="destination bms directory")
    parser.add_option("-o", "--offset", dest="offset", help="offset override")
    parser.add_option(
        "-p",
        "--present",
        dest="preset",
        default="beatoraja",
        help="offset preset for mp3 [beatoraja/bemuse] (defaults to beatoraja)",
    )

    opt, args = parser.parse_args()
    if not opt.osz:
        parser.error("osz not given")
    if not opt.dst:
        parser.error("dst not given")

    if opt.offset:
        offset = opt.offset
    elif opt.preset and opt.preset == "beatoraja":
        offset = 95
    elif opt.preset and opt.preset == "bemuse":
        offset = 5

    """Mania chart processing"""
    # get raw data of beatmap
    dstfolder = unzip_osz(opt.osz, opt.dst)
    LOGGER.info(dstfolder)
    for file in glob.glob(f"{dstfolder}/*.osu"):
        convert_mania_chart(file, dstfolder, offset)
