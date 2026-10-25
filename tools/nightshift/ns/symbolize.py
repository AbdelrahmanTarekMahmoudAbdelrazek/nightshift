"""Native symbolization for Crashlytics frames that arrive as (library, address) only.

Symbol store: tools/nightshift/symbols/<versionCode>/<lib>.so (+ meta.json with the GNU BuildId).
Fill it with `sentinel.py symbols add <apk|aab|.so|dir> --version-code 800054867`.
Lookup order per frame: .symtab (unstripped build) -> .dynsym (exported names survive stripping, which is how the
device tombstone shows names) -> llvm-addr2line / addr2line for file:line when debug info is present.
Pure-Python ELF reader; demangling via c++filt / llvm-cxxfilt when available.
"""
import bisect
import json
import os
import time
import re
import shutil
import struct
import subprocess
import zipfile

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
STORE = os.path.join(HERE, 'symbols')


class Elf:
    def __init__(self, path):
        self.path = path
        self.d = open(path, 'rb').read()
        if self.d[:4] != b'\x7fELF':
            raise ValueError(f'not an ELF file: {path}')
        self.is64 = self.d[4] == 2
        self.sections = self._sections()

    def _sections(self):
        d, u = self.d, struct.unpack_from
        if self.is64:
            shoff, = u('<Q', d, 0x28); shentsize, shnum, shstrndx = u('<HHH', d, 0x3A)
        else:
            shoff, = u('<I', d, 0x20); shentsize, shnum, shstrndx = u('<HHH', d, 0x2E)
        raw = []
        for i in range(shnum):
            o = shoff + i * shentsize
            if self.is64:
                name, typ = u('<II', d, o); addr, off, size = u('<QQQ', d, o + 0x10); link, = u('<I', d, o + 0x28); entsize, = u('<Q', d, o + 0x38)
            else:
                name, typ = u('<II', d, o); addr, off, size = u('<III', d, o + 0x0C); link, = u('<I', d, o + 0x18); entsize, = u('<I', d, o + 0x24)
            raw.append(dict(name=name, type=typ, addr=addr, off=off, size=size, link=link, entsize=entsize))
        strtab = raw[shstrndx] if shstrndx < len(raw) else None
        for s in raw:
            s['sname'] = self._cstr(strtab['off'] + s['name']) if strtab else ''
        return raw

    def _cstr(self, off):
        end = self.d.find(b'\0', off)
        return self.d[off:end].decode('utf-8', 'replace')

    def build_id(self):
        for s in self.sections:
            if s['type'] == 7:
                p, end = s['off'], s['off'] + s['size']
                while p + 12 <= end:
                    nsz, dsz, nt = struct.unpack_from('<III', self.d, p)
                    desc = p + 12 + ((nsz + 3) & ~3)
                    if nt == 3 and self.d[p + 12:p + 12 + nsz].startswith(b'GNU'):
                        return self.d[desc:desc + dsz].hex()
                    p = desc + ((dsz + 3) & ~3)
        return None

    def symbols(self):
        """[(addr, size, name)] from .symtab, else .dynsym; functions only."""
        out = []
        for want in ('.symtab', '.dynsym'):
            for s in self.sections:
                if s['sname'] != want or not s['entsize']:
                    continue
                strs = self.sections[s['link']]
                n = s['size'] // s['entsize']
                for i in range(n):
                    o = s['off'] + i * s['entsize']
                    if self.is64:
                        name, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', self.d, o)
                    else:
                        name, value, size, info, other, shndx = struct.unpack_from('<IIIBBH', self.d, o)
                    if (info & 0xF) == 2 and value and shndx:
                        out.append((value & ~1, size, self._cstr(strs['off'] + name)))
            if out:
                return sorted(out), want
        return [], None


def demangle(names):
    tool = shutil.which('llvm-cxxfilt') or shutil.which('c++filt')
    if not tool or not names:
        return names
    try:
        res = subprocess.run([tool], input='\n'.join(names), capture_output=True, text=True, timeout=30)
        out = res.stdout.splitlines()
        return out if len(out) == len(names) else names
    except Exception:
        return names


