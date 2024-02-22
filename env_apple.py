from configparser import ConfigParser
from pathlib import Path
import subprocess
from typing import Callable, Optional

from .machine_file import strv_to_meson
from .machine_spec import MachineSpec


APPLE_SDKS = {
    "macos":             "macosx",
    "ios":               "iphoneos",
    "ios-simulator":     "iphonesimulator",
    "watchos":           "watchos",
    "watchos-simulator": "watchsimulator",
    "tvos":              "appletvos",
    "tvos-simulator":    "appletvsimulator",
}

APPLE_CLANG_ARCHS = {
    "x86":        "i386",
    "arm":        "armv7",
    "arm64eoabi": "arm64e",
}

APPLE_MINIMUM_OS_VERSIONS = {
    "macos":        "10.9",
    "macos-arm64":  "11.0",
    "macos-arm64e": "11.0",
    "ios":          "8.0",
    "watchos":      "9.0",
    "tvos":         "13.0",
}

APPLE_BINARIES = [
    ("c",                 "clang"),
    ("cpp",               "clang++", ["-stdlib=libc++"]),
    ("objc",              "#c"),
    ("objcpp",            "#cpp"),

    ("ar",                "ar"),
    ("nm",                "llvm-nm"),
    ("ranlib",            "ranlib"),
    ("strip",             "strip", ["-Sx"]),
    ("libtool",           "libtool"),

    ("install_name_tool", "install_name_tool"),
    ("otool",             "otool"),
    ("codesign",          "codesign"),
    ("lipo",              "lipo"),
]


def init_machine_config(machine: MachineSpec,
                        sdk_prefix: Optional[Path],
                        native_machine: MachineSpec,
                        is_cross_build: bool,
                        call_selected_meson: Callable,
                        config: ConfigParser):
    machine_path = []
    machine_env = {}

    sdk_name = APPLE_SDKS[machine.os_dash_config]
    sdk_path = subprocess.run(["xcrun", "--sdk", sdk_name, "--show-sdk-path"],
                              capture_output=True,
                              encoding="utf-8").stdout.strip()

    binaries = {}
    clang_path = None
    for (identifier, tool_name, *rest) in APPLE_BINARIES:
        if tool_name.startswith("#"):
            binaries[identifier] = binaries[tool_name[1:]]
            continue

        path = subprocess.run(["xcrun", "--sdk", sdk_name, "-f", tool_name],
                              capture_output=True,
                              encoding="utf-8").stdout.strip()
        if tool_name == "clang":
            clang_path = Path(path)

        argv = [path]
        if len(rest) != 0:
            argv += rest[0]

        raw_val = str(argv)
        if identifier in {"c", "cpp"}:
            raw_val += " + common_flags"

        binaries[identifier] = raw_val
    config["binaries"] = binaries

    clang_arch = APPLE_CLANG_ARCHS.get(machine.arch, machine.arch)

    os_minver = APPLE_MINIMUM_OS_VERSIONS.get(machine.os_dash_arch,
                                              APPLE_MINIMUM_OS_VERSIONS[machine.os])

    target = f"{clang_arch}-apple-{machine.os}{os_minver}"
    if machine.config is not None:
        target += "-" + machine.config

    linker_flags = ["-Wl,-dead_strip"]
    if (clang_path.parent / "ld-classic").exists():
        # New linker links with libresolv even if we're not using any symbols from it,
        # at least as of Xcode 15.0 beta 7.
        linker_flags += ["-Wl,-ld_classic"]

    constants = {
        "common_flags": strv_to_meson([
            "-target", target,
            "-isysroot", sdk_path,
        ]),
        "c_like_flags": strv_to_meson([]),
        "linker_flags": strv_to_meson(linker_flags),
    }

    if sdk_prefix is not None \
            and (sdk_prefix / "lib" / "c++" / "libc++.a").exists() \
            and machine.os != "watchos":
        constants.update({
            "cxx_like_flags": strv_to_meson([
                "-nostdinc++",
                "-isystem" + str(sdk_prefix / "include" / "c++"),
            ]),
            "cxx_link_flags": strv_to_meson([
                "-nostdlib++",
                "-L" + str(sdk_prefix / "lib" / "c++"),
                "-lc++",
                "-lc++abi",
            ]),
        })
    config["constants"] = constants

    config["built-in options"] = {
        "c_args": "c_like_flags",
        "cpp_args": "c_like_flags + cxx_like_flags",
        "objc_args": "c_like_flags",
        "objcpp_args": "c_like_flags + cxx_like_flags",
        "c_link_args": "linker_flags",
        "cpp_link_args": "linker_flags + cxx_link_flags",
        "objc_link_args": "linker_flags",
        "objcpp_link_args": "linker_flags + cxx_link_flags",
        "b_lundef": "true",
    }

    return (machine_path, machine_env)