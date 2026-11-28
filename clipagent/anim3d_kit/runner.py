"""Jalankan satu adegan 3D di Blender (dipanggil Clip Agent).

    blender -b --factory-startup --python-exit-code 1 -P runner.py -- job.json
    python runner.py job.json            (bila modul bpy terpasang, untuk uji)

job.json: {"mode": "check"|"render", "code_file", "out_dir", "kit_dir", "W", "H", "fps", "T", "quality", "style",
           "words": [[detik, kata], ...], "stills": [detik, ...], "scale": 100, "samples": n}
Hasil selalu ditulis ke out_dir/result.json: {"ok": bool, "error": str, "objects": n, "stills": [...], "engine": ...}
"""
import builtins
import json
import math
import os
import random
import sys
import time
import traceback

ALLOWED_IMPORTS = {"math", "random", "mathutils", "bpy", "bmesh", "colorsys", "itertools", "functools"}


def _args():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else argv[1:]


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] not in ALLOWED_IMPORTS:
        raise ImportError(f"import '{name}' tidak diizinkan di kode adegan (pakai math, random, mathutils, bpy)")
    return builtins.__import__(name, globals, locals, fromlist, level)


SAFE_BUILTINS = {k: getattr(builtins, k) for k in (
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "int", "isinstance", "len", "list",
    "map", "max", "min", "pow", "print", "range", "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip",
    "ValueError", "TypeError", "KeyError", "IndexError", "Exception", "ZeroDivisionError", "AttributeError",
    "True", "False", "None", "hasattr", "slice", "frozenset", "iter", "next", "object", "super",
    "property", "staticmethod", "classmethod", "callable", "repr", "format", "chr", "ord", "hash", "id",
    "NotImplementedError", "RuntimeError", "StopIteration", "complex", "bytes")
    if hasattr(builtins, k)}
SAFE_BUILTINS["__import__"] = _safe_import
SAFE_BUILTINS["__build_class__"] = builtins.__build_class__


def _short_tb() -> str:
    tb = traceback.format_exc().strip().splitlines()
    keep, take = [], False
    for line in tb:
        if 'File "scene.py"' in line or 'File "<scene>"' in line:
            take = True
        if take or line.startswith(("Traceback", "  File \"scene.py\"")):
            keep.append(line)
    keep = keep or tb[-8:]
    return "\n".join(keep[-14:] if len(keep) > 14 else keep)


def main():
    job = json.load(open(_args()[0], encoding="utf-8"))
    out_dir = job["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    res = {"ok": False, "error": "", "objects": 0, "stills": [], "engine": "", "started": time.time()}

    def write():
        with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False)
    try:
        sys.path.insert(0, job["kit_dir"])
        import bpy
        import kit
        kit.setup({k: job[k] for k in ("W", "H", "fps", "T", "quality", "style", "words", "scale", "samples", "lang")
                   if k in job})
        res["engine"] = kit.P.get("engine", "")
        code = open(job["code_file"], encoding="utf-8").read()
        ns = {"__builtins__": SAFE_BUILTINS, "__name__": "scene", "math": math, "random": random, "k": kit}
        try:
            exec(compile(code, "scene.py", "exec"), ns)
            if not callable(ns.get("build")):
                raise NameError("Kode adegan harus mendefinisikan fungsi build(k).")
            ns["build"](kit)
            if not kit.STATE["camera_set"]:
                kit.fit()
            kit.finish()
        except Exception:                                   # noqa: BLE001 - dilaporkan ke Clip Agent untuk diperbaiki AI
            res["error"] = _short_tb()
            write()
            print("CLIPAGENT_SCENE_ERROR\n" + res["error"], flush=True)
            return 1
        res["objects"] = len(kit.STATE["objects"])
        sc = bpy.context.scene
        if job["mode"] == "check":
            sc.render.image_settings.file_format = "PNG"
            for i, t in enumerate(job.get("stills") or [0.5]):
                sc.frame_set(kit.f(t))
                path = os.path.join(out_dir, f"still_{i}.png")
                sc.render.filepath = path
                bpy.ops.render.render(write_still=True)
                res["stills"].append(path)
        else:
            frames = os.path.join(out_dir, "frames")
            os.makedirs(frames, exist_ok=True)
            sc.render.image_settings.file_format = "JPEG"
            try:
                sc.render.image_settings.quality = 92
            except AttributeError:
                pass
            sc.render.filepath = os.path.join(frames, "f_")
            sc.render.use_file_extension = True
            bpy.ops.render.render(animation=True)
            res["frames"] = sc.frame_end
        res["ok"] = True
    except Exception:                                       # noqa: BLE001
        res["error"] = "RUNNER: " + traceback.format_exc()[-2000:]
        print(res["error"], flush=True)
    res["seconds"] = round(time.time() - res.pop("started"), 1)
    write()
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    code = main()
    if code:
        sys.exit(code)
