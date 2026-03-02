#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL_DIR="$SCRIPT_DIR/models"
PIGEON_MODEL_DIR="$SCRIPT_DIR/../pigeon/models"

mkdir -p "$MODEL_DIR"

# SSD MobileDet - CPU version (non-EdgeTPU)
if [ ! -f "$MODEL_DIR/ssdlite_mobiledet_coco_qat_postprocess.tflite" ]; then
    echo "Downloading SSD MobileDet (CPU)..."
    wget -q --show-progress \
        https://raw.githubusercontent.com/google-coral/test_data/master/ssdlite_mobiledet_coco_qat_postprocess.tflite \
        -O "$MODEL_DIR/ssdlite_mobiledet_coco_qat_postprocess.tflite"
else
    echo "SSD MobileDet (CPU) already present."
fi

# COCO labels
if [ ! -f "$MODEL_DIR/coco_labels.txt" ]; then
    echo "Downloading COCO labels..."
    wget -q --show-progress \
        https://raw.githubusercontent.com/google-coral/test_data/master/coco_labels.txt \
        -O "$MODEL_DIR/coco_labels.txt"
else
    echo "COCO labels already present."
fi

# YOLO models - copy from pigeon/models/ if available
for model in yolov7tiny_relu6.tflite yolov8n_relu6.tflite; do
    if [ ! -f "$MODEL_DIR/$model" ]; then
        if [ -f "$PIGEON_MODEL_DIR/$model" ]; then
            echo "Copying $model from pigeon/models/..."
            cp "$PIGEON_MODEL_DIR/$model" "$MODEL_DIR/$model"
        else
            echo "WARNING: $model not found in $PIGEON_MODEL_DIR"
            echo "  Download it manually and place in $MODEL_DIR/"
        fi
    else
        echo "$model already present."
    fi
done

echo ""
echo "Models ready at $MODEL_DIR"
