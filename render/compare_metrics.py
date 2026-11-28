"""Compare a fixed robot render with the main product view of the reference."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


CHECKS = Path(__file__).resolve().parent / "checks"
REFERENCE = CHECKS / "industrial_reference.png"
REFERENCE_CROP = (0, 0, 311, 318)
SIZE = (311, 318)
REFERENCE_OUTLINE = (
    (13, 99), (12, 88), (17, 74), (29, 58), (39, 47), (54, 38), (78, 32),
    (151, 18), (200, 5), (216, 3), (235, 11), (251, 19), (260, 31), (261, 67),
    (257, 92), (242, 148), (242, 161), (245, 207), (253, 228), (257, 255),
    (260, 266), (278, 276), (278, 287), (209, 306), (127, 291), (126, 277),
    (145, 264), (151, 244), (159, 227), (161, 202), (151, 189), (146, 176),
    (146, 161), (157, 145), (173, 136), (189, 76), (194, 58), (180, 54),
    (91, 70), (74, 77), (55, 80), (49, 92), (39, 105), (29, 107), (29, 97),
    (19, 103),
)


def pixels(path, crop=None):
    with Image.open(path) as image:
        image = image.convert("RGB")
        if crop:
            image = image.crop(crop)
        image = image.resize(SIZE, Image.Resampling.LANCZOS)
        return np.asarray(image, dtype=np.float64) @ [.2126, .7152, .0722]


def reference_mask():
    mask = Image.new("1", SIZE)
    ImageDraw.Draw(mask).polygon(REFERENCE_OUTLINE, fill=1)
    return np.asarray(mask)


def reflection_area(mask):
    # The bottom 12% of the silhouette identifies the mounting foot.
    rows, cols = np.nonzero(mask)
    foot = cols[rows >= rows.max() - round(.12 * (rows.max() - rows.min()))]
    x1, x2 = max(0, foot.min() - 8), min(mask.shape[1], foot.max() + 9)
    top = rows.max() + 2
    if top + 4 > mask.shape[0]:
        raise ValueError("The composition must leave room beneath the base")
    return np.s_[top:min(top + 32, mask.shape[0]), x1:x2]


def summarize(luma, mask):
    foreground, background = luma[mask], luma[~mask]
    return {
        "mean_luma": float(luma.mean()),
        "highlight_pct": float((luma > 240).mean() * 100),
        "subject_mean_luma": float(foreground.mean()),
        "background_mean_luma": float(background.mean()),
        "contrast_luma": float(foreground.mean() - background.mean()),
    }


def subject_mask(mask_file):
    with Image.open(mask_file) as alpha:
        return np.asarray(alpha.getchannel("A").resize(SIZE, Image.Resampling.LANCZOS)) > 127


def histogram_distance(image, ref):
    ref_hist = np.bincount(np.rint(ref).astype(int).ravel(), minlength=256) / ref.size
    histogram = np.bincount(np.rint(image).astype(int).ravel(), minlength=256) / image.size
    return float(np.abs(np.cumsum(histogram - ref_hist)).sum() / 255 * 100)


def compare(candidate, mask_file, without_reflection):
    ref = pixels(REFERENCE, REFERENCE_CROP)
    ref_mask = reference_mask()
    image = pixels(candidate)
    mask = subject_mask(mask_file)
    control = pixels(without_reflection)
    distance = histogram_distance(image, ref)
    below_foot = reflection_area(mask)
    dark = (control - image)[below_foot]
    dark_pct = float((dark >= 2).mean() * 100)
    ref_below = ref[reflection_area(ref_mask)]
    reference, rendered = summarize(ref, ref_mask), summarize(image, mask)
    rendered["reflection"] = {
        "detected": dark_pct >= 8,
        "coverage_pct_at_2_luma": dark_pct,
        "mean_signed_darkening_luma": float(dark.mean()),
        "method": "paired Cycles render with robot glossy-ray visibility disabled",
    }
    reference["floor_below_base_mean_luma"] = float(ref_below.mean())
    reference["reflection_status"] = "A single image does not isolate reflection from shadow"
    diff_highlights = rendered["highlight_pct"] - reference["highlight_pct"]
    return {
        "reference": reference, "render": rendered,
        "histogram_deviation_pct": float(distance),
        "histogram_similarity_pct": float(100 - distance),
        "highlight_delta_pp": diff_highlights,
        "contrast_delta_luma": rendered["contrast_luma"] - reference["contrast_luma"],
        "thresholds_pass": bool(distance < 10 and abs(diff_highlights) <= 2 and rendered["reflection"]["detected"]),
    }


def make_comparison(candidate):
    with Image.open(REFERENCE) as source, Image.open(candidate) as result:
        result = result.convert("RGB")
        ref = source.crop(REFERENCE_CROP).convert("RGB").resize(result.size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (2 * result.width + 2, result.height), "#ebebeb")
        canvas.paste(ref, (0, 0))
        canvas.paste(result, (result.width + 2, 0))
        canvas.save(CHECKS / "final_compare.png")


def make_gripper_comparison(previous_home, previous_tool, current_home, current_tool):
    width, height = 720, 540
    canvas = Image.new("RGB", (2 * width + 2, 2 * height + 2), "#ebebeb")
    for index, path in enumerate((previous_home, current_home, previous_tool, current_tool)):
        with Image.open(path) as source:
            shot = source.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
            canvas.paste(shot, (index % 2 * (width + 2), index // 2 * (height + 2)))
    canvas.save(CHECKS / "gripper_fix_compare.png")


def append_result(path, result):
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append(result)
    draft = path.with_suffix(".tmp")
    draft.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    draft.replace(path)
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--mask", type=Path)
    parser.add_argument("--without-reflection", type=Path)
    parser.add_argument("--round", type=int)
    parser.add_argument("--parameters", type=json.loads, default={})
    parser.add_argument("--change", type=json.loads, default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--publish", action="store_true")
    mode.add_argument("--contrast-view", choices=("home", "tool", "reference_pose"))
    mode.add_argument("--product-stage")
    mode.add_argument("--final-view", choices=("home", "reference_pose"))
    mode.add_argument("--gripper-compare", nargs=3, type=Path, metavar=("OLD_HOME", "OLD_TOOL", "NEW_TOOL"))
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    if args.publish:
        make_comparison(args.candidate)
        return
    if args.gripper_compare:
        old_home, old_tool, new_tool = args.gripper_compare
        make_gripper_comparison(old_home, old_tool, args.candidate, new_tool)
        return
    if args.final_view:
        if args.mask is None or args.without_reflection is None:
            parser.error("--final-view requires --mask and --without-reflection")
        result = compare(args.candidate, args.mask, args.without_reflection)
        append_result(CHECKS / "final_v2_metrics.json", {
            "view": args.final_view, "image": args.candidate.name, "parameters": args.parameters, **result,
        })
        return
    if args.product_stage:
        if args.mask is None or args.round is None or args.previous is None:
            parser.error("--product-stage requires --mask, --round and --previous")
        image = pixels(args.candidate)
        ref = pixels(REFERENCE, REFERENCE_CROP)
        distance = histogram_distance(image, ref)
        sheet = CHECKS / f"product_compare_{args.round:02d}_{args.product_stage}.png"
        with Image.open(args.previous) as previous, Image.open(args.candidate) as current:
            width, height = current.size
            canvas = Image.new("RGB", (2 * width + 2, height), "#ebebeb")
            canvas.paste(previous.convert("RGB").resize(current.size, Image.Resampling.LANCZOS), (0, 0))
            canvas.paste(current.convert("RGB"), (width + 2, 0))
            canvas.save(sheet)
        append_result(CHECKS / "product_metrics.json", {
            "round": args.round, "stage": args.product_stage, "image": args.candidate.name,
            "comparison": sheet.name, "parameters": args.parameters,
            "reference": summarize(ref, reference_mask()), "render": summarize(image, subject_mask(args.mask)),
            "histogram_deviation_pct": distance, "histogram_pass": distance < 5,
        })
        return
    if args.contrast_view:
        if args.mask is None or args.round is None:
            parser.error("--contrast-view requires --mask and --round")
        rendered = summarize(pixels(args.candidate), subject_mask(args.mask))
        reference = summarize(pixels(REFERENCE, REFERENCE_CROP), reference_mask())
        append_result(CHECKS / "gripper_metrics.json", {
            "round": args.round, "view": args.contrast_view, "image": args.candidate.name,
            "parameters": args.parameters, "render": rendered, "reference": reference,
            "contrast_pass": abs(rendered["contrast_luma"]) <= 15,
        })
        return
    if args.mask is None or args.without_reflection is None or args.round is None:
        parser.error("--mask, --without-reflection and --round are required to measure a render")
    prefix = {"round": args.round, "image": args.candidate.name,
              "parameters": args.parameters, "change": args.change}
    append_result(CHECKS / "metrics_log.json", {**prefix, **compare(args.candidate, args.mask, args.without_reflection)})


if __name__ == "__main__":
    main()
