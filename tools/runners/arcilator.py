#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 The SymbiFlow Authors.
#
# Use of this source code is governed by a ISC-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/ISC
#
# SPDX-License-Identifier: ISC

import os
import shlex
import shutil

from BaseRunner import BaseRunner


class arcilator(BaseRunner):
    def __init__(self):
        super().__init__(
            "arcilator", "arcilator", {
                "preprocessing", "parsing", "elaboration", "simulation",
                "simulation_without_run"
            })

        self.submodule = "third_party/tools/circt-verilog"
        self.display_name = "Arcilator"
        self.url = f"https://github.com/llvm/circt/tree/{self.get_commit()}"
        self.frontend_executable = "circt-verilog"

    def can_run(self):
        return (shutil.which(self.executable) is not None
                and shutil.which(self.frontend_executable) is not None)

    def _apply_compat_flag(self, frontend_cmd, backend_cmd, flag):
        if not flag:
            return

        if flag.startswith("-I") and len(flag) > 2:
            frontend_cmd.extend(["-I", flag[2:]])
        elif flag.startswith("-D") and len(flag) > 2:
            frontend_cmd.extend(["-D", flag[2:]])
        elif flag.startswith("-U") and len(flag) > 2:
            frontend_cmd.extend(["-U", flag[2:]])
        elif flag.startswith("-G") and len(flag) > 2:
            frontend_cmd.extend(["-G", flag[2:]])
        elif flag == "-Wno-fatal":
            frontend_cmd.append("--error-limit=0")
        elif flag.startswith("-W"):
            frontend_cmd.append(flag)
        elif flag.startswith("--"):
            # Keep Arcilator-native overrides available for the backend.
            backend_cmd.append(flag)

    def _apply_compat_flags(self, frontend_cmd, backend_cmd, params):
        # Reuse the meaningful subset of Verilator metadata on the CIRCT
        # frontend side so Arcilator sees the same include paths, defines, and
        # warning relaxations where possible.
        raw_flags = []
        if "runner_verilator_flags" in params:
            raw_flags += shlex.split(params["runner_verilator_flags"])
        if "runner_arcilator_flags" in params:
            raw_flags += shlex.split(params["runner_arcilator_flags"])

        i = 0
        while i < len(raw_flags):
            flag = raw_flags[i]

            if flag == "-CFLAGS" and i + 1 < len(raw_flags):
                for cflag in shlex.split(raw_flags[i + 1]):
                    self._apply_compat_flag(frontend_cmd, backend_cmd, cflag)
                i += 2
                continue

            if flag in {"-I", "-D", "-U", "-y", "-Y", "-G"} and i + 1 < len(raw_flags):
                frontend_cmd.extend([flag, raw_flags[i + 1]])
                i += 2
                continue

            self._apply_compat_flag(frontend_cmd, backend_cmd, flag)
            i += 1

    def prepare_run_cb(self, tmp_dir, params):
        mode = params["mode"]
        frontend_cmd = [self.frontend_executable]

        # Reuse the same SystemVerilog frontend options as the circt-verilog
        # runner, then hand the lowered HW dialect MLIR to arcilator.
        if mode == "preprocessing":
            frontend_cmd += ["-E"]
        elif mode == "parsing":
            frontend_cmd += ["--parse-only"]
        else:
            frontend_cmd += ["--ir-hw"]

        for incdir in params["incdirs"]:
            frontend_cmd.extend(["-I", incdir])

        for define in params["defines"]:
            frontend_cmd.extend(["-D", define])

        frontend_cmd += ["--timescale=1ns/1ns", "--single-unit"]
        frontend_cmd += ["-Wno-implicit-conv"]
        frontend_cmd += [
            "-Wno-error=index-oob",
            "-Wno-error=range-oob",
            "-Wno-error=range-width-oob",
        ]
        frontend_cmd += ["--ignore-unknown-modules"]

        top = self.get_top_module_or_guess(params)
        if top is not None:
            frontend_cmd += ["--top=" + top]

        tags = params["tags"]

        if "ariane" in tags or "ibex" in tags:
            frontend_cmd += ["-Wno-duplicate-definition"]

        if "ariane" in tags:
            frontend_cmd += ["--allow-self-determined-stream-concat"]

        if "black-parrot" in tags and mode != "parsing":
            frontend_cmd += ["--allow-use-before-declare"]

            name = params["name"]
            if "bp_lce" in name or "bp_uce" in name or "bp_multicore" in name:
                frontend_cmd += ["--parse-only"]

        if "fx68k" in tags:
            frontend_cmd += ["--allow-dup-initial-drivers"]

        runner_scr = os.path.join(tmp_dir, "scr.sh")
        mlir_file = os.path.join(tmp_dir, "input.mlir")

        backend_cmd = [self.executable, "--disable-output", mlir_file]
        self._apply_compat_flags(frontend_cmd, backend_cmd, params)

        frontend_cmd += params["files"]

        with open(runner_scr, "w") as f:
            f.write("set -e\n")
            f.write("set -x\n")
            if mode in {"elaboration", "simulation", "simulation_without_run"}:
                f.write(f"{shlex.join(frontend_cmd)} -o {shlex.quote(mlir_file)}\n")
                f.write(f"{shlex.join(backend_cmd)}\n")
            else:
                f.write(f"{shlex.join(frontend_cmd)}\n")

        self.cmd = ["sh", runner_scr]
