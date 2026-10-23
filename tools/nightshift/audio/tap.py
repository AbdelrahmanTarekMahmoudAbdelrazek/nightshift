"""Add the Audio Check mixer tap to a CHECKOUT (a throwaway worktree, never the working copy, never committed).

The tap writes every exported mixer block to files/aud_dump_mix.f32 (raw f32le, stereo, 44100) and logs
"AUD split at <s>" at every media change on layer 0, timed in dump frames during export. Same tap as the PR #3132
audio handoff, section 1. Branches that already carry it are left alone. Returns a short note."""
import re
import sys

REL = 'app/src/main/cpp/audio/AudioTimeline/AudioTimeline.cpp'
VERSION = 'tap1'          # part of the APK cache key: bump when the tap changes

STATICS = ('static long long aud_dump_frames  = 0;   /// Audio Check tap: frames written to the dump so far\n'
           'static int       aud_prev_media   = -1;  /// Audio Check tap: last media id seen on layer 0\n')
SPLIT = ('            if (media_id != aud_prev_media) {   // Audio Check tap: seam times\n'
         '                double split_s = in_export ? (double)aud_dump_frames / 44100.0 : (double)pts / 1000000.0;\n'
         '                if (aud_prev_media >= 0) { LOGE("AUD split at %.4f s", split_s); }\n'
         '                aud_prev_media = media_id;\n'
         '            }\n')
TAP = ('    auto aud_out = _mixer->get_frame(int(num_samples), used_layers, pts);   // Audio Check tap\n'
       '    if (in_export && aud_out) {\n'
       '        static FILE* aud_dump = fopen("/data/user/0/com.myzesty/files/aud_dump_mix.f32", "wb");\n'
       '        if (aud_dump) {\n'
       '            const int n = aud_out->get_num_samples();\n'
       '            fwrite(aud_out->get_buffer(), sizeof(float), n, aud_dump);\n'
       '            fflush(aud_dump);\n'
       '            aud_dump_frames += n / 2;\n'
       '        }\n'
       '    }\n'
       '    return aud_out;\n')


def apply(root):
    path = f'{root}/{REL}'
    s = open(path).read()
    notes = []
    if '<cstdio>' not in s:
        s = s.replace('#include "AudioTimeline.h"\n', '#include "AudioTimeline.h"\n#include <cstdio>\n', 1)
    if 'aud_dump_frames' not in s:
        m = re.search(r'#define FULL_FUNC_NAME', s) or re.search(r'\nAudioTimeline::AudioTimeline\(', s)
        if not m:
            raise RuntimeError('tap: no place for the tap counters in AudioTimeline.cpp')
        s = s[:m.start()] + STATICS + s[m.start():]
        notes.append('counters')
    elif 'aud_prev_media' not in s:
        s = s.replace('static long long aud_dump_frames', STATICS.splitlines()[1] + '\nstatic long long aud_dump_frames', 1)
    if 'AUD split at' not in s:
        m = re.search(r'\n([ \t]*)current_base_media_id = media_id;[^\n]*\n', s)
        if not m:
            raise RuntimeError('tap: anchor "current_base_media_id = media_id;" not found (seam log)')
        s = s[:m.end()] + SPLIT + s[m.end():]
        notes.append('seam log')
    if 'aud_dump_mix' not in s:
        m = re.search(r'\n[ \t]*return\s+_mixer->get_frame\(\s*int\(num_samples\)\s*,\s*used_layers\s*,\s*pts\s*\);[^\n]*\n', s)
        if not m:
            raise RuntimeError('tap: anchor "return _mixer->get_frame(int(num_samples),used_layers,pts);" not found')
        s = s[:m.start()] + '\n' + TAP + s[m.end():]
        notes.append('dump')
    open(path, 'w').write(s)
    return 'tap added (' + ', '.join(notes) + ')' if notes else 'tap already in this branch'


if __name__ == '__main__':
    print(apply(sys.argv[1]))
