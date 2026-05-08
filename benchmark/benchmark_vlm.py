"""COCO val2017 bird classification benchmark using a Vision Language Model.

Sends images to a VLM via an OpenAI-compatible API and asks whether there is
a bird in the image (binary yes/no), then evaluates against COCO ground truth.

Usage (mac LM Studio):
    python benchmark_vlm.py --backend mac --dataset balcony
    python benchmark_vlm.py --backend mac --dataset coco --coco-dir data/coco

Usage (linux llama-server):
    python benchmark_vlm.py --backend linux --dataset coco --coco-dir data/coco

Usage (Windows LM Studio):
    python benchmark_vlm.py --backend windows --dataset balcony --no-think

Usage (custom):
    python benchmark_vlm.py --base-url http://localhost:8080/v1 --model qwen3.5-35b \
        --dataset coco --coco-dir data/coco --output-dir results
"""
import argparse
import base64
import json
import os
import random
import re
import sys
import time

from openai import OpenAI
from tabulate import tabulate

BIRD_CATEGORY_ID = 16

# Backend presets
# no_think_method:
#   "token"      - prepend /no_think to the user message (LM Studio / any server)
#   "extra_body" - pass chat_template_kwargs via extra_body (llama.cpp server)
BACKENDS = {
    "mac": {
        "base_url": "http://192.168.2.2:1234/v1",
        "model": "mlx-community/qwen3.5-35b-a3b",
        # LM Studio ignores extra_body/chat_template_kwargs; prefill an empty
        # <think> block so the model skips reasoning entirely.
        "no_think_method": "prefill",
    },
    "linux": {
        "base_url": "http://localhost:8080/v1",
        "model": "qwen3.5-35b",
        "no_think_method": "extra_body",
    },
    "windows": {
        "base_url": "http://localhost:1234/v1",
        "model": "qwen3.6-35b-a3b@q4_k_xl",
        "no_think_method": "prefill",
    },
}

# Ground-truth labels for the balcony example images.
# Labelled by visual inspection:
#   115859092 - pigeon flying/landing visible upper-right
#   115902512 - pigeon clearly sitting on balcony railing
#   115905698 - bird (small, on rooftop edge in background)
#   115908470 - no bird
BALCONY_LABELS = {
    "PXL_20260302_115859092.RAW-01.COVER.jpg": True,
    "PXL_20260302_115902512.RAW-01.COVER.jpg": True,
    "PXL_20260302_115905698.RAW-01.COVER.jpg": True,
    "PXL_20260302_115908470.RAW-01.COVER.jpg": False,
}

PROMPT = """Is there a bird in this image?

Reply with ONLY a JSON object in this exact format, nothing else:
{"bird": true, "confidence": 0.95}

Rules:
- "bird": true if you see one or more birds, false otherwise
- "confidence": how sure you are of your answer (0.0 to 1.0)
- Return ONLY the JSON, no explanation"""


