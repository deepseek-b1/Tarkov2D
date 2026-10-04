#!/usr/bin/env python3
"""Fail the build if the APK contains a shared library that Android cannot load.

Why this exists
---------------
Android's linker resolves every relocation when it dlopen()s a library.  A
single undefined symbol therefore does not degrade gracefully - the whole
module fails to load:

    ImportError: dlopen failed: cannot locate symbol "<name>"
                 referenced by ".../pygame/surface.so"

pygame/__init__.py imports pygame.surface at startup, so one unresolved pygame
symbol is enough to make the app die instantly on launch with no error dialog.
That is exactly what Tarkov2D 1.0.8 shipped: surface.so referenced
pg_avx2_at_runtime_but_uncompiled, which no library in the APK defined.  The
old CI check only looked for two hard-coded symbol names in surface.so and
missed it.

This check is generic: for every shared library inside the APK - including the
ones packed into p4a's libpybundle.so (a gzipped tar despite the .so name) - it
collects the undefined symbols and verifies that each one is provided by
another library in the same APK or by something Android guarantees
(libc/libm/libdl/liblog/libz/...).  Anything left over is a build failure.

Usage:
    python tools/check_android_symbols.py bin/tarkov2d-*-debug.apk
"""
import gzip
import io
import os
import struct
import sys
import tarfile
import zipfile

SHT_DYNSYM = 11
SHN_UNDEF = 0

# e_machine values we care about: the APK is arm64-v8a only.
EM_AARCH64 = 183
ARCH_NAMES = {183: "aarch64 (arm64-v8a)", 62: "x86_64", 40: "arm (armeabi-v7a)",
              3: "i386"}

# Symbols the platform always provides at runtime, even though they are not
# visible in the APK itself.  Anything here may stay undefined.
PLATFORM_LIBS = {
    "libc.so", "libm.so", "libdl.so", "liblog.so", "libz.so", "libandroid.so",
    "libGLESv2.so", "libEGL.so", "libGLESv1_CM.so", "libstdc++.so",
    "libc++_shared.so", "libOpenSLES.so", "libaaudio.so", "libjnigraphics.so",
    "libnativewindow.so", "libsync.so", "libvulkan.so", "libhidapi.so",
    "libcutils.so", "libutils.so", "libui.so", "libgui.so", "libbinder.so",
}

# Libraries that ship inside the APK are fine too; their exported symbols count.
# Everything else must be resolved inside the APK.


