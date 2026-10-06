import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app/src"))
from video_import_alpha import has_transparent_alpha, convert_transparent_webm_to_webp

with tempfile.TemporaryDirectory(prefix="xm_v01101_alpha_") as td:
    td = Path(td)
    frames = td / "frames"
    frames.mkdir()
    for i in range(12):
        im = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)
        draw.ellipse((10 + i * 2, 20, 50 + i * 2, 60), fill=(20, 200, 160, 180))
        im.save(frames / f"{i:03d}.png")
        im.close()

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    alpha_webm = td / "alpha.webm"
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-framerate", "12",
        "-i", str(frames / "%03d.png"), "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", "-y", str(alpha_webm),
    ], check=True)
    assert has_transparent_alpha(alpha_webm)

    out = td / "converted.webp"
    count, fps = convert_transparent_webm_to_webp(alpha_webm, out, max_width=96, target_fps=12)
    assert count > 0 and fps > 0 and out.is_file()
    with Image.open(out) as im:
        im.seek(0)
        alpha = im.convert("RGBA").getchannel("A")
        lo, hi = alpha.getextrema()
        assert lo < hi and lo < 250

    opaque_webm = td / "opaque.webm"
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=red:s=96x96:r=12:d=1", "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuv420p", "-y", str(opaque_webm),
    ], check=True)
    assert not has_transparent_alpha(opaque_webm)

print("V01101_TRANSPARENT_WEBM_RUNTIME_OK")