def encode_image_base64(image_path):
    """Read image and return base64-encoded string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def classify_image(client, model, image_path, no_think=False, no_think_method="extra_body"):
    """Send an image to the VLM and parse the binary bird/no-bird response.

    no_think_method:
      "prefill"    - add assistant prefill <think>\\n\\n</think> to skip reasoning (LM Studio)
      "extra_body" - use chat_template_kwargs via extra_body (llama.cpp)

    Returns dict: {"bird": bool, "confidence": float}
    """
    b64 = encode_image_base64(image_path)

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{b64}"
            }},
        ],
    }]

    extra = {}
    if no_think:
        if no_think_method == "prefill":
            # Prefill an empty think block — model continues directly with the answer
            messages.append({"role": "assistant", "content": "<think>\n\n</think>"})
        else:
            extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                **extra,
            )
            text = resp.choices[0].message.content.strip()
            return parse_response(text)
        except Exception as e:
            err = str(e)
            if "rate" in err.lower() or "429" in err:
                wait = 5 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    API error: {err[:120]}")
                if attempt < 2:
                    time.sleep(2)
                else:
                    return None
    return None


def parse_response(text):
    """Parse VLM JSON response into {"bird": bool, "confidence": float}."""
    # Strip thinking tags and markdown fences
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'```json\s*', '', cleaned)
    cleaned = re.sub(r'```\s*', '', cleaned)
    cleaned = cleaned.strip()

    # Try to find JSON object with "bird" key
    json_match = re.search(r'\{[^{}]*"bird"\s*:.*?\}', cleaned, re.DOTALL)
    if not json_match:
        # Fallback: look for yes/no in plain text
        lower = cleaned.lower()
        if "yes" in lower or '"bird": true' in lower or '"bird":true' in lower:
            return {"bird": True, "confidence": 0.5}
        elif "no" in lower or '"bird": false' in lower or '"bird":false' in lower:
            return {"bird": False, "confidence": 0.5}
        return None

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        return None

    bird = bool(data.get("bird", False))
    confidence = float(data.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))
    return {"bird": bird, "confidence": confidence}


def evaluate(results, thresholds):
    """Compute per-threshold classification metrics.

    Each result has: image_id, has_bird_gt (bool), bird_predicted (bool), confidence.
    A prediction counts as positive when bird_predicted=True AND confidence >= threshold.
    """
    total_positive = sum(1 for r in results if r["has_bird_gt"])
    total_negative = len(results) - total_positive

    rows = []
    for thresh in sorted(thresholds):
        tp = fp = tn = fn = 0
        for r in results:
            predicted_positive = r["bird_predicted"] and r["confidence"] >= thresh
            if r["has_bird_gt"]:
                if predicted_positive:
                    tp += 1
                else:
                    fn += 1
            else:
                if predicted_positive:
                    fp += 1
                else:
                    tn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        accuracy = (tp + tn) / len(results) if results else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        rows.append({
            "threshold": thresh,
            "accuracy": accuracy,
            "recall": recall,
            "precision": precision,
            "f1": f1,
            "fdr": 1.0 - precision,
            "miss_rate": 1.0 - recall,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        })

    return rows, total_positive, total_negative


def load_balcony_images(balcony_dir):
    """Return list of (image_path, filename, has_bird_gt) for balcony examples."""
    images = []
    for filename, has_bird in BALCONY_LABELS.items():
        path = os.path.join(balcony_dir, filename)
        if not os.path.exists(path):
            print(f"  Warning: balcony image not found: {path}", file=sys.stderr)
            continue
        images.append({"path": path, "filename": filename, "has_bird_gt": has_bird})
    return images


def load_coco_images(coco_dir, num_negative, limit, seed):
    """Return list of image dicts and the set of bird image IDs."""
    from pycocotools.coco import COCO

    ann_file = os.path.join(coco_dir, "annotations", "instances_val2017.json")
    coco_gt = COCO(ann_file)

    bird_img_ids = set(coco_gt.getImgIds(catIds=[BIRD_CATEGORY_ID]))
    all_img_ids = coco_gt.getImgIds()
    non_bird_ids = [i for i in all_img_ids if i not in bird_img_ids]

    random.seed(seed)
    if limit > 0:
        n_pos = min(len(bird_img_ids), limit // 2)
        n_neg = limit - n_pos
        sampled_pos = random.sample(sorted(bird_img_ids), n_pos)
        sampled_neg = random.sample(non_bird_ids, min(n_neg, len(non_bird_ids)))
        test_img_ids = sampled_pos + sampled_neg
    else:
        sampled_neg = random.sample(non_bird_ids, min(num_negative, len(non_bird_ids)))
        test_img_ids = sorted(bird_img_ids) + sampled_neg

    images = coco_gt.loadImgs(test_img_ids)
    return images, bird_img_ids, coco_dir


def main():
    parser = argparse.ArgumentParser(
        description="Bird classification benchmark using Vision LLM",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Backend
    parser.add_argument("--backend", choices=sorted(BACKENDS), default=None,
                        help="Preset backend: 'mac' = LM Studio at 192.168.2.2:1234, "
                             "'linux' = llama-server at localhost:8080, "
                             "'windows' = LM Studio at localhost:1234")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1",
                        help="OpenAI-compatible API base URL (overridden by --backend)")
    parser.add_argument("--api-key", default="no-key",
                        help="API key (not required for local servers)")
    parser.add_argument("--model", default="qwen/qwen3-vl-235b-a22b-thinking",
                        help="Model name/slug (overridden by --backend)")

    # Dataset
    parser.add_argument("--dataset", choices=["coco", "balcony"], default="coco",
                        help="Dataset to benchmark: 'coco' = COCO val2017, "
                             "'balcony' = local balcony example images")
    parser.add_argument("--coco-dir", default=None,
                        help="Path to COCO dataset (required when --dataset coco)")
    parser.add_argument("--balcony-dir",
                        default=os.path.join(os.path.dirname(__file__), "data", "balcony-examples"),
                        help="Path to balcony example images")

    parser.add_argument("--output-dir", default="results", help="Output directory")
    parser.add_argument("--num-negative", type=int, default=125,
                        help="Number of non-bird COCO images to test for FP rate")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit total images (0 = no limit, COCO only)")
    parser.add_argument("--thresholds", default="0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9",
                        help="Confidence thresholds")
    parser.add_argument("--no-think", action="store_true",
                        help="Disable thinking mode (Qwen3.5, etc.)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for COCO sampling")
    args = parser.parse_args()

    # Apply backend preset (overrides --base-url, --model, and no_think_method)
    no_think_method = "extra_body"  # default for custom/unknown backends
    if args.backend:
        preset = BACKENDS[args.backend]
        args.base_url = preset["base_url"]
        args.model = preset["model"]
        no_think_method = preset["no_think_method"]

    # Validate dataset args
    if args.dataset == "coco" and not args.coco_dir:
        parser.error("--coco-dir is required when --dataset coco")

    thresholds = [float(t) for t in args.thresholds.split(",")]
    os.makedirs(args.output_dir, exist_ok=True)

    client = OpenAI(base_url=args.base_url, api_key=args.api_key)

    model_short = args.model.split("/")[-1]
    model_slug = re.sub(r'[^a-zA-Z0-9._-]', '_', model_short)

    # Load dataset
    if args.dataset == "balcony":
        balcony_images = load_balcony_images(args.balcony_dir)
        n_pos = sum(1 for img in balcony_images if img["has_bird_gt"])
        n_neg = len(balcony_images) - n_pos
        print(f"Dataset:  balcony examples ({len(balcony_images)} images: {n_pos} bird, {n_neg} no-bird)")
        print(f"Model:    {args.model}")
        print(f"API:      {args.base_url}")
        if args.no_think:
            print(f"No-think: {no_think_method}")
        print()

        dataset_slug = "balcony"
        cache_path = os.path.join(args.output_dir, f"vlm_{model_slug}_{dataset_slug}_results.json")
        cached = {}
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                for r in json.load(f):
                    cached[r["image_id"]] = r
            print(f"Found {len(cached)} cached results, resuming...")

        all_results = list(cached.values())
        t_start = time.time()
        processed = 0
        parse_failures = 0

        for i, img in enumerate(balcony_images):
            if img["filename"] in cached:
                continue

            result = classify_image(client, args.model, img["path"], no_think=args.no_think, no_think_method=no_think_method)

            if result is None:
                parse_failures += 1
                result = {"bird": False, "confidence": 0.0}

            entry = {
                "image_id": img["filename"],
                "has_bird_gt": img["has_bird_gt"],
                "bird_predicted": result["bird"],
                "confidence": result["confidence"],
            }
            all_results.append(entry)
            processed += 1

            marker = "BIRD" if img["has_bird_gt"] else "    "
            pred = "Y" if result["bird"] else "N"
            correct = result["bird"] == img["has_bird_gt"]
            check = "ok" if correct else ("MISS" if img["has_bird_gt"] else "FP")
            elapsed = time.time() - t_start
            print(f"  [{i+1}/{len(balcony_images)}] {marker} {img['filename']}  "
                  f"pred={pred} conf={result['confidence']:.2f} {check}  ({elapsed:.0f}s)")

        with open(cache_path, "w") as f:
            json.dump(all_results, f, indent=2)

    else:  # coco
        images, bird_img_ids, coco_dir = load_coco_images(
            args.coco_dir, args.num_negative, args.limit, args.seed
        )
        n_pos_test = sum(1 for img in images if img["id"] in bird_img_ids)
        n_neg_test = len(images) - n_pos_test
        print(f"Dataset:  COCO val2017 ({len(images)} images: {n_pos_test} bird, {n_neg_test} no-bird)")
        print(f"Model:    {args.model}")
        print(f"API:      {args.base_url}")
        if args.no_think:
            print(f"No-think: {no_think_method}")
        print()

        dataset_slug = "coco"
        cache_path = os.path.join(args.output_dir, f"vlm_{model_slug}_{dataset_slug}_results.json")
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                cached = json.load(f)
            cached_ids = set(r["image_id"] for r in cached)
            print(f"Found {len(cached_ids)} cached image results, resuming...")
        else:
            cached = []
            cached_ids = set()

        all_results = list(cached)
        t_start = time.time()
        processed = 0
        parse_failures = 0

        for i, img_info in enumerate(images):
            if img_info["id"] in cached_ids:
                continue

            image_path = os.path.join(coco_dir, "val2017", img_info["file_name"])
            if not os.path.exists(image_path):
                continue
            has_bird_gt = img_info["id"] in bird_img_ids

            result = classify_image(client, args.model, image_path, no_think=args.no_think, no_think_method=no_think_method)

            if result is None:
                parse_failures += 1
                result = {"bird": False, "confidence": 0.0}

            all_results.append({
                "image_id": img_info["id"],
                "has_bird_gt": has_bird_gt,
                "bird_predicted": result["bird"],
                "confidence": result["confidence"],
            })

            processed += 1
            elapsed = time.time() - t_start

            marker = "BIRD" if has_bird_gt else "    "
            pred = "Y" if result["bird"] else "N"
            correct = result["bird"] == has_bird_gt
            check = "ok" if correct else ("MISS" if has_bird_gt else "FP")
            print(f"  [{i+1}/{len(images)}] {marker} {img_info['file_name']}  "
                  f"pred={pred} conf={result['confidence']:.2f} {check}  ({elapsed:.0f}s)")

            if processed % 25 == 0:
                with open(cache_path, "w") as f:
                    json.dump(all_results, f)

        with open(cache_path, "w") as f:
            json.dump(all_results, f)

    elapsed = time.time() - t_start
    print(f"\nDone: {processed} new images in {elapsed:.0f}s")
    if parse_failures:
        print(f"  ({parse_failures} parse failures treated as negative)")
    print()

    # Evaluate
    rows, total_pos, total_neg = evaluate(all_results, thresholds)

    print(f"--- Per-Threshold Analysis: {model_short} ({total_pos} bird images, {total_neg} non-bird images) ---")
    table = []
    for r in rows:
        table.append([
            f"{r['threshold']:.2f}",
            f"{r['accuracy']:.3f}",
            f"{r['recall']:.3f}",
            f"{r['precision']:.3f}",
            f"{r['f1']:.3f}",
            f"{r['fdr']:.3f}",
            f"{r['miss_rate']:.3f}",
            r["tp"], r["fp"], r["tn"], r["fn"],
        ])
    headers = ["Thresh", "Acc", "Recall", "Prec", "F1", "FDR", "Miss", "TP", "FP", "TN", "FN"]
    print(tabulate(table, headers=headers, tablefmt="simple"))

    # Recommended operating point
    good = [r for r in rows if r["precision"] >= 0.95]
    if good:
        best = max(good, key=lambda r: r["recall"])
        print(f"\n  Recommended operating point (precision >= 0.95):")
        print(f"    Threshold: {best['threshold']:.2f}")
        print(f"    Recall:    {best['recall']:.3f}  (miss rate: {best['miss_rate']:.3f})")
        print(f"    Precision: {best['precision']:.3f}  (FDR: {best['fdr']:.3f})")
        print(f"    F1:        {best['f1']:.3f}")
    else:
        print(f"\n  No threshold achieves precision >= 0.95")

    # Save metrics
    metrics_path = os.path.join(args.output_dir, f"vlm_{model_slug}_{dataset_slug}_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\n  Metrics saved to {metrics_path}")


if __name__ == "__main__":
    main()
