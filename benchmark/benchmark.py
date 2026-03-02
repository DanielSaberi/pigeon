"""COCO val2017 bird detection accuracy benchmark.

Evaluates detection models (SSD, YOLOv7, YOLOv8) on the COCO val2017 dataset,
focused on the bird class (category_id=16). Reports recall, precision, and
false discovery rate at multiple confidence thresholds.

Usage:
    python benchmark.py --detector yolov7 --coco-dir data/coco --model-dir models --output-dir results
    python benchmark.py --detector all --coco-dir data/coco --model-dir models --output-dir results
"""
import argparse
import json
import os
import sys
import time

import cv2
import numpy as np
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval
from tabulate import tabulate

# Insert benchmark dir first so our pycoral mock takes precedence
BENCHMARK_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BENCHMARK_DIR)

# Add pigeon source dir so we can import yolo.py
PIGEON_DIR = os.path.join(BENCHMARK_DIR, '..', 'pigeon')
sys.path.insert(1, PIGEON_DIR)

from ssd_detect import ssd_detect
from yolo import yolov7, yolov8

BIRD_CATEGORY_ID = 16  # COCO category_id for bird
BIRD_OBJ_ID = 15       # 0-indexed Object.id for bird (category_id - 1)
INFERENCE_THRESHOLD = 0.01  # Run inference at low threshold, sweep in post-processing

MODEL_FILES = {
    'ssd': 'ssdlite_mobiledet_coco_qat_postprocess.tflite',
    'efficientdet3': 'efficientdet_lite3_512_ptq.tflite',
    'yolov7': 'yolov7tiny_relu6.tflite',
    'yolov8': 'yolov8n_relu6.tflite',
}


def load_model(model_path):
    """Load a TFLite model using ai-edge-litert (or tflite-runtime fallback)."""
    try:
        from ai_edge_litert.interpreter import Interpreter
    except ImportError:
        from tflite_runtime.interpreter import Interpreter
    interpreter = Interpreter(model_path=model_path)
    interpreter.allocate_tensors()
    return interpreter


def get_input_size(interpreter):
    """Get model input dimensions as (width, height)."""
    shape = interpreter.get_input_details()[0]['shape']  # [1, H, W, 3]
    return (shape[2], shape[1])


def run_detection(detector_name, interpreter, input_size, image_path, threshold):
    """Run detection on a single image.

    Returns list of dicts in COCO result format:
        {"image_id": None, "category_id": int, "bbox": [x,y,w,h], "score": float}
    """
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        return []
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    orig_h, orig_w = img_rgb.shape[:2]

    # Resize to model input — matches pigeon.py preprocessing
    img_det = cv2.resize(img_rgb, input_size)

    if detector_name in ('ssd', 'efficientdet3'):
        objs = ssd_detect(img_det, interpreter, threshold)
    elif detector_name == 'yolov7':
        objs = yolov7(img_det, interpreter, threshold)
    elif detector_name == 'yolov8':
        objs = yolov8(img_det, interpreter, threshold)
    else:
        raise ValueError(f"Unknown detector: {detector_name}")

    # Scale from model resolution to original image resolution
    sx = orig_w / input_size[0]
    sy = orig_h / input_size[1]

    results = []
    for obj in objs:
        bbox = obj.bbox.scale(sx, sy)
        x = max(0.0, float(bbox.xmin))
        y = max(0.0, float(bbox.ymin))
        w = min(float(bbox.xmax - bbox.xmin), orig_w - x)
        h = min(float(bbox.ymax - bbox.ymin), orig_h - y)
        if w <= 0 or h <= 0:
            continue

        results.append({
            'image_id': None,  # filled by caller
            'category_id': obj.id + 1,  # convert 0-indexed to COCO category_id
            'bbox': [x, y, w, h],
            'score': float(obj.score),
        })

    return results


def run_inference_loop(detector_name, interpreter, input_size, coco_gt, coco_dir):
    """Run detection on all COCO val2017 images. Returns list of COCO-format results."""
    img_ids = coco_gt.getImgIds()
    images = coco_gt.loadImgs(img_ids)
    all_results = []

    t_start = time.time()
    for i, img_info in enumerate(images):
        image_path = os.path.join(coco_dir, 'val2017', img_info['file_name'])
        dets = run_detection(detector_name, interpreter, input_size,
                             image_path, INFERENCE_THRESHOLD)
        for d in dets:
            d['image_id'] = img_info['id']
        all_results.extend(dets)

        if (i + 1) % 200 == 0:
            elapsed = time.time() - t_start
            eta = elapsed / (i + 1) * (len(images) - i - 1)
            print(f"  [{i+1}/{len(images)}] {elapsed:.0f}s elapsed, ~{eta:.0f}s remaining")

    elapsed = time.time() - t_start
    print(f"  Inference complete: {len(images)} images in {elapsed:.0f}s")
    return all_results


