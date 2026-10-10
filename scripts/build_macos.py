#!/usr/bin/env python3
"""Build and validate the macOS application bundle.

Local builds are ad-hoc signed for development. Release builds require a
Developer ID Application identity and Apple notarization credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = PROJECT_ROOT / "CtripPlanDescriptionFilling.spec"
APP_BUNDLE = PROJECT_ROOT / "dist" / "CtripPlanDescriptionFilling.app"
APP_EXECUTABLE = APP_BUNDLE / "Contents" / "MacOS" / "CtripPlanDescriptionFilling"
VALID_ARCHITECTURES = {"arm64", "x86_64"}


class PackagingError(RuntimeError):
    pass


def print_command(command: list[str]) -> None:
    print(f"+ {shlex.join(command)}", flush=True)


def run_command(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    dry_run: bool = False,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    print_command(command)
    if dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=capture_output,
        check=True,
    )


def require_release_settings(environ: dict[str, str]) -> tuple[str, str]:
    identity = environ.get("MACOS_CODESIGN_IDENTITY", "").strip()
    if not identity:
        raise PackagingError(
            "release 打包缺少 MACOS_CODESIGN_IDENTITY；必须使用 Developer ID Application 证书"
        )
    if not identity.startswith("Developer ID Application:"):
        raise PackagingError(
            "MACOS_CODESIGN_IDENTITY 必须是 Developer ID Application 证书，"
            "不能使用 adhoc 或 Apple Development 证书"
        )

    notary_profile = environ.get("MACOS_NOTARY_PROFILE", "").strip()
    if not notary_profile:
        raise PackagingError(
            "release 打包缺少 MACOS_NOTARY_PROFILE；先用 notarytool store-credentials 保存公证凭据"
        )
    return identity, notary_profile


def verify_identity_is_installed(identity: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    result = run_command(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True,
    )
    if f'"{identity}"' not in result.stdout:
        raise PackagingError(f"钥匙串中找不到有效签名证书：{identity}")


def create_zip(source: Path, destination: Path, *, dry_run: bool) -> None:
    if not dry_run:
        destination.unlink(missing_ok=True)
    run_command(
        [
            "ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(source),
            str(destination),
        ],
        dry_run=dry_run,
    )


def macho_architectures(path: Path) -> set[str] | None:
    with path.open("rb") as handle:
        magic = handle.read(4)
    macho_magics = {
        b"\xfe\xed\xfa\xce",
        b"\xfe\xed\xfa\xcf",
        b"\xce\xfa\xed\xfe",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf",
        b"\xbf\xba\xfe\xca",
    }
    if magic not in macho_magics:
        return None
    result = subprocess.run(
        ["lipo", "-archs", str(path)],
        text=True,
        capture_output=True,
        check=True,
    )
    return set(result.stdout.split())


def verify_bundle_architecture(app_bundle: Path, target_arch: str, *, dry_run: bool) -> None:
    print(f"+ lipo architecture-check {shlex.quote(str(app_bundle))} {target_arch}", flush=True)
    if dry_run:
        return

    required = {target_arch}
    invalid: list[str] = []
    for path in app_bundle.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        architectures = macho_architectures(path)
        if architectures is not None and not required.issubset(architectures):
            invalid.append(f"{path.relative_to(app_bundle)} ({', '.join(sorted(architectures))})")
    if invalid:
        details = "\n".join(invalid[:20])
        raise PackagingError(f"产物包含不兼容 {target_arch} 的 Mach-O 文件：\n{details}")


def smoke_test_app(*, dry_run: bool, seconds: int = 8) -> None:
    print(f"+ smoke-test {shlex.quote(str(APP_EXECUTABLE))} {seconds}s", flush=True)
    if dry_run:
        return

    smoke_env = os.environ.copy()
    smoke_env["QT_QPA_PLATFORM"] = "offscreen"
    process = subprocess.Popen(
        [str(APP_EXECUTABLE)],
        cwd=PROJECT_ROOT,
        env=smoke_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        output, _ = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
        return

    if process.returncode != 0:
        raise PackagingError(
            f"打包后的应用启动失败，退出码 {process.returncode}:\n{output.strip()}"
        )


def validate_release_signature(*, dry_run: bool) -> None:
    result = run_command(
        ["codesign", "-d", "--verbose=4", str(APP_BUNDLE)],
        dry_run=dry_run,
        capture_output=True,
    )
    if dry_run:
        return
    details = f"{result.stdout}\n{result.stderr}"
    if "Authority=Developer ID Application:" not in details:
        raise PackagingError("产物不是 Developer ID Application 签名")
    if "TeamIdentifier=not set" in details or "(runtime)" not in details:
        raise PackagingError("产物缺少 TeamIdentifier 或 Hardened Runtime")


def require_notary_accepted(output: str) -> None:
    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        raise PackagingError(f"无法解析 Apple 公证结果：{exc}") from exc
    status = result.get("status")
    if status != "Accepted":
        submission_id = result.get("id", "unknown")
        raise PackagingError(f"Apple 公证未通过：status={status}, id={submission_id}")


def build_macos(*, release: bool, target_arch: str, dry_run: bool) -> Path:
    if target_arch not in VALID_ARCHITECTURES:
        raise PackagingError(f"不支持的 macOS 架构：{target_arch}")
    if not dry_run and platform.system() != "Darwin":
        raise PackagingError("macOS .app 必须在 macOS 上构建")

    identity = ""
    notary_profile = ""
    if release:
        identity, notary_profile = require_release_settings(os.environ)
        verify_identity_is_installed(identity, dry_run=dry_run)

    build_env = os.environ.copy()
    build_env["MACOS_CODESIGN_IDENTITY"] = identity
    build_env["MACOS_TARGET_ARCH"] = target_arch
    build_env["PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR"] = "1"
    build_env["PYINSTALLER_VERIFY_BUNDLE_SIGNATURE"] = "1"

    run_command(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            str(SPEC_FILE),
        ],
        env=build_env,
        dry_run=dry_run,
    )
    run_command(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=1", str(APP_BUNDLE)],
        dry_run=dry_run,
    )
    verify_bundle_architecture(APP_BUNDLE, target_arch, dry_run=dry_run)
    smoke_test_app(dry_run=dry_run)

    if not release:
        print("本地开发包已通过结构、签名、架构和启动烟测；adhoc 包不可对外分发。")
        return APP_BUNDLE

    validate_release_signature(dry_run=dry_run)
    upload_zip = PROJECT_ROOT / "dist" / f"CtripPlanDescriptionFilling-macOS-{target_arch}-notarization.zip"
    final_zip = PROJECT_ROOT / "dist" / f"CtripPlanDescriptionFilling-macOS-{target_arch}.zip"
    create_zip(APP_BUNDLE, upload_zip, dry_run=dry_run)
    notary_result = run_command(
        [
            "xcrun",
            "notarytool",
            "submit",
            str(upload_zip),
            "--keychain-profile",
            notary_profile,
            "--wait",
            "--output-format",
            "json",
        ],
        dry_run=dry_run,
        capture_output=True,
    )
    if not dry_run:
        require_notary_accepted(notary_result.stdout)
        print(notary_result.stdout.strip())
    run_command(["xcrun", "stapler", "staple", str(APP_BUNDLE)], dry_run=dry_run)
    run_command(["xcrun", "stapler", "validate", str(APP_BUNDLE)], dry_run=dry_run)
    run_command(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=1", str(APP_BUNDLE)],
        dry_run=dry_run,
    )
    run_command(
        ["spctl", "--assess", "--type", "execute", "--verbose=4", str(APP_BUNDLE)],
        dry_run=dry_run,
    )
    create_zip(APP_BUNDLE, final_zip, dry_run=dry_run)
    if not dry_run:
        upload_zip.unlink(missing_ok=True)
    print(f"可分发产物：{final_zip}")
    return final_zip


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--local", action="store_true", help="构建仅供本机开发使用的 adhoc 包")
    mode.add_argument("--release", action="store_true", help="构建签名并公证的可分发包")
    machine = platform.machine().lower()
    native_arch = "arm64" if machine in {"arm64", "aarch64"} else "x86_64"
    parser.add_argument("--arch", choices=sorted(VALID_ARCHITECTURES), default=native_arch)
    parser.add_argument("--dry-run", action="store_true", help="只打印流程，不执行命令")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        build_macos(release=args.release, target_arch=args.arch, dry_run=args.dry_run)
    except (PackagingError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
