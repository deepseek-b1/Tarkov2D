"""
Project-local pygame recipe for Tarkov2D (based on p4a's official recipe).

Why this file exists
--------------------
The pygame built by p4a's stock recipe crashes on arm64 at runtime:

    ImportError: dlopen failed: cannot locate symbol
    "alphablit_alpha_sse2_argb_surf_alpha" referenced by ".../pygame/surface.so"

That symbol is an x86 SSE2-only SIMD blitter (note the "sse2" in the name).
p4a's cross-compile setup ends up linking x86 SIMD blitters into the arm64
build, so surface.so cannot be loaded, pygame.display becomes unavailable,
and the game dies in pygame.display.set_mode() with exit status 255.

Fix: build with the SIMD blitter path disabled so pygame uses plain C code.
This is the ONLY difference from the upstream recipe.
"""
import os
import re
from os.path import exists, join

from pythonforandroid.recipe import CompiledComponentsPythonRecipe
from pythonforandroid.toolchain import current_directory

# AVX2 blitters declared in simd_blitters.h but never defined on aarch64
AVX2_SYMBOLS = [
    "blit_blend_rgba_mul_avx2", "blit_blend_rgb_mul_avx2",
    "blit_blend_rgba_add_avx2", "blit_blend_rgb_add_avx2",
    "blit_blend_rgba_sub_avx2", "blit_blend_rgb_sub_avx2",
    "blit_blend_rgba_max_avx2", "blit_blend_rgb_max_avx2",
    "blit_blend_rgba_min_avx2", "blit_blend_rgb_min_avx2",
]


