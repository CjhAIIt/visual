#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YOLOv11/YOLO-format dataset augmentation for plant pest/disease detection.
- Keeps labels consistent with geometric transforms.
- Supports translation, stronger rotation, flips, stronger color jitter, MixUp, and Mosaic.

Label format (YOLO):
class x_center y_center width height  (all normalized 0-1)
"""
from __future__ import annotations

import argparse
import math
import random
import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageEnhance

Image.MAX_IMAGE_PIXELS = None

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET_ROOT = BASE_DIR / "annotation_datasets"
DEFAULT_IMAGES = Path("/run/media/zyd/文档/石斛/图片")
DEFAULT_LABELS = Path("/run/media/zyd/文档/石斛/黑斑")
DEFAULT_OUT_IMAGES = Path("/run/media/zyd/文档/石斛/增强图片")
DEFAULT_OUT_LABELS = Path("/run/media/zyd/文档/石斛/增强标注")
LabelItem = Tuple[int, float, float, float, float]
SampleItem = Tuple[Path, List[LabelItem]]


def read_labels(path: Path) -> List[LabelItem]:
    if not path.exists():
        return []
    items: List[LabelItem] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            cls = int(float(parts[0]))
            xc, yc, w, h = map(float, parts[1:5])
            items.append((cls, xc, yc, w, h))
    return items


def write_labels(path: Path, items: List[LabelItem]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for cls, xc, yc, w, h in items:
            f.write(f"{cls} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}\n")


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def translate_boxes(
    boxes: List[Tuple[int, float, float, float, float]],
    dx: int,
    dy: int,
    img_w: int,
    img_h: int,
    min_size: float = 1.0,
) -> List[Tuple[int, float, float, float, float]]:
    out: List[Tuple[int, float, float, float, float]] = []
    for cls, xc, yc, w, h in boxes:
        # to pixel coords
        bw = w * img_w
        bh = h * img_h
        cx = xc * img_w
        cy = yc * img_h
        x1 = cx - bw / 2.0 + dx
        y1 = cy - bh / 2.0 + dy
        x2 = cx + bw / 2.0 + dx
        y2 = cy + bh / 2.0 + dy

        # clip to image bounds
        x1c = clamp(x1, 0.0, img_w)
        y1c = clamp(y1, 0.0, img_h)
        x2c = clamp(x2, 0.0, img_w)
        y2c = clamp(y2, 0.0, img_h)

        new_w = x2c - x1c
        new_h = y2c - y1c
        if new_w < min_size or new_h < min_size:
            continue

        new_cx = x1c + new_w / 2.0
        new_cy = y1c + new_h / 2.0
        out.append((cls, new_cx / img_w, new_cy / img_h, new_w / img_w, new_h / img_h))
    return out


def flip_boxes(
    boxes: List[Tuple[int, float, float, float, float]],
    horizontal: bool,
    vertical: bool,
) -> List[Tuple[int, float, float, float, float]]:
    out: List[Tuple[int, float, float, float, float]] = []
    for cls, xc, yc, w, h in boxes:
        if horizontal:
            xc = 1.0 - xc
        if vertical:
            yc = 1.0 - yc
        out.append((cls, xc, yc, w, h))
    return out


def rotate_boxes(
    boxes: List[Tuple[int, float, float, float, float]],
    angle_deg: float,
    img_w: int,
    img_h: int,
    min_size: float = 1.0,
) -> List[Tuple[int, float, float, float, float]]:
    if abs(angle_deg) < 1e-6:
        return list(boxes)
    out: List[Tuple[int, float, float, float, float]] = []
    angle = math.radians(angle_deg)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    cx0 = img_w / 2.0
    cy0 = img_h / 2.0

    for cls, xc, yc, w, h in boxes:
        bw = w * img_w
        bh = h * img_h
        cx = xc * img_w
        cy = yc * img_h
        x1 = cx - bw / 2.0
        y1 = cy - bh / 2.0
        x2 = cx + bw / 2.0
        y2 = cy + bh / 2.0

        corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        rot = []
        for x, y in corners:
            rx = cos_a * (x - cx0) - sin_a * (y - cy0) + cx0
            ry = sin_a * (x - cx0) + cos_a * (y - cy0) + cy0
            rot.append((rx, ry))

        xs = [p[0] for p in rot]
        ys = [p[1] for p in rot]
        x1c = clamp(min(xs), 0.0, img_w)
        y1c = clamp(min(ys), 0.0, img_h)
        x2c = clamp(max(xs), 0.0, img_w)
        y2c = clamp(max(ys), 0.0, img_h)

        new_w = x2c - x1c
        new_h = y2c - y1c
        if new_w < min_size or new_h < min_size:
            continue

        new_cx = x1c + new_w / 2.0
        new_cy = y1c + new_h / 2.0
        out.append((cls, new_cx / img_w, new_cy / img_h, new_w / img_w, new_h / img_h))
    return out


def apply_color_jitter(
    img: Image.Image,
    brightness: float,
    contrast: float,
    saturation: float,
    hue: float,
) -> Image.Image:
    if brightness > 0:
        factor = 1.0 + random.uniform(-brightness, brightness)
        img = ImageEnhance.Brightness(img).enhance(factor)
    if contrast > 0:
        factor = 1.0 + random.uniform(-contrast, contrast)
        img = ImageEnhance.Contrast(img).enhance(factor)
    if saturation > 0:
        factor = 1.0 + random.uniform(-saturation, saturation)
        img = ImageEnhance.Color(img).enhance(factor)
    if hue > 0:
        shift = int(round(random.uniform(-hue, hue) * 255))
        if shift:
            hsv = img.convert("HSV")
            h, s, v = hsv.split()
            h = h.point(lambda value: (value + shift) % 256)
            img = Image.merge("HSV", (h, s, v)).convert("RGB")
    return img


def list_images(img_dir: Path) -> List[Path]:
    images: List[Path] = []
    for p in img_dir.iterdir():
        if p.is_file() and p.suffix.lower() in IMG_EXTS:
            images.append(p)
    return sorted(images)


def project_boxes(
    boxes: List[LabelItem],
    src_w: int,
    src_h: int,
    scale_x: float,
    scale_y: float,
    offset_x: float,
    offset_y: float,
    canvas_w: int,
    canvas_h: int,
    min_size: float = 1.0,
) -> List[LabelItem]:
    out: List[LabelItem] = []
    for cls, xc, yc, w, h in boxes:
        x1 = (xc - w / 2.0) * src_w * scale_x + offset_x
        y1 = (yc - h / 2.0) * src_h * scale_y + offset_y
        x2 = (xc + w / 2.0) * src_w * scale_x + offset_x
        y2 = (yc + h / 2.0) * src_h * scale_y + offset_y

        x1c = clamp(x1, 0.0, canvas_w)
        y1c = clamp(y1, 0.0, canvas_h)
        x2c = clamp(x2, 0.0, canvas_w)
        y2c = clamp(y2, 0.0, canvas_h)
        new_w = x2c - x1c
        new_h = y2c - y1c
        if new_w < min_size or new_h < min_size:
            continue

        new_cx = x1c + new_w / 2.0
        new_cy = y1c + new_h / 2.0
        out.append((cls, new_cx / canvas_w, new_cy / canvas_h, new_w / canvas_w, new_h / canvas_h))
    return out


def load_sample(sample_path: Path, labels_dir: Path) -> Tuple[Image.Image, List[LabelItem]]:
    label_path = labels_dir / f"{sample_path.stem}.txt"
    with Image.open(sample_path) as image:
        return image.convert("RGB"), read_labels(label_path)


class MixAugmentation:
    """MixUp enhancement for two images."""

    def __init__(
        self,
        alpha: float = 0.5,
        beta: float = 0.5,
        min_lambda: float = 0.1,
        max_lambda: float = 0.9,
    ) -> None:
        self.alpha = alpha
        self.beta = beta
        self.min_lambda = min_lambda
        self.max_lambda = max_lambda

    def simple_lambda(self) -> float:
        lambda_value = random.betavariate(self.alpha, self.beta)
        return clamp(lambda_value, self.min_lambda, self.max_lambda)

    def apply_mixup(
        self,
        image1: Image.Image,
        image2: Image.Image,
        label1: List[LabelItem],
        label2: List[LabelItem],
    ) -> Tuple[Image.Image, List[LabelItem]]:
        target_size = image1.size
        image2_resized = image2.resize(target_size, resample=Image.BICUBIC)
        lambda_val = self.simple_lambda()
        mixed_image = Image.blend(image1, image2_resized, 1.0 - lambda_val)

        img2_boxes = project_boxes(
            label2,
            src_w=image2.size[0],
            src_h=image2.size[1],
            scale_x=target_size[0] / image2.size[0],
            scale_y=target_size[1] / image2.size[1],
            offset_x=0.0,
            offset_y=0.0,
            canvas_w=target_size[0],
            canvas_h=target_size[1],
        )
        return mixed_image, list(label1) + img2_boxes


class MosaicAugmentation:
    """Mosaic enhancement that combines four images into one image."""

    def __init__(self, fill_value: int = 114) -> None:
        self.fill_value = fill_value

    def _ensure_four_samples(self, samples: List[Tuple[Image.Image, List[LabelItem]]]) -> List[Tuple[Image.Image, List[LabelItem]]]:
        if not samples:
            blank = Image.new("RGB", (640, 640), (self.fill_value, self.fill_value, self.fill_value))
            return [(blank, [])] * 4
        expanded = list(samples)
        while len(expanded) < 4:
            expanded.append(random.choice(samples))
        return expanded[:4]

    def mosaic_augmentation(
        self,
        samples: List[Tuple[Image.Image, List[LabelItem]]],
        output_size: Tuple[int, int],
        min_box: float = 1.0,
    ) -> Tuple[Image.Image, List[LabelItem]]:
        out_w, out_h = output_size
        mosaic_image = Image.new("RGB", (out_w, out_h), (self.fill_value, self.fill_value, self.fill_value))
        mosaic_labels: List[LabelItem] = []
        split_x = random.randint(max(1, out_w // 4), max(1, (3 * out_w) // 4))
        split_y = random.randint(max(1, out_h // 4), max(1, (3 * out_h) // 4))
        regions = [
            (0, 0, split_x, split_y),
            (split_x, 0, out_w, split_y),
            (0, split_y, split_x, out_h),
            (split_x, split_y, out_w, out_h),
        ]

        for (image, labels), (x1, y1, x2, y2) in zip(self._ensure_four_samples(samples), regions):
            region_w = max(1, x2 - x1)
            region_h = max(1, y2 - y1)
            src_w, src_h = image.size
            scale = min(region_w / src_w, region_h / src_h)
            new_w = max(1, int(round(src_w * scale)))
            new_h = max(1, int(round(src_h * scale)))
            resized = image.resize((new_w, new_h), resample=Image.BICUBIC)
            start_x = x1 + (region_w - new_w) // 2
            start_y = y1 + (region_h - new_h) // 2
            mosaic_image.paste(resized, (start_x, start_y))
            mosaic_labels.extend(
                project_boxes(
                    labels,
                    src_w=src_w,
                    src_h=src_h,
                    scale_x=scale,
                    scale_y=scale,
                    offset_x=float(start_x),
                    offset_y=float(start_y),
                    canvas_w=out_w,
                    canvas_h=out_h,
                    min_size=min_box,
                )
            )

        return mosaic_image, mosaic_labels


def choose_augmentation_mode(
    mosaic_prob: float,
    mixup_prob: float,
    sample_count: int,
) -> str:
    weighted_modes: List[Tuple[str, float]] = []
    if sample_count >= 2 and mosaic_prob > 0:
        weighted_modes.append(("mosaic", mosaic_prob))
    if sample_count >= 2 and mixup_prob > 0:
        weighted_modes.append(("mixup", mixup_prob))

    used_weight = sum(weight for _, weight in weighted_modes)
    weighted_modes.append(("basic", max(0.0, 1.0 - used_weight)))
    total_weight = sum(weight for _, weight in weighted_modes)
    if total_weight <= 0:
        return "basic"

    roll = random.random() * total_weight
    running = 0.0
    for mode, weight in weighted_modes:
        running += weight
        if roll <= running:
            return mode
    return "basic"


def safe_dataset_name(name: str) -> str:
    raw = str(name or "").strip()
    sanitized = re.sub(r'[<>:"/\\|?*]+', "_", raw)
    sanitized = re.sub(r"\s+", "_", sanitized).strip(" ._")
    return sanitized or "default"


def clear_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def collect_image_label_pairs(images_dir: Path, labels_dir: Path) -> List[Tuple[Path, Path]]:
    pairs: List[Tuple[Path, Path]] = []
    if not images_dir.exists() or not labels_dir.exists():
        return pairs
    for image_path in list_images(images_dir):
        label_path = labels_dir / f"{image_path.stem}.txt"
        if label_path.exists():
            pairs.append((image_path, label_path))
    return pairs


def seed_raw_dataset_if_needed(structure: Dict[str, Path]) -> List[Tuple[Path, Path]]:
    raw_pairs = collect_image_label_pairs(structure["images_raw"], structure["labels_raw"])
    if raw_pairs:
        return raw_pairs

    train_pairs = collect_image_label_pairs(structure["images_train"], structure["labels_train"])
    if train_pairs:
        structure["images_raw"].mkdir(parents=True, exist_ok=True)
        structure["labels_raw"].mkdir(parents=True, exist_ok=True)
        for image_path, label_path in train_pairs:
            shutil.copy2(image_path, structure["images_raw"] / image_path.name)
            shutil.copy2(label_path, structure["labels_raw"] / label_path.name)
        return collect_image_label_pairs(structure["images_raw"], structure["labels_raw"])

    return []


def split_pairs(
    pairs: List[Tuple[Path, Path]],
    train_images_dir: Path,
    train_labels_dir: Path,
    val_images_dir: Path,
    val_labels_dir: Path,
    train_ratio: float,
    seed: int,
) -> Tuple[int, int]:
    clear_directory(train_images_dir)
    clear_directory(train_labels_dir)
    clear_directory(val_images_dir)
    clear_directory(val_labels_dir)

    rng = random.Random(seed)
    shuffled_pairs = list(pairs)
    rng.shuffle(shuffled_pairs)

    if len(shuffled_pairs) == 1:
        train_count = 1
    else:
        tentative = int(len(shuffled_pairs) * train_ratio)
        train_count = min(max(tentative, 1), len(shuffled_pairs) - 1)
    val_count = len(shuffled_pairs) - train_count

    for index, (image_path, label_path) in enumerate(shuffled_pairs):
        target_images_dir = train_images_dir if index < train_count else val_images_dir
        target_labels_dir = train_labels_dir if index < train_count else val_labels_dir
        shutil.copy2(image_path, target_images_dir / image_path.name)
        shutil.copy2(label_path, target_labels_dir / label_path.name)

    return train_count, val_count


def resolve_dataset_structure(dataset_root: Path, dataset_name: str) -> Tuple[str, Dict[str, Path]]:
    dataset_key = safe_dataset_name(dataset_name)
    dataset_dir = dataset_root / dataset_key
    structure = {
        "dataset_dir": dataset_dir,
        "images_raw": dataset_dir / "images" / "raw",
        "labels_raw": dataset_dir / "labels" / "raw",
        "images_train": dataset_dir / "images" / "train",
        "labels_train": dataset_dir / "labels" / "train",
        "images_val": dataset_dir / "images" / "val",
        "labels_val": dataset_dir / "labels" / "val",
    }
    for path in structure.values():
        path.mkdir(parents=True, exist_ok=True)
    return dataset_key, structure


def augment_dataset(
    img_dir: Path,
    lbl_dir: Path,
    out_img: Path,
    out_lbl: Path,
    copies: int,
    translate: int,
    rotate: float,
    rotate_min: float,
    rotate_max: float,
    hflip: float,
    vflip: float,
    brightness: float,
    contrast: float,
    saturation: float,
    hue: float,
    mixup_prob: float,
    mixup_alpha: float,
    mixup_beta: float,
    mixup_min_lambda: float,
    mixup_max_lambda: float,
    mosaic_prob: float,
    mosaic_fill: int,
    keep_original: bool,
    min_box: float,
) -> Tuple[int, int]:
    out_img.mkdir(parents=True, exist_ok=True)
    out_lbl.mkdir(parents=True, exist_ok=True)

    if not img_dir.exists():
        raise FileNotFoundError(f"Image directory not found: {img_dir}")
    if not lbl_dir.exists():
        raise FileNotFoundError(f"Label directory not found: {lbl_dir}")

    images = list_images(img_dir)
    if not images:
        raise FileNotFoundError(f"No images found in {img_dir}")

    samples: List[SampleItem] = [(image_path, read_labels(lbl_dir / f"{image_path.stem}.txt")) for image_path in images]
    mixup_augmentation = MixAugmentation(
        alpha=mixup_alpha,
        beta=mixup_beta,
        min_lambda=mixup_min_lambda,
        max_lambda=mixup_max_lambda,
    )
    mosaic_augmentation = MosaicAugmentation(fill_value=mosaic_fill)
    augmented_count = 0
    for img_path, boxes in samples:
        stem = img_path.stem
        with Image.open(img_path) as im:
            im = im.convert("RGB")
            w, h = im.size

            if keep_original:
                out_img_path = out_img / img_path.name
                out_lbl_path = out_lbl / f"{stem}.txt"
                im.save(out_img_path)
                write_labels(out_lbl_path, boxes)

            for i in range(copies):
                aug_mode = choose_augmentation_mode(mosaic_prob, mixup_prob, len(samples))
                aug = im.copy()
                aug_boxes = list(boxes)

                if aug_mode == "mixup":
                    partner_path, partner_boxes = random.choice(samples)
                    if partner_path == img_path and len(samples) > 1:
                        partner_candidates = [sample for sample in samples if sample[0] != img_path]
                        partner_path, partner_boxes = random.choice(partner_candidates)
                    partner_image, _ = load_sample(partner_path, lbl_dir)
                    aug, aug_boxes = mixup_augmentation.apply_mixup(aug, partner_image, aug_boxes, partner_boxes)
                elif aug_mode == "mosaic":
                    other_samples = [sample for sample in samples if sample[0] != img_path]
                    selected = [(im.copy(), list(boxes))]
                    chosen_paths = random.sample(other_samples, k=min(3, len(other_samples))) if other_samples else []
                    for partner_path, partner_boxes in chosen_paths:
                        partner_image, _ = load_sample(partner_path, lbl_dir)
                        selected.append((partner_image, partner_boxes))
                    aug, aug_boxes = mosaic_augmentation.mosaic_augmentation(selected, output_size=(w, h), min_box=min_box)

                dx = random.randint(-translate, translate) if translate > 0 else 0
                dy = random.randint(-translate, translate) if translate > 0 else 0
                if dx != 0 or dy != 0:
                    translated = Image.new("RGB", (w, h), color=(114, 114, 114))
                    translated.paste(aug, (dx, dy))
                    aug = translated
                    aug_boxes = translate_boxes(aug_boxes, dx, dy, w, h, min_size=min_box)

                if rotate_max > 0:
                    min_angle = min(abs(rotate_min), abs(rotate_max))
                    max_angle = max(abs(rotate_min), abs(rotate_max))
                    magnitude = random.uniform(min_angle, max_angle)
                    angle = magnitude if random.random() < 0.5 else -magnitude
                elif rotate > 0:
                    angle = random.uniform(-rotate, rotate)
                else:
                    angle = 0.0
                if abs(angle) > 1e-6:
                    aug = aug.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(0, 0, 0))
                    aug_boxes = rotate_boxes(aug_boxes, angle, w, h, min_size=min_box)

                do_h = random.random() < hflip if hflip > 0 else False
                do_v = random.random() < vflip if vflip > 0 else False
                if do_h or do_v:
                    if do_h:
                        aug = aug.transpose(Image.FLIP_LEFT_RIGHT)
                    if do_v:
                        aug = aug.transpose(Image.FLIP_TOP_BOTTOM)
                    aug_boxes = flip_boxes(aug_boxes, do_h, do_v)

                aug = apply_color_jitter(aug, brightness, contrast, saturation, hue)

                out_name = f"{stem}_{aug_mode}{i+1}.jpg"
                out_img_path = out_img / out_name
                out_lbl_path = out_lbl / f"{Path(out_name).stem}.txt"
                aug.save(out_img_path, quality=95)
                write_labels(out_lbl_path, aug_boxes)
                augmented_count += 1

    return len(images), augmented_count


def main() -> int:
    ap = argparse.ArgumentParser(description="YOLO dataset augmentation with label-safe transforms")
    ap.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT), help="Dataset root directory for named datasets")
    ap.add_argument("--dataset-name", default="", help="Named dataset under dataset root, e.g. name1 or name2")
    ap.add_argument("--train-ratio", type=float, default=0.8, help="Train split ratio used when dataset-name is provided")
    ap.add_argument("--images", default=str(DEFAULT_IMAGES), help="Image directory")
    ap.add_argument("--labels", default=str(DEFAULT_LABELS), help="Label directory (YOLO txt)")
    ap.add_argument("--out-images", default=str(DEFAULT_OUT_IMAGES), help="Output image directory")
    ap.add_argument("--out-labels", default=str(DEFAULT_OUT_LABELS), help="Output label directory")
    ap.add_argument("--copies", type=int, default=3, help="Augmented copies per image")
    ap.add_argument("--seed", type=int, default=42, help="Random seed")
    ap.add_argument("--translate", type=int, default=10, help="Max translation in pixels (dx/dy in [-t, t])")
    ap.add_argument("--rotate", type=float, default=180.0, help="Legacy max rotation in degrees when rotate-max is 0")
    ap.add_argument("--rotate-min", type=float, default=20.0, help="Minimum absolute rotation angle in degrees")
    ap.add_argument("--rotate-max", type=float, default=180.0, help="Maximum absolute rotation angle in degrees")
    ap.add_argument("--hflip", type=float, default=0.5, help="Horizontal flip probability")
    ap.add_argument("--vflip", type=float, default=0.0, help="Vertical flip probability")
    ap.add_argument("--brightness", type=float, default=0.32, help="Brightness jitter (0-1)")
    ap.add_argument("--contrast", type=float, default=0.30, help="Contrast jitter (0-1)")
    ap.add_argument("--saturation", type=float, default=0.35, help="Saturation jitter (0-1)")
    ap.add_argument("--hue", type=float, default=0.12, help="Hue jitter strength (0-1)")
    ap.add_argument("--mixup-prob", type=float, default=0.2, help="Probability of applying MixUp")
    ap.add_argument("--mixup-alpha", type=float, default=0.5, help="MixUp beta distribution alpha")
    ap.add_argument("--mixup-beta", type=float, default=0.5, help="MixUp beta distribution beta")
    ap.add_argument("--mixup-min-lambda", type=float, default=0.1, help="Minimum MixUp lambda")
    ap.add_argument("--mixup-max-lambda", type=float, default=0.9, help="Maximum MixUp lambda")
    ap.add_argument("--mosaic-prob", type=float, default=0.45, help="Probability of applying Mosaic")
    ap.add_argument("--mosaic-fill", type=int, default=114, help="Mosaic background fill value")
    ap.add_argument("--keep-original", action="store_true", help="Copy original images/labels to output")
    ap.add_argument("--min-box", type=float, default=1.0, help="Min box size (pixels) after transform")
    args = ap.parse_args()

    if args.copies < 1:
        print("Copies must be at least 1.")
        return 1
    if not 0.1 <= args.train_ratio <= 0.95:
        print("Train ratio must be between 0.1 and 0.95.")
        return 1
    if not 0.0 <= args.mixup_prob <= 1.0:
        print("MixUp probability must be between 0 and 1.")
        return 1
    if not 0.0 <= args.mosaic_prob <= 1.0:
        print("Mosaic probability must be between 0 and 1.")
        return 1

    random.seed(args.seed)

    try:
        if args.dataset_name:
            dataset_root = Path(args.dataset_root)
            dataset_key, structure = resolve_dataset_structure(dataset_root, args.dataset_name)
            raw_pairs = seed_raw_dataset_if_needed(structure)
            if not raw_pairs:
                print(f"Dataset '{dataset_key}' has no source images to augment.")
                return 1

            with tempfile.TemporaryDirectory(prefix=f"augment_{dataset_key}_", dir=str(structure['dataset_dir'])) as temp_dir:
                temp_root = Path(temp_dir)
                temp_images = temp_root / "images"
                temp_labels = temp_root / "labels"
                _, augmented_count = augment_dataset(
                    img_dir=structure["images_raw"],
                    lbl_dir=structure["labels_raw"],
                    out_img=temp_images,
                    out_lbl=temp_labels,
                    copies=args.copies,
                    translate=args.translate,
                    rotate=args.rotate,
                    rotate_min=args.rotate_min,
                    rotate_max=args.rotate_max,
                    hflip=args.hflip,
                    vflip=args.vflip,
                    brightness=args.brightness,
                    contrast=args.contrast,
                    saturation=args.saturation,
                    hue=args.hue,
                    mixup_prob=args.mixup_prob,
                    mixup_alpha=args.mixup_alpha,
                    mixup_beta=args.mixup_beta,
                    mixup_min_lambda=args.mixup_min_lambda,
                    mixup_max_lambda=args.mixup_max_lambda,
                    mosaic_prob=args.mosaic_prob,
                    mosaic_fill=args.mosaic_fill,
                    keep_original=False,
                    min_box=args.min_box,
                )
                augmented_pairs = collect_image_label_pairs(temp_images, temp_labels)
                all_pairs = list(raw_pairs) + augmented_pairs
                train_count, val_count = split_pairs(
                    pairs=all_pairs,
                    train_images_dir=structure["images_train"],
                    train_labels_dir=structure["labels_train"],
                    val_images_dir=structure["images_val"],
                    val_labels_dir=structure["labels_val"],
                    train_ratio=args.train_ratio,
                    seed=args.seed,
                )

            print(
                f"Done. Dataset: {dataset_key}\n"
                f"Raw source images: {len(raw_pairs)}\n"
                f"Augmented images: {augmented_count}\n"
                f"Train split: {train_count}\n"
                f"Val split: {val_count}\n"
                f"Train images dir: {structure['images_train']}\n"
                f"Val images dir: {structure['images_val']}"
            )
            return 0

        out_img = Path(args.out_images)
        out_lbl = Path(args.out_labels)
        augment_dataset(
            img_dir=Path(args.images),
            lbl_dir=Path(args.labels),
            out_img=out_img,
            out_lbl=out_lbl,
            copies=args.copies,
            translate=args.translate,
            rotate=args.rotate,
            rotate_min=args.rotate_min,
            rotate_max=args.rotate_max,
            hflip=args.hflip,
            vflip=args.vflip,
            brightness=args.brightness,
            contrast=args.contrast,
            saturation=args.saturation,
            hue=args.hue,
            mixup_prob=args.mixup_prob,
            mixup_alpha=args.mixup_alpha,
            mixup_beta=args.mixup_beta,
            mixup_min_lambda=args.mixup_min_lambda,
            mixup_max_lambda=args.mixup_max_lambda,
            mosaic_prob=args.mosaic_prob,
            mosaic_fill=args.mosaic_fill,
            keep_original=args.keep_original,
            min_box=args.min_box,
        )
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    print(f"Done. Output images: {out_img}\nOutput labels: {out_lbl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
