#!/usr/bin/env python3

from PIL import Image
import argparse
import os
import json
import boto3
import time
import numpy as np
import logging
from rfdetr import RFDETRBase
import supervision as sv
from datetime import datetime

_logger = logging.getLogger()
_logger.setLevel(logging.INFO)

def process_image(image_path, output_path, model):
    """Process a single image with the RFDETR model."""
    categories = [
        {"id": 0, "name": 'fish', "supercategory": "animal"}, 
        {"id": 1, "name": 'jellyfish', "supercategory": "animal"}, 
        {"id": 2, "name": "penguin", "supercategory": "animal"}, 
        {"id": 3, "name": "puffer_fish", "supercategory": "animal"}, 
        {"id": 4, "name": "shark", "supercategory": "animal"}, 
        {"id": 5, "name": "stingray", "supercategory": "animal"}, 
        {"id": 6, "name": "starfish","supercategory": "animal"}
    ]
    
    image = Image.open(image_path)
    detections = model.predict(image, threshold=0.5)
    
    # Prepare results in a format compatible with SageMaker Ground Truth
    results = []
    manifest_data = {
        "source-ref": image_path
    }
    class_map = {}
    anno = [] # to collect bbox for all labels
    confs = [] # to collect confidence for all labels
    for class_id in np.unique(detections.class_id):
        # find index for same labels
        idx = [i for i, e in enumerate(detections.class_id) if e == class_id]
        label = categories[class_id]["name"]
        class_map[str(class_id)] = label
        # Save bounding boxes, labels, and logits to a manifest file
        for i in idx:
            results.append(i)
            bbox = detections.xyxy[i]
            conf = detections.confidence[i]
            x1, y1, x2, y2 = bbox
            width = x2 - x1
            height = y2 - y1
            top = y1 # y1
            left = x1 # x1
            anno.append({
                        "class_id": str(class_id),
                        "top": int(top),
                        "left": int(left),
                        "height": int(height),
                        "width": int(width)
                    })
            confs.append({"confidence": float(conf)})
            label_data = {
                "bounding-box": {
                    "image_size": [{"width": image.width, "height": image.height, "depth": 3}],
                    "annotations": anno
                },
                "bounding-box-metadata": {
                    "objects": confs,
                    "class-map": class_map,
                    "type": "groundtruth/object-detection",
                    "human-annotated": "no",
                    "creation-date": datetime.now().isoformat(),
                    "job-name": f"labeling-job/rfdetr"
                }
            }
        manifest_data = {**manifest_data, **label_data}
    
    # Save results
    with open(output_path, 'w') as f:
        json.dump(manifest_data, f)
    
    return results

def main():
    """
    Main function to run the processing job.
    This function loads the RFDETR model, processes images from the input directory,
    and saves the results in the output directory.
    """
    # SageMaker paths
    input_data_path = '/opt/ml/processing/input'
    output_data_path = '/opt/ml/processing/output'
    model_path = './checkpoints/checkpoint_best_regular.pth'
    
    # Ensure output directory exists
    os.makedirs(output_data_path, exist_ok=True)
    
    # Check model file existence and size
    if os.path.exists(model_path):
        model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
        _logger.info(f"Found model at {model_path} (Size: {model_size_mb:.2f} MB)")
    else:
        _logger.info(f"WARNING: Model file not found at {model_path}")
        # Try to download from S3 if environment variable is set
        model_s3_uri = os.environ.get('MODEL_S3_URI')
        if model_s3_uri:
            _logger.info(f"Attempting to download model from {model_s3_uri}")
            try:
                s3_path_parts = model_s3_uri.replace('s3://', '').split('/')
                bucket = s3_path_parts[0]
                key = '/'.join(s3_path_parts[1:])
                
                s3_client = boto3.client('s3')
                os.makedirs(os.path.dirname(model_path), exist_ok=True)
                s3_client.download_file(bucket, key, model_path)
                
                model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
                _logger.info(f"Downloaded model (Size: {model_size_mb:.2f} MB)")
            except Exception as e:
                _logger.info(f"Failed to download model from S3: {e}")
                return
    
    _logger.info(f"Loading model from {model_path}")
    try:
        model = RFDETRBase(pretrain_weights=model_path)
        _logger.info("Model loaded successfully")
    except Exception as e:
        _logger.error(f"Error loading model: {e}")
        return
    
    # Process all images in the input directory
    start_time = time.time()
    processed_count = 0
    
    for root, _, files in os.walk(input_data_path):
        for file in sorted(files):
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp')):
                input_file_path = os.path.join(root, file)
                relative_path = os.path.relpath(input_file_path, input_data_path)
                output_file_path = os.path.join(output_data_path, f"{os.path.splitext(relative_path)[0]}.json")
                
                if os.path.exists(output_file_path):
                    _logger.warning(f"Skipping {relative_path}, already processed")
                    continue
                
                # Ensure output directory for this file exists
                os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
                
                _logger.info(f"Processing {relative_path}")
                try:
                    results = process_image(input_file_path, output_file_path, model)
                    _logger.info(f"Found {len(results)} objects in {relative_path}")
                    processed_count += 1
                except Exception as e:
                    _logger.error(f"Error processing {relative_path}: {e}")
    
    elapsed_time = time.time() - start_time
    _logger.info(f"Processed {processed_count} images in {elapsed_time:.2f} seconds")
    _logger.info("Processing job complete")

if __name__ == "__main__":
    main()