def coco_eval_bird(coco_gt, all_results):
    """Run standard COCO evaluation for the bird category."""
    bird_results = [r for r in all_results if r['category_id'] == BIRD_CATEGORY_ID]
    if not bird_results:
        print("  No bird detections found!")
        return None

    coco_dt = coco_gt.loadRes(bird_results)
    coco_eval = COCOeval(coco_gt, coco_dt, 'bbox')
    coco_eval.params.catIds = [BIRD_CATEGORY_ID]
    coco_eval.evaluate()
    coco_eval.accumulate()
    coco_eval.summarize()
    return coco_eval


def compute_per_threshold_metrics(coco_gt, all_results, thresholds, iou_thresh=0.5):
    """Compute recall, precision, FDR at each confidence threshold for the bird class.

    Uses greedy IoU matching: detections sorted by score (highest first),
    each GT box matched at most once.
    """
    # Get all bird ground truth annotations
    bird_ann_ids = coco_gt.getAnnIds(catIds=[BIRD_CATEGORY_ID])
    bird_anns = coco_gt.loadAnns(bird_ann_ids)

    # Organize GT by image_id
    gt_by_image = {}
    for ann in bird_anns:
        img_id = ann['image_id']
        if img_id not in gt_by_image:
            gt_by_image[img_id] = []
        # COCO bbox format: [x, y, w, h]
        gt_by_image[img_id].append(ann['bbox'])

    total_gt = len(bird_anns)

    # Filter to bird detections only
    bird_dets = [r for r in all_results if r['category_id'] == BIRD_CATEGORY_ID]

    rows = []
    for thresh in sorted(thresholds):
        # Filter by threshold
        dets_t = [d for d in bird_dets if d['score'] >= thresh]

        # Organize detections by image (sorted by score descending)
        dets_by_image = {}
        for d in dets_t:
            img_id = d['image_id']
            if img_id not in dets_by_image:
                dets_by_image[img_id] = []
            dets_by_image[img_id].append(d)
        for img_id in dets_by_image:
            dets_by_image[img_id].sort(key=lambda x: x['score'], reverse=True)

        tp = 0
        fp = 0

        # Match detections to GT per image
        all_image_ids = set(list(gt_by_image.keys()) + list(dets_by_image.keys()))
        for img_id in all_image_ids:
            gt_boxes = list(gt_by_image.get(img_id, []))  # copy
            img_dets = dets_by_image.get(img_id, [])
            matched = [False] * len(gt_boxes)

            for det in img_dets:
                det_box = det['bbox']
                best_iou = 0
                best_idx = -1
                for gi, gt_box in enumerate(gt_boxes):
                    if matched[gi]:
                        continue
                    iou = _compute_iou(det_box, gt_box)
                    if iou > best_iou:
                        best_iou = iou
                        best_idx = gi

                if best_iou >= iou_thresh and best_idx >= 0:
                    tp += 1
                    matched[best_idx] = True
                else:
                    fp += 1

        fn = total_gt - tp
        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        fdr = 1.0 - precision
        miss_rate = 1.0 - recall

        rows.append({
            'threshold': thresh,
            'recall': recall,
            'precision': precision,
            'fdr': fdr,
            'miss_rate': miss_rate,
            'tp': tp,
            'fp': fp,
            'fn': fn,
        })

    return rows, total_gt


def _compute_iou(box_a, box_b):
    """Compute IoU between two boxes in [x, y, w, h] format."""
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b

    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh

    ix = max(ax, bx)
    iy = max(ay, by)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    if ix2 <= ix or iy2 <= iy:
        return 0.0

    inter = (ix2 - ix) * (iy2 - iy)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def print_report(detector_name, rows, total_gt):
    """Print per-threshold metrics table."""
    print(f"\n--- Per-Threshold Analysis: {detector_name} (bird class, {total_gt} GT instances) ---")
    table = []
    for r in rows:
        table.append([
            f"{r['threshold']:.2f}",
            f"{r['recall']:.3f}",
            f"{r['precision']:.3f}",
            f"{r['fdr']:.3f}",
            f"{r['miss_rate']:.3f}",
            r['tp'], r['fp'], r['fn'],
        ])
    headers = ['Threshold', 'Recall', 'Precision', 'FDR', 'Miss Rate', 'TP', 'FP', 'FN']
    print(tabulate(table, headers=headers, tablefmt='simple'))

    # Find recommended operating point: lowest threshold where precision >= 0.95
    good = [r for r in rows if r['precision'] >= 0.95]
    if good:
        best = min(good, key=lambda r: r['threshold'])
        print(f"\n  Recommended operating point (precision >= 0.95):")
        print(f"    Threshold: {best['threshold']:.2f}")
        print(f"    Recall:    {best['recall']:.3f}  (miss rate: {best['miss_rate']:.3f})")
        print(f"    Precision: {best['precision']:.3f}  (FDR: {best['fdr']:.3f})")
    else:
        print(f"\n  No threshold achieves precision >= 0.95")