class Symbolizer:
    def __init__(self, so_path):
        self.elf = Elf(so_path)
        self.syms, self.table = self.elf.symbols()
        self.addrs = [a for a, _, _ in self.syms]
        self.a2l = _addr2line()

    def lookup(self, offsets):
        raw = []
        for off in offsets:
            i = bisect.bisect_right(self.addrs, off) - 1
            if i >= 0:
                a, size, name = self.syms[i]
                if (size and off < a + size) or (not size and off - a < 0x200):
                    raw.append((name, off - a))
                    continue
            raw.append((None, None))
        names = demangle([n for n, _ in raw if n])
        it = iter(names)
        out = [(next(it), d) if n else (None, None) for n, d in raw]
        lines = self._lines(offsets) if self.table == '.symtab' and self.a2l else [None] * len(offsets)
        return [{'func': f'{n} + {d}' if n else None, 'srcline': l} for (n, d), l in zip(out, lines)]

    def _lines(self, offsets):
        """file:line per offset. With inlining (-i) the innermost line is often a libc++ header (unique_ptr.h); the
        first line in OUR source wins, made repo-relative (app/src/main/cpp/...)."""
        if not offsets:
            return []
        try:
            res = subprocess.run([self.a2l, '-a', '-i', '-e', self.elf.path, *[hex(o) for o in offsets]],
                                 capture_output=True, text=True, timeout=180)
        except Exception:
            return [None] * len(offsets)
        blocks, cur = [], None
        for l in res.stdout.splitlines():
            if re.match(r'^0x[0-9a-f]+$', l.strip()):
                cur = []
                blocks.append(cur)
            elif cur is not None and l.strip() and '??' not in l:
                cur.append(l.strip().split(' (discriminator')[0])
        if len(blocks) != len(offsets):
            return [None] * len(offsets)
        out = []
        for b in blocks:
            ours = [x for x in b if '/app/src/main/cpp/' in x or '/extra/' in x]
            pick = ours[0] if ours else (b[0] if b else None)
            if pick and '/video_gles3jni/' in pick:
                pick = pick.split('/video_gles3jni/', 1)[1]
            out.append(pick)
        return out


# ---------------------------------------------------------------- store

def store_path(version_code, lib):
    return os.path.join(STORE, str(version_code), lib)


def add(src, version_code, lib='libMYJNILIB26.so', abi='arm64-v8a', version_name=None):
    os.makedirs(os.path.join(STORE, str(version_code)), exist_ok=True)
    dst = store_path(version_code, lib)
    if os.path.isdir(src):
        cands = [os.path.join(r, f) for r, _, fs in os.walk(src) for f in fs if f == lib and abi in r]
        if not cands:
            raise SystemExit(f'no {abi}/{lib} under {src}')
        src = max(cands, key=lambda p: Elf(p).symbols()[1] == '.symtab')
        shutil.copy(src, dst)
    elif zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            member = next((m for m in z.namelist() if m.endswith(f'{abi}/{lib}')), None)
            if not member:
                raise SystemExit(f'{abi}/{lib} not found in {src}')
            open(dst, 'wb').write(z.read(member))
    else:
        shutil.copy(src, dst)
    e = Elf(dst)
    syms, table = e.symbols()
    meta = {'version_code': str(version_code), 'version_name': version_name, 'lib': lib, 'build_id': e.build_id(), 'table': table, 'functions': len(syms), 'source': os.path.abspath(src)}
    json.dump(meta, open(os.path.join(STORE, str(version_code), 'meta.json'), 'w'), indent=1)
    return meta


def _addr2line():
    import glob
    from . import config as _cfg
    ndk = sorted(glob.glob(os.path.join(_cfg.android_sdk(), 'ndk/*/toolchains/llvm/prebuilt/*/bin/llvm-addr2line')) +
                 glob.glob(os.path.join(os.environ.get('ANDROID_NDK_HOME', '/nonexistent'), 'toolchains/llvm/prebuilt/*/bin/llvm-addr2line')))
    return shutil.which('llvm-addr2line') or (ndk[-1] if ndk else None) or shutil.which('addr2line')


