"""Standalone CLI: python scripts/postprocess_image.py --input image.png --output outputs/test"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Works from backend/, project root, arbitrary cwd, and python -m backend.scripts....
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main(argv=None):
    parser = argparse.ArgumentParser(description="CPU-only planning image cleanup; SDXL and the web server are not required.")
    parser.add_argument("--input", required=True, type=Path, help="Image file or directory")
    parser.add_argument("--output", required=True, type=Path, help="Root directory for result bundles")
    parser.add_argument("--config", type=Path, help="Optional JSON configuration")
    parser.add_argument("--mode", choices=("auto", "palette"), default=None)
    parser.add_argument("--background", help="Background RGB, e.g. #FFFFFF; otherwise estimated")
    parser.add_argument("--color-delta", type=float, help="Lab color-mode tolerance; smaller preserves more differences")
    parser.add_argument("--geometry-radius", type=int, help="Defect radius at 1024px; 0 disables geometry repair")
    parser.add_argument("--geometry-mode", choices=("regularize", "local", "off"), default=None,
                        help="Footprint reconstruction (default), v1 local morphology, or no geometry edits")
    parser.add_argument("--mask", type=Path, help="Authoritative foreground mask for a single image; geometry is preserved")
    parser.add_argument("--recursive", action="store_true", help="Search input subdirectories")
    parser.add_argument("--overwrite", action="store_true", help="Replace only existing generated bundles")
    args = parser.parse_args(argv)
    try:
        from backend.postprocessing import load_config, process_file
        from backend.postprocessing.files import SUPPORTED_EXTENSIONS
    except ModuleNotFoundError as exc:
        print(f"Missing dependency: {exc.name}. Run: python -m pip install -r requirements-postprocess.txt", file=sys.stderr)
        return 2
    try:
        config = load_config(args.config, mode=args.mode, background_rgb=args.background,
                             color_delta=args.color_delta, defect_radius=args.geometry_radius, geometry_mode=args.geometry_mode)
        source, output = args.input.resolve(), args.output.resolve()
        if not source.exists():
            raise FileNotFoundError(f"Input does not exist: {source}")
        if source.is_dir():
            if args.mask:
                raise ValueError("--mask is supported only for a single image")
            if source == output or output in source.parents:
                raise ValueError("Choose a separate output directory")
            images = sorted(p for p in (source.rglob("*") if args.recursive else source.iterdir())
                            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS and output not in p.parents)
        else:
            images = [source]
        if not images:
            raise ValueError("No supported images found")
        failed = 0
        for path in images:
            relative = path.relative_to(source) if source.is_dir() else Path(path.name)
            # Keep extension in directory name, so plan.jpg and plan.png do not collide.
            target = output / relative
            try:
                result = process_file(path, target, config, mask_path=args.mask, overwrite=args.overwrite)
                counts = result["report"]["counts"]
                print(json.dumps({"input": str(path), "output": str(target), "status": "ok", "counts": counts,
                                  "seconds": result["report"]["elapsed_seconds"]}, ensure_ascii=False), flush=True)
            except Exception as exc:
                failed += 1
                print(f"ERROR {path}: {exc}", file=sys.stderr, flush=True)
        print(f"Finished: {len(images) - failed} succeeded, {failed} failed.")
        return 1 if failed else 0
    except (ValueError, OSError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
