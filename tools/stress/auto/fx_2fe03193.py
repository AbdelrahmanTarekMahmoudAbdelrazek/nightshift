# Night Shift lab fixture builder for 2fe03193 (try 2)

import os, re

def _fx_2fe03193_note(ed, msg):
    # Not dev.marker: require_log/wait_log skip ZSTRESS lines, so the proof must use another tag
    ed.dev.sh("log -t NSFX '" + msg.replace("'", "") + "'")

@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_fx(ed, r):
    """Fixture for Crashlytics/Play [libmedia.so] AudioMCDecoder::reset_state SIGSEGV (cached reverse with no audio)."""
    ed.fixture_begin()
    mark = ed.log_mark()
    # One clip WITH audio at a durable path (not cache/): a new clean project from a fresh copy of a phone video
    ed.new_project(tag='fx2fe03193', duration_s=30)
    src = ed.dev.sh('ls -t /sdcard/DCIM/NightShift/ns_fresh_*_fx2fe03193.mp4 2>/dev/null | head -1').strip()
    if not src:
        raise UIError('fresh source clip for the fixture not found on the phone')
    # The clip's photoUri: the first-import MsgAddVideo on layer 0 (a transcode -> files/outputs/transcoding-N.mp4,
    # a pass -> the source path). Reverse caches its output at cacheDir/<basename of photoUri>.
    line = ed.wait_log(r'MsgAddVideo: media_layer 0 path: \S+', 15, since=mark)
    names = []
    if line:
        p = re.search(r'path: (\S+?),?\s', line + ' ').group(1).rstrip(',')
        names.append(os.path.basename(p))
    if os.path.basename(src) not in names:
        names.append(os.path.basename(src))
    ed.step('clip photoUri candidates: ' + ', '.join(names))
    if any('/cache/' in n for n in names):
        raise UIError('fixture clip points into cache/: it would not survive a snapshot restore')

    # Checkpoint 1: a reversed copy with only video is already in cacheDir under that name (an earlier Reverse made it)
    for n in names:
        since = ed.log_mark()
        size = ed.dev.plant_app_file(src, 'cache/' + n, video_only=True, min_bytes=50000)
        _fx_2fe03193_note(ed, f'2fe03193 planted cache/{n} {size} bytes video-only')
        ed.require_log(r'2fe03193 planted cache/\S+\.mp4 \d+ bytes video-only', 10, since=since,
                       why='cached reversed copy (no audio track) is in cacheDir under the clip file name')

    # Checkpoint 2: the project's only clip is the ORIGINAL with audio (no 'no audio' from its decoder)
    if ed.wait_log(r'-Error-Audio-Constructor- no audio', 3, since=mark):
        raise UIError('the fixture clip itself has no audio track: pick a source video with audio')
    ed.settle(2)
    ed.save_fixture('2fe03193', 'one clip WITH audio (photoUri outside cache/) on layer 0, not reversed; '
                    'cache/<clip file name> holds a video-only reversed copy so Reverse takes the cached branch')
