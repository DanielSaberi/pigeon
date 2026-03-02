#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data/coco"

mkdir -p "$DATA_DIR"

# Images (~1GB, 5000 images)
if [ ! -d "$DATA_DIR/val2017" ]; then
    echo "Downloading COCO val2017 images..."
    wget -q --show-progress http://images.cocodataset.org/zips/val2017.zip -O "$DATA_DIR/val2017.zip"
    unzip -q "$DATA_DIR/val2017.zip" -d "$DATA_DIR"
    rm "$DATA_DIR/val2017.zip"
else
    echo "COCO val2017 images already present."
fi

# Annotations (~0.25GB)
if [ ! -f "$DATA_DIR/annotations/instances_val2017.json" ]; then
    echo "Downloading COCO val2017 annotations..."
    wget -q --show-progress http://images.cocodataset.org/annotations/annotations_trainval2017.zip \
         -O "$DATA_DIR/annotations.zip"
    unzip -q "$DATA_DIR/annotations.zip" -d "$DATA_DIR"
    rm "$DATA_DIR/annotations.zip"
else
    echo "COCO val2017 annotations already present."
fi

echo "COCO val2017 ready at $DATA_DIR"
