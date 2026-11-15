#!/usr/bin/env python3
"""Bangun ClipAgent.apk tanpa Android Studio/Gradle.

Butuh: JDK 11+ (javac, java), aapt2, android.jar (API 35), bundletool-all.jar (berisi apksig untuk
tanda tangan) dan dx.jar (dexer; mis. dx-27.0.3.jar dari rilis dex2jar). Tanpa --dx, D8 dari bundletool
dipakai (versi lama D8 di bundletool bermasalah dengan inner class, jadi dx disarankan).
Contoh:
  python build_apk.py --android-jar android.jar --aapt2 aapt2 --bundletool bundletool-all.jar --dx dx.jar
Keystore default: keystore/clipagent-release.p12 (alias clipagent). Bila belum ada, keystore baru dibuat
otomatis dengan keytool. Keystore tidak disimpan di repo publik; simpan cadangannya sendiri, karena APK
yang ditandatangani kunci berbeda tidak bisa memperbarui aplikasi yang sudah terpasang (harus uninstall dulu).
"""
import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(cmd, **kw):
    print("$", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--android-jar", required=True)
    ap.add_argument("--aapt2", required=True)
    ap.add_argument("--bundletool", required=True)
    ap.add_argument("--dx", default="", help="path dx.jar (disarankan)")
    ap.add_argument("--keystore", default=str(HERE / "keystore" / "clipagent-release.p12"))
    ap.add_argument("--alias", default="clipagent")
    ap.add_argument("--password", default="clipagent")
    ap.add_argument("--out", default=str(HERE / "ClipAgent.apk"))
    a = ap.parse_args()

    build = HERE / "build"
    shutil.rmtree(build, ignore_errors=True)
    (build / "classes").mkdir(parents=True)

    # 1) resource + manifest
    run([a.aapt2, "compile", "--dir", HERE / "res", "-o", build / "res.zip"])
    run([a.aapt2, "link", "-I", a.android_jar, "--manifest", HERE / "AndroidManifest.xml",
         "-A", HERE / "assets", "-o", build / "base.apk", build / "res.zip",
         "--min-sdk-version", "24", "--target-sdk-version", "34"])

    # 2) Java -> .class -> classes.dex
    sources = [str(p) for p in (HERE / "src").rglob("*.java")]
    run(["javac", "-source", "8", "-target", "8", "-bootclasspath", a.android_jar, "-Xlint:-options",
         "-encoding", "UTF-8", "-d", build / "classes", *sources])
    if a.dx:
        run(["java", "-cp", a.dx, "com.android.dx.command.Main", "--dex", "--min-sdk-version=24",
             f"--output={build / 'classes.dex'}", build / "classes"])
    else:
        classes = [str(p) for p in (build / "classes").rglob("*.class")]
        run(["java", "-cp", a.bundletool, "com.android.tools.r8.D8", "--release", "--min-api", "24",
             "--lib", a.android_jar, "--output", build, *classes])

    # 3) gabungkan & tanda tangani
    unsigned = build / "unsigned.apk"
    shutil.copy(build / "base.apk", unsigned)
    with zipfile.ZipFile(unsigned, "a") as z:
        z.write(build / "classes.dex", "classes.dex", compress_type=zipfile.ZIP_DEFLATED)
    ks = Path(a.keystore)
    if not ks.is_file():
        ks.parent.mkdir(parents=True, exist_ok=True)
        print("Keystore belum ada; membuat keystore baru:", ks)
        run(["keytool", "-genkeypair", "-storetype", "PKCS12", "-keystore", ks, "-alias", a.alias,
             "-storepass", a.password, "-keypass", a.password, "-keyalg", "RSA", "-keysize", "2048",
             "-validity", "10000", "-dname", "CN=Clip Agent, O=Clip Agent, C=ID"])
    signer = HERE / "tools"
    run(["javac", "-cp", a.bundletool, "-d", build, signer / "Sign.java"])
    sep = ";" if sys.platform.startswith("win") else ":"
    run(["java", "-cp", f"{a.bundletool}{sep}{build}", "Sign", unsigned, a.out, a.keystore, a.alias,
         a.password, "24"])
    print("APK:", a.out)


if __name__ == "__main__":
    main()