def resolve(version_code, version_name, native_lib):
    """Exact versionCode first (its full debug symbols if imported); else another build of the same versionName."""
    p = store_path(version_code, native_lib)
    if os.path.exists(p + '.dbg'):
        return p + '.dbg', False
    if os.path.exists(p):
        try:                                      # another build with the SAME BuildId = byte-identical lib: its symbols fit
            import glob
            bid = json.load(open(os.path.join(os.path.dirname(p), 'meta.json'))).get('build_id')
            for meta in glob.glob(os.path.join(STORE, '*', 'meta.json')):
                m = json.load(open(meta))
                q = store_path(m.get('version_code'), native_lib) + '.dbg'
                if bid and m.get('debug_build_id') == bid and os.path.exists(q):
                    return q, False
        except Exception:
            pass
        return p, False
    import glob
    for meta in glob.glob(os.path.join(STORE, '*', 'meta.json')):
        m = json.load(open(meta))
        if version_name and m.get('version_name') == version_name and os.path.exists(store_path(m['version_code'], native_lib)):
            return store_path(m['version_code'], native_lib), True
    return None, False


def _via_host(frames, version_code, native_lib, version_name):
    """No symbols for this build on this computer (a teammate's): the board host names the pcs (relay), cached here."""
    idx = [i for i, f in enumerate(frames) if f.get('lib') == native_lib and not f.get('func') and f.get('address')]
    if not idx:
        return frames, False
    cf = os.path.join(STORE, '_from_host', f'{version_code}_{native_lib}.json')
    try:
        cache = json.load(open(cf))
    except (OSError, ValueError):
        cache = {}
    ask = sorted({int(frames[i]['address']) for i in idx} - {int(k) for k in cache})
    if ask:
        if getattr(_via_host, 'down_until', 0) > time.time():
            return frames, False                    # the host did not answer a minute ago: do not wait again for every event
        try:
            from . import relay
            res = relay.symbolize(ask, version_code, version_name, native_lib)
            cache.update({str(a): r for a, r in zip(ask, res)})
            os.makedirs(os.path.dirname(cf), exist_ok=True)
            json.dump(cache, open(cf, 'w'))
        except Exception:
            _via_host.down_until = time.time() + 120
            return frames, False
    for i in idx:
        r = cache.get(str(int(frames[i]['address']))) or {}
        if r.get('func'):
            frames[i]['func'] = r['func']
            frames[i]['srcline'] = r.get('srcline')
            frames[i]['named_by'] = r.get('named_by') or 'board-host'
            if r.get('assumed_lib'):
                frames[i]['assumed_lib'] = True
    return frames, True


def symbolize_frames(frames, version_code, native_lib, version_name=None, relay_ok=True):
    p, assumed = resolve(version_code, version_name, native_lib)
    if relay_ok and (not p or not p.endswith('.dbg') or assumed) and not _host_here():
        try:                                        # a teammate's computer: the build's symbols from the team's GitHub, once
            from . import symshare
            if symshare.fetch(version_code):
                p, assumed = resolve(version_code, version_name, native_lib)
        except Exception:
            pass
    if not p or (relay_ok and not p.endswith('.dbg') and not _host_here()):
        if relay_ok and not _host_here():           # the host has the full debug symbols (.aab): ask it first
            fr, did = _via_host(frames, version_code, native_lib, version_name)
            if did and not p:
                return fr, did
        if not p:
            return frames, False
    sym = Symbolizer(p)
    idx = [i for i, f in enumerate(frames) if f.get('lib') == native_lib and not f.get('func') and f.get('address')]
    res = sym.lookup([int(frames[i]['address']) for i in idx])
    for i, r in zip(idx, res):
        if r['func']:
            frames[i]['func'] = r['func']
            frames[i]['srcline'] = r['srcline']
            if assumed:
                frames[i]['assumed_lib'] = True
    # internal (non-exported) functions are not in .dynsym; Google Play symbolizes them with the uploaded
    # native-debug-symbols, so reuse Play's names for the same BuildId + pc (pcmap.json, filled by merge.py)
    try:
        bid = json.load(open(os.path.join(os.path.dirname(p), 'meta.json'))).get('build_id', '')[:16]   # same for .so and .dbg
        pm = load_pcmap().get(bid) or {}
        for i in idx:
            if not frames[i].get('func'):
                fn = pm.get('0x%x' % int(frames[i]['address']))
                if fn:
                    frames[i]['func'] = fn
                    frames[i]['named_by'] = 'google-play'
    except Exception:
        pass
    return frames, bool(idx)