def save_results(output_dir, detector_name, all_results, rows):
    """Save raw results and metrics to files."""
    os.makedirs(output_dir, exist_ok=True)

    results_path = os.path.join(output_dir, f'{detector_name}_detections.json')
    with open(results_path, 'w') as f:
        json.dump(all_results, f)
    print(f"  Raw detections saved to {results_path}")

    metrics_path = os.path.join(output_dir, f'{detector_name}_metrics.json')
    with open(metrics_path, 'w') as f:
        json.dump(rows, f, indent=2)
    print(f"  Metrics saved to {metrics_path}")


def run_single_detector(detector_name, args, thresholds):
    """Run the full benchmark pipeline for one detector."""
    model_path = os.path.join(args.model_dir, MODEL_FILES[detector_name])
    if not os.path.exists(model_path):
        print(f"  Model not found: {model_path} — skipping {detector_name}")
        return

    print(f"\n{'='*60}")
    print(f"  Benchmarking: {detector_name}")
    print(f"{'='*60}")

    # Check for cached results
    cache_path = os.path.join(args.output_dir, f'{detector_name}_detections.json')
    if os.path.exists(cache_path) and not args.force:
        print(f"  Loading cached detections from {cache_path}")
        with open(cache_path) as f:
            all_results = json.load(f)
    else:
        print(f"  Loading model: {model_path}")
        interpreter = load_model(model_path)
        input_size = get_input_size(interpreter)
        print(f"  Input size: {input_size[0]}x{input_size[1]}")

        print(f"  Running inference on COCO val2017...")
        ann_file = os.path.join(args.coco_dir, 'annotations', 'instances_val2017.json')
        coco_gt = COCO(ann_file)
        all_results = run_inference_loop(detector_name, interpreter, input_size,
                                         coco_gt, args.coco_dir)

    # Save raw results
    save_results(args.output_dir, detector_name, all_results, [])

    # COCO evaluation
    print(f"\n--- Standard COCO Evaluation: {detector_name} (bird class) ---")
    ann_file = os.path.join(args.coco_dir, 'annotations', 'instances_val2017.json')
    coco_gt = COCO(ann_file)
    coco_eval_bird(coco_gt, all_results)

    # Per-threshold analysis
    rows, total_gt = compute_per_threshold_metrics(coco_gt, all_results, thresholds)
    print_report(detector_name, rows, total_gt)

    # Save metrics
    metrics_path = os.path.join(args.output_dir, f'{detector_name}_metrics.json')
    with open(metrics_path, 'w') as f:
        json.dump(rows, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description='COCO val2017 bird detection accuracy benchmark',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--coco-dir', required=True, help='Path to COCO dataset root')
    parser.add_argument('--model-dir', required=True, help='Path to TFLite models')
    parser.add_argument('--detector', default='all',
                        help='Detector to benchmark: ssd, efficientdet3, yolov7, yolov8, or all')
    parser.add_argument('--thresholds', default='0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9',
                        help='Comma-separated confidence thresholds for analysis')
    parser.add_argument('--output-dir', default='results', help='Directory for output files')
    parser.add_argument('--force', action='store_true',
                        help='Re-run inference even if cached results exist')
    args = parser.parse_args()

    thresholds = [float(t) for t in args.thresholds.split(',')]

    if args.detector == 'all':
        detectors = ['ssd', 'efficientdet3', 'yolov7', 'yolov8']
    else:
        detectors = [args.detector]

    for det in detectors:
        run_single_detector(det, args, thresholds)

    # Summary comparison if multiple detectors
    if len(detectors) > 1:
        print(f"\n{'='*60}")
        print(f"  Summary Comparison (recommended operating points)")
        print(f"{'='*60}")
        ann_file = os.path.join(args.coco_dir, 'annotations', 'instances_val2017.json')
        coco_gt = COCO(ann_file)

        summary = []
        for det in detectors:
            metrics_path = os.path.join(args.output_dir, f'{det}_metrics.json')
            if not os.path.exists(metrics_path):
                continue
            with open(metrics_path) as f:
                rows = json.load(f)
            good = [r for r in rows if r['precision'] >= 0.95]
            if good:
                best = min(good, key=lambda r: r['threshold'])
                summary.append([
                    det,
                    f"{best['threshold']:.2f}",
                    f"{best['recall']:.3f}",
                    f"{best['precision']:.3f}",
                    f"{best['fdr']:.3f}",
                ])
            else:
                summary.append([det, 'N/A', 'N/A', 'N/A', 'N/A'])

        headers = ['Detector', 'Threshold', 'Recall', 'Precision', 'FDR']
        print(tabulate(summary, headers=headers, tablefmt='simple'))


if __name__ == '__main__':
    main()