def elf_symbols(data):
    """-> (defined, undefined, needed) name lists for an ELF64 shared object."""
    if data[:4] != b"\x7fELF" or data[4] != 2:
        raise ValueError("not an ELF64 file")
    e_machine, = struct.unpack_from("<H", data, 18)
    e_machine, = struct.unpack_from("<H", data, 18)
    e_shoff, = struct.unpack_from("<Q", data, 0x28)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x3a)
    secs = []
    for i in range(e_shnum):
        o = e_shoff + i * 64
        _, typ = struct.unpack_from("<II", data, o)
        _flags, _addr, off, size = struct.unpack_from("<QQQQ", data, o + 8)
        link, _info, _align, _entsize = struct.unpack_from("<IIQQ", data, o + 40)
        secs.append((typ, off, size, link))

    defined, undef, needed = [], [], []
    for (typ, off, size, link) in secs:
        if typ == SHT_DYNSYM:
            ltyp, loff, lsize, _ = secs[link]
            strs = data[loff:loff + lsize]
            for i in range(size // 24):
                nm, info, other, shndx, val, sz = struct.unpack_from(
                    "<IBBHQQ", data, off + i * 24)
                if nm == 0:
                    continue
                end = strs.find(b"\x00", nm)
                name = strs[nm:end].decode("latin1")
                (undef if shndx == SHN_UNDEF else defined).append(name)
        elif typ == 6:  # SHT_DYNAMIC
            _ltyp, loff, lsize, _ = secs[link]
            strs = data[loff:loff + lsize]
            for i in range(size // 16):
                tag, val = struct.unpack_from("<qQ", data, off + i * 16)
                if tag == 1:  # DT_NEEDED
                    end = strs.find(b"\x00", val)
                    needed.append(strs[val:end].decode("latin1"))
    return e_machine, defined, undef, needed


def read_pybundle(blob):
    """p4a packs the python bundle into libpybundle.so, which is really a
    gzipped tar.  -> {member name: bytes} for every .so inside."""
    out = {}
    try:
        data = gzip.GzipFile(fileobj=io.BytesIO(blob)).read()
    except OSError:
        return out
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf.getmembers():
            if m.isfile() and m.name.endswith(".so"):
                f = tf.extractfile(m)
                if f is not None:
                    out[m.name] = f.read()
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    apk_path = sys.argv[1]
    if not os.path.exists(apk_path):
        print("!! apk not found: %s" % apk_path)
        return 2

    z = zipfile.ZipFile(apk_path)
    top_defined, top_needed, modules = set(), set(), {}
    wrong_arch = []

    for info in z.infolist():
        if not info.filename.startswith("lib/") or not info.filename.endswith(".so"):
            continue
        blob = z.read(info.filename)
        if blob[:4] != b"\x7fELF":
            # p4a's python bundle: many more shared objects hide in here
            modules.update(read_pybundle(blob))
            continue
        try:
            machine, d, u, n = elf_symbols(blob)
        except ValueError as exc:
            print("!! %s: %s" % (info.filename, exc))
            return 1
        if machine != EM_AARCH64:
            wrong_arch.append((info.filename, machine))
        top_defined |= set(d)
        top_needed |= set(n)
        modules[info.filename] = blob

    if not modules:
        print("!! no shared libraries found in %s" % apk_path)
        return 1

    available = set(top_defined)
    loaded = set(top_needed) | PLATFORM_LIBS
    undef_by_module = {}
    for name, blob in modules.items():
        try:
            machine, d, u, _ = elf_symbols(blob)
        except ValueError:
            continue
        if machine != EM_AARCH64:
            wrong_arch.append((name, machine))
        available |= set(d)
        undef_by_module[name] = sorted(set(u))

    print("APK            : %s" % apk_path)
    print("shared objects : %d (%d loose, rest inside libpybundle.so)"
          % (len(modules), sum(1 for n in modules if n.startswith("lib/"))))
    print("DT_NEEDED      : %s" % ", ".join(sorted(loaded - PLATFORM_LIBS)))

    for name, machine in wrong_arch:
        print("!! %s is %s, not aarch64 - the phone cannot load it"
              % (name, ARCH_NAMES.get(machine, "ELF machine %d" % machine)))

    missing_libs = sorted(lib for lib in loaded
                          if lib not in PLATFORM_LIBS
                          and lib not in {os.path.basename(n) for n in modules})
    for lib in missing_libs:
        print("!! DT_NEEDED %s is not part of the APK and not a platform library" % lib)

    unresolved = {}
    for name, undef in undef_by_module.items():
        left = [s for s in undef if s not in available]
        if left:
            unresolved[name] = left

    # Every library here is linked against the NDK sysroot, so a pile of libc /
    # libm / libdl / liblog / libz symbols legitimately stays undefined: the OS
    # provides them.  What must NEVER be undefined is a symbol that belongs to a
    # library that ships *inside* this APK - pygame's C internals, SDL, or the
    # CPython C-API.  Those are exactly the ones that break dlopen().
    MUST_RESOLVE = ("pg_", "blit_", "alphablit", "_PGSLOTS", "_pg",
                    "SDL_", "SDL", "Py", "_Py")

    must_fix, platform_syms = {}, []
    for name, syms in unresolved.items():
        bad = [s for s in syms if s.startswith(MUST_RESOLVE)]
        if bad:
            must_fix[name] = bad
        platform_syms += [s for s in syms if s not in bad]

    print("platform-provided undefined symbols (libc/libm/libdl/liblog/libz): %d"
          % len(platform_syms))

    if must_fix:
        print("\n!! UNRESOLVED APK-INTERNAL SYMBOLS - these libraries cannot be")
        print("!! dlopen()ed on the device:")
        for name, syms in sorted(must_fix.items()):
            for s in syms:
                print("     %-70s <- %s" % (s, name))
        print("\n!! The phone will show 'dlopen failed: cannot locate symbol' and")
        print("!! the app will close immediately.  pygame symbols: give them weak")
        print("!! definitions in p4a-recipes/pygame/__init__.py (see AVX2_STUBS).")

    if must_fix or missing_libs or wrong_arch:
        print("\nRESULT: FAIL")
        return 1
    print("\nRESULT: PASS - every library in the APK can be loaded on device")
    return 0


if __name__ == "__main__":
    sys.exit(main())
