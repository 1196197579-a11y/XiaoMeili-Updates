# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.3.3 patch anchor: {label}")
    return text.replace(old, new, 1)


def replace_exact_count(text: str, old: str, new: str, expected: int, label: str) -> str:
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"unexpected anchor count for {label}: {count}, expected {expected}")
    return text.replace(old, new)


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    if not main_path.exists():
        raise FileNotFoundError(main_path)

    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.3\.2"',
        'APP_NAME = "小美丽 V0.7.3.3｜Result Snapshot Alignment Fix"\nAPP_VERSION = "0.7.3.3"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # User-provided 2026-09-24 result screenshot shows that the old parse snapshot
    # y=0.42..0.74 is visibly too high and clips the bottom K/D/A values.
    # Keep the same 32% height but shift the native-resolution parse crop down by 8%.
    s = replace_once(
        s,
        'ROI_REPORT_CARDS = (0.090, 0.420, 0.910, 0.740)',
        'ROI_REPORT_CARDS = (0.090, 0.500, 0.910, 0.820)',
        "report parse crop",
    )

    s = s.replace(
        '# High-resolution parse crop. It deliberately starts higher so the nickname row\n'
        '# and K/D/A row are both present in the frozen snapshot.',
        '# High-resolution parse crop calibrated to the 2026-09-24 result layout.\n'
        '# It now centers the player cards and fully includes nickname, ACS and K/D/A.',
        1,
    )

    # After moving the outer crop, retarget the inner nickname bands.
    old_nick = 'card[int(h * 0.26):int(h * 0.58), int(w * 0.08):int(w * 0.92)]'
    new_nick = 'card[int(h * 0.16):int(h * 0.42), int(w * 0.08):int(w * 0.92)]'
    s = replace_exact_count(s, old_nick, new_nick, 2, "nickname ROI")

    # Retarget the K/D/A bands. Global target becomes roughly y=0.70..0.80 of the
    # full game frame, which safely contains the KDA label and all three values.
    old_kda = 'card[int(h * 0.80):int(h * 0.995), int(w * 0.16):int(w * 0.84)]'
    new_kda = 'card[int(h * 0.62):int(h * 0.92), int(w * 0.16):int(w * 0.84)]'
    s = replace_exact_count(s, old_kda, new_kda, 2, "KDA ROI")

    s = replace_once(
        s,
        'tight_k = card[int(h * 0.82):int(h * 0.995), int(w * 0.18):int(w * 0.43)]',
        'tight_k = card[int(h * 0.68):int(h * 0.90), int(w * 0.18):int(w * 0.43)]',
        "tight K ROI",
    )

    s = s.replace(
        '# Corrected V0.4.9.9 coordinates for ROI_REPORT_CARDS (y=0.42..0.74).',
        '# V0.7.3.3 coordinates for ROI_REPORT_CARDS (y=0.50..0.82).',
        1,
    )

    # Defensive geometry checks. These fail the build if a future edit shifts the
    # regions back into the character-art area or clips KDA again.
    outer_y1, outer_y2 = 0.50, 0.82
    nick_y1, nick_y2 = 0.16, 0.42
    kda_y1, kda_y2 = 0.62, 0.92
    nick_global = (outer_y1 + (outer_y2 - outer_y1) * nick_y1,
                   outer_y1 + (outer_y2 - outer_y1) * nick_y2)
    kda_global = (outer_y1 + (outer_y2 - outer_y1) * kda_y1,
                  outer_y1 + (outer_y2 - outer_y1) * kda_y2)
    if not (0.54 <= nick_global[0] <= 0.57 and 0.62 <= nick_global[1] <= 0.65):
        raise RuntimeError(f"nickname global ROI sanity check failed: {nick_global}")
    if not (0.69 <= kda_global[0] <= 0.71 and 0.79 <= kda_global[1] <= 0.81):
        raise RuntimeError(f"KDA global ROI sanity check failed: {kda_global}")

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)
    print(
        "Patched XiaoMeili source to V0.7.3.3 | "
        f"report_y=0.50..0.82 nick_global={nick_global} kda_global={kda_global}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0733.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