class Pygame2Recipe(CompiledComponentsPythonRecipe):
    version = '2.5.2'
    url = 'https://github.com/pygame/pygame/archive/{version}.tar.gz'

    site_packages_name = 'pygame'
    name = 'pygame'

    depends = ['sdl2', 'sdl2_image', 'sdl2_mixer', 'sdl2_ttf', 'setuptools', 'jpeg', 'png']
    call_hostpython_via_targetpython = False  # Due to setuptools
    install_in_hostpython = False

    def prebuild_arch(self, arch):
        super().prebuild_arch(arch)
        with current_directory(self.get_build_dir(arch.arch)):
            setup_template = open(join("buildconfig", "Setup.Android.SDL2.in")).read()
            # ==== FIX 1: the template omits src_c/simd_blitters_sse2.c ====
            # Setup.Android.SDL2.in lists only
            #     surface src_c/surface.c src_c/alphablit.c src_c/surface_fill.c
            # but alphablit.c calls alphablit_alpha_sse2_argb_surf_alpha(),
            # which is defined in src_c/simd_blitters_sse2.c (it uses
            # include/sse2neon.h on aarch64, so it builds fine on arm64).
            # Without it surface.so has an undefined symbol and the phone
            # cannot dlopen it:
            #     cannot locate symbol "alphablit_alpha_sse2_argb_surf_alpha"
            setup_template = setup_template.replace(
                "surface src_c/surface.c src_c/alphablit.c src_c/surface_fill.c",
                "surface src_c/surface.c src_c/alphablit.c src_c/surface_fill.c "
                "src_c/simd_blitters_sse2.c",
            )
            # ==== FIX 2: neutralise the AVX2 entry points ====
            # simd_blitters.h declares the AVX2 helpers *outside* any guard and
            # alphablit.c calls pg_has_avx2() unconditionally, but aarch64 has
            # no AVX2, so src_c/simd_blitters_avx2.c never ends up defining
            # them for our build -> another undefined symbol:
            #     cannot locate symbol "pg_has_avx2"
            # Turning the declarations into inline stubs removes the references
            # and makes the AVX2 code paths unreachable (which is correct on
            # arm64: they can never be taken).
            hdr_path = join("src_c", "simd_blitters.h")
            text = open(hdr_path).read()
            changed = False
            for name in AVX2_SYMBOLS:
                # strip the plain declaration (possibly split over two lines as
                # "void\nblit_..._avx2(SDL_BlitInfo *info);")
                pattern = re.compile(
                    r"(?:void|int)\s*\n?\s*%s\s*\(SDL_BlitInfo \*info\)\s*;" % re.escape(name)
                )
                text, n = pattern.subn("", text)
                changed = changed or bool(n)
            text, n = re.subn(r"(?:void|int)\s*\n?\s*pg_has_avx2\s*\(\s*\)\s*;", "", text)
            changed = changed or bool(n)

            if "static inline int pg_has_avx2" not in text:
                stubs = ["static inline int pg_has_avx2(void) { return 0; }"]
                stubs += [
                    "static inline void %s(SDL_BlitInfo *info) { (void)info; }" % n
                    for n in AVX2_SYMBOLS
                ]
                text += "\n/* arm64 stubs added by the Tarkov2D recipe */\n" + "\n".join(stubs) + "\n"
                changed = True
            if changed:
                open(hdr_path, "w").write(text)
                print("[pygame-recipe] patched simd_blitters.h: AVX2 entries stubbed out for arm64")
            env = self.get_recipe_env(arch)
            env['ANDROID_ROOT'] = join(self.ctx.ndk.sysroot, 'usr')

            png = self.get_recipe('png', self.ctx)
            png_lib_dir = join(png.get_build_dir(arch.arch), '.libs')
            png_inc_dir = png.get_build_dir(arch)

            jpeg = self.get_recipe('jpeg', self.ctx)
            jpeg_inc_dir = jpeg_lib_dir = jpeg.get_build_dir(arch.arch)

            sdl_mixer_includes = ""
            sdl2_mixer_recipe = self.get_recipe('sdl2_mixer', self.ctx)
            for include_dir in sdl2_mixer_recipe.get_include_dirs(arch):
                sdl_mixer_includes += f"-I{include_dir} "

            sdl2_image_includes = ""
            sdl2_image_recipe = self.get_recipe('sdl2_image', self.ctx)
            for include_dir in sdl2_image_recipe.get_include_dirs(arch):
                sdl2_image_includes += f"-I{include_dir} "

            setup_file = setup_template.format(
                sdl_includes=(
                    " -I" + join(self.ctx.bootstrap.build_dir, 'jni', 'SDL', 'include') +
                    " -L" + join(self.ctx.bootstrap.build_dir, "libs", str(arch)) +
                    " -L" + png_lib_dir + " -L" + jpeg_lib_dir + " -L" + arch.ndk_lib_dir_versioned),
                sdl_ttf_includes="-I"+join(self.ctx.bootstrap.build_dir, 'jni', 'SDL2_ttf'),
                sdl_image_includes=sdl2_image_includes,
                sdl_mixer_includes=sdl_mixer_includes,
                jpeg_includes="-I"+jpeg_inc_dir,
                png_includes="-I"+png_inc_dir,
                freetype_includes=""
            )
            open("Setup", "w").write(setup_file)
            self._fix_missing_simd_blitters()

    def _fix_missing_simd_blitters(self):
        """
        Fix the arm64 crash caused by pygame 2.5.2's own build config.

        pygame's sources do this on aarch64 (see src_c/simd_blitters.h):

            #if !defined(PG_ENABLE_ARM_NEON) && defined(__aarch64__)
            #define PG_ENABLE_ARM_NEON 1
            #endif
            #if (defined(__SSE2__) || defined(PG_ENABLE_ARM_NEON))
                void alphablit_alpha_sse2_argb_surf_alpha(SDL_BlitInfo *info);

        but pygame's Setup.Android.SDL2.in never compiles
        src_c/simd_blitters_sse2.c, so that declared function is never defined.
        surface.so ends up with an undefined symbol and cannot be dlopen'ed:

            ImportError: dlopen failed: cannot locate symbol
            "alphablit_alpha_sse2_argb_surf_alpha"

        Fix: compile src_c/simd_blitters_sse2.c into the surface module.
        On aarch64 it pulls in include/sse2neon.h (SSE2 -> NEON translation),
        so it builds fine on arm64.
        """
        if not exists("Setup"):
            return
        with open("Setup") as f:
            text = f.read()

        if "simd_blitters_sse2.c" in text:
            return  # already patched (prebuild_arch can run more than once)

        lines = text.split("\n")
        out = []
        patched_surface = False
        for line in lines:
            out.append(line)
            # the surface module's source list starts with surface.c
            if not patched_surface and line.strip().startswith("surface.c"):
                indent = line[: len(line) - len(line.lstrip())]
                out.append(indent + "src_c/simd_blitters_sse2.c")
                patched_surface = True

        if not patched_surface:
            # fall back: append a dedicated module so the symbol is defined
            # somewhere in surface's link unit
            out.append("")
            out.append("simd_blitters_defs = src_c/simd_blitters_sse2.c")
        with open("Setup", "w") as f:
            f.write("\n".join(out))
        print("[pygame-recipe] patched Setup: added src_c/simd_blitters_sse2.c")

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        env['USE_SDL2'] = '1'
        env["PYGAME_CROSS_COMPILE"] = "TRUE"
        env["PYGAME_ANDROID"] = "TRUE"

        # FIX 2: force pygame's AVX2 detection off.
        # pygame's setup.py does:
        #     if os.environ.get('PYGAME_DETECT_AVX2', '') != '':
        #         avx2_filenames = ['simd_blitters_avx2']
        #         ... and then enables -mavx2 whenever platform.machine() is
        #         x86/amd64 -- which is exactly what the CI runner reports, even
        #         though we cross-compile for arm64.
        # The result is that surface.so references pg_has_avx2(), which is not
        # compiled for aarch64, so dlopen fails on the phone with
        #     cannot locate symbol "pg_has_avx2"
        # aarch64 has no AVX2 at all, so detecting it is pointless here.
        for key in ("PYGAME_DETECT_AVX2", "MAC_ARCH"):
            env.pop(key, None)
        os.environ.pop("PYGAME_DETECT_AVX2", None)

        # Keep the SIMD blitters from being inlined away (sse2neon.h marks its
        # helpers FORCE_INLINE) and make sure the ARM NEON path is on.
        cflags = env.get("CFLAGS", "")
        for flag in ("-fno-inline-functions", "-DPG_ENABLE_ARM_NEON"):
            if flag not in cflags:
                cflags += " " + flag
        env["CFLAGS"] = cflags
        return env


recipe = Pygame2Recipe()
