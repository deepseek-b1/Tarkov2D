"""
Tarkov2D 专用 pygame 配方(基于 p4a 官方配方,只加一处修复)。

问题:用 p4a 默认配方编出来的 pygame 2.5.2,在 arm64 上运行时报
    ImportError: dlopen failed: cannot locate symbol
    "alphablit_alpha_sse2_argb_surf_alpha" referenced by ".../pygame/surface.so"
这个符号是 pygame 的 **x86 SSE2** 专用 SIMD 函数(名字里的 sse2 就是它),
在 arm64 上根本不存在,于是 surface.so 加载失败 -> pygame.display 不可用 ->
游戏在 pygame.display.set_mode() 处崩溃(exit 255)。

修法:构建时关掉 pygame 的 SIMD 汇编路径,让它走纯 C 实现。
"""
from os.path import join

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

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        env['USE_SDL2'] = '1'
        env["PYGAME_CROSS_COMPILE"] = "TRUE"
        env["PYGAME_ANDROID"] = "TRUE"
        # ==== 本配方唯一的改动:关掉 SIMD/SSE 汇编 ====
        # 否则 surface.so 会引用 x86 SSE2 符号,arm64 上 dlopen 失败。
        env["PYGAME_DISABLE_SIMD"] = "1"
        env["PS_DISABLE_SIMD"] = "1"
        cflags = env.get("CFLAGS", "")
        if "-DPYGAME_DISABLE_SIMD" not in cflags:
            env["CFLAGS"] = cflags + " -DPYGAME_DISABLE_SIMD -DPS_DISABLE_SIMD"
        return env


recipe = Pygame2Recipe()
