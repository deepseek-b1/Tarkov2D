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
from os.path import exists, join

from pythonforandroid.recipe import CompiledComponentsPythonRecipe
from pythonforandroid.toolchain import current_directory


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
        # Keep the SIMD blitters from being inlined away: sse2neon.h marks its
        # helpers FORCE_INLINE, and without this the symbol can stay undefined.
        cflags = env.get("CFLAGS", "")
        for flag in ("-fno-inline-functions", "-DPG_ENABLE_ARM_NEON"):
            if flag not in cflags:
                cflags += " " + flag
        env["CFLAGS"] = cflags
        return env


recipe = Pygame2Recipe()
