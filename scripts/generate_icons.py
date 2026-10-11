"""Generate app icons from logo.svg for PyInstaller.

Produces:
  - assets/icon.icns  (macOS)
  - assets/icon.ico   (Windows)
  - assets/icon.png   (Linux)
  - assets/icon-macos.png (Qt Dock icon, with transparent margins)

Requires: Pillow, cairosvg (or falls back to a simple PNG generation).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SVG = ASSETS / "logo.svg"
PNG = ASSETS / "icon.png"
MACOS_PNG = ASSETS / "icon-macos.png"
ICO = ASSETS / "icon.ico"
ICNS = ASSETS / "icon.icns"
PACKAGE_ASSETS = ASSETS.parent / "src" / "roomkit_ui" / "assets"


def svg_to_png(size: int = 1024) -> None:
    """Convert SVG to PNG using cairosvg or rsvg-convert."""
    try:
        import cairosvg

        cairosvg.svg2png(
            url=str(SVG),
            write_to=str(PNG),
            output_width=size,
            output_height=size,
        )
        return
    except ImportError:
        pass

    # Fallback: rsvg-convert (available on most Linux/macOS)
    try:
        subprocess.run(
            ["rsvg-convert", "-w", str(size), "-h", str(size), str(SVG), "-o", str(PNG)],
            check=True,
        )
        return
    except FileNotFoundError:
        pass

    # Fallback: sips (macOS only)
    try:
        # sips can't read SVG, but we can try qlmanage
        subprocess.run(
            ["qlmanage", "-t", "-s", str(size), "-o", str(ASSETS), str(SVG)],
            check=True,
            capture_output=True,
        )
        generated = ASSETS / (SVG.stem + ".svg.png")
        if generated.exists():
            generated.rename(PNG)
            return
    except FileNotFoundError:
        pass

    print("WARNING: Could not convert SVG to PNG. Install cairosvg: pip install cairosvg")
    sys.exit(1)


def png_to_ico() -> None:
    """Convert PNG to ICO using Pillow."""
    try:
        from PIL import Image

        img = Image.open(PNG)
        img.save(ICO, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    except ImportError:
        print("WARNING: Pillow not installed, skipping .ico generation")


def png_to_icns() -> None:
    """Convert PNG to ICNS using iconutil (macOS) or png2icns."""
    if sys.platform == "darwin":
        iconset = ASSETS / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        try:
            from PIL import Image

            # The logo nearly fills its canvas. Inset it for the macOS Dock;
            # the application and the .app bundle must use the same margins.
            with Image.open(PNG) as source:
                padding = source.width // 16
                drawing = source.convert("RGBA").resize(
                    (source.width - 2 * padding, source.height - 2 * padding), Image.LANCZOS
                )
                img = Image.new("RGBA", source.size)
                img.alpha_composite(drawing, (padding, padding))
            img.save(MACOS_PNG)
            for size in [16, 32, 64, 128, 256, 512]:
                resized = img.resize((size, size), Image.LANCZOS)
                resized.save(iconset / f"icon_{size}x{size}.png")
                double = img.resize((size * 2, size * 2), Image.LANCZOS)
                double.save(iconset / f"icon_{size}x{size}@2x.png")
        except ImportError:
            print("WARNING: Pillow not installed, skipping .icns generation")
            return

        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS)], check=True)
        # Cleanup iconset
        shutil.rmtree(iconset)
    else:
        print("NOTE: .icns generation requires macOS, skipping")


def sync_packaged_icons() -> None:
    """Keep Qt's installed resources in step with the bundle's build assets."""
    PACKAGE_ASSETS.mkdir(parents=True, exist_ok=True)
    for path in (PNG, MACOS_PNG, ICO, ICNS):
        if path.exists():
            shutil.copy2(path, PACKAGE_ASSETS / path.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Regenerate existing app icons")
    args = parser.parse_args()
    # Skip generation if the required icons already exist
    needed = [PNG]
    if sys.platform == "darwin":
        needed.extend((ICNS, MACOS_PNG))
    elif sys.platform == "win32":
        needed.append(ICO)
    if all(f.exists() for f in needed) and not args.force:
        sync_packaged_icons()
        print("Icons already exist, skipping generation.")
        sys.exit(0)

    if not PNG.exists() or args.force:
        print(f"Converting {SVG} ...")
        svg_to_png(1024)
        print(f"  -> {PNG}")
    if not ICO.exists() or args.force:
        png_to_ico()
    if ICO.exists():
        print(f"  -> {ICO}")
    png_to_icns()
    if ICNS.exists():
        print(f"  -> {ICNS}")
    sync_packaged_icons()
    print("Done.")