def _host_here():
    """True on the board host (it keeps the symbol store); False on a teammate's computer."""
    try:
        from . import config as _c
        return bool(((_c.load() or {}).get('worker') or {}).get('serve_others')) or not ((_c.load() or {}).get('worker') or {}).get('owner')
    except Exception:
        return True


PCMAP = os.path.join(STORE, 'pcmap.json')


def load_pcmap():
    try:
        return json.load(open(PCMAP))
    except Exception:
        return {}


def add_pcmap(entries):
    """entries: iterable of (build_id, pc_hex, func). Returns how many new pcs were learned."""
    pm, new = load_pcmap(), 0
    for bid, pc, fn in entries:
        if bid and pc and fn:
            d = pm.setdefault(bid[:16], {})
            if pc not in d:
                new += 1
            d[pc] = fn
    os.makedirs(STORE, exist_ok=True)
    json.dump(pm, open(PCMAP, 'w'), indent=0, sort_keys=True)
    return new


def add_debug(src, version_code, lib='libMYJNILIB26.so', abi='arm64-v8a'):
    """Import full debug symbols for one build from the Play .aab (BUNDLE-METADATA/.../debugsymbols/<abi>/<lib>.dbg|.sym)
    or a native-debug-symbols.zip (<abi>/<lib>.dbg). Kept next to the stripped .so as <lib>.dbg; the BuildId must match
    the build's own .so, so a symbols file from another build can never be used by mistake."""
    d = os.path.join(STORE, str(version_code))
    meta_p = os.path.join(d, 'meta.json')
    meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        member = next((m for m in names if m.endswith(f'{abi}/{lib}.dbg')), None) or \
            next((m for m in names if m.endswith(f'{abi}/{lib}.sym')), None)
        if not member:
            raise SystemExit(f'no {abi}/{lib}.dbg or .sym in {src}')
        os.makedirs(d, exist_ok=True)
        tmp = store_path(version_code, lib) + '.dbg.tmp'
        with z.open(member) as fi, open(tmp, 'wb') as fo:
            shutil.copyfileobj(fi, fo, 1 << 20)
    e = Elf(tmp)
    bid = e.build_id()
    if meta.get('build_id') and bid and meta['build_id'] != bid:
        os.remove(tmp)
        raise SystemExit(f'BuildId mismatch: {src} has {bid}, build {version_code} has {meta["build_id"]}: not this build')
    os.replace(tmp, store_path(version_code, lib) + '.dbg')
    syms, table = e.symbols()
    meta.update({'debug_symbols': os.path.abspath(src), 'debug_member': member, 'debug_table': table,
                 'debug_functions': len(syms), 'debug_build_id': bid})
    json.dump(meta, open(meta_p, 'w'), indent=1)
    return meta


def auto_import_debug(version_codes, lib='libMYJNILIB26.so', log=print):
    """Each sync: for builds without full symbols, look in Downloads for <vc>*.aab or native-debug-symbols*<vc>*.zip."""
    import glob
    for vc in version_codes:
        if os.path.exists(store_path(vc, lib) + '.dbg'):
            continue
        for pat in (f'~/Downloads/{vc}*.aab', f'~/Downloads/*native-debug-symbols*{vc}*.zip', f'~/mnt/Downloads/{vc}*.aab'):
            for f in glob.glob(os.path.expanduser(pat)):
                try:
                    m = add_debug(f, vc, lib)
                    log(f'symbols: imported full debug symbols for {vc} from {os.path.basename(f)} '
                        f'({m["debug_functions"]} functions, {m["debug_table"]})')
                    break
                except (SystemExit, Exception) as e:
                    log(f'symbols: {os.path.basename(f)} not usable for {vc}: {str(e)[:150]}')
            if os.path.exists(store_path(vc, lib) + '.dbg'):
                break
