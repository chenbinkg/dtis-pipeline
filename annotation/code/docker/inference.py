#!/usr/bin/env python3

from PIL import Image
import os
import json
import boto3
import time
import numpy as np
from rfdetr import RFDETRBase
import supervision as sv


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
    for i, (bbox, class_id, conf) in enumerate(zip(detections.xyxy, detections.class_id, detections.confidence)):
        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1
        
        result = {
            "label": categories[class_id]["name"],
            "confidence": float(conf),
            "boundingBox": {
                "left": float(x1 / image.width),
                "top": float(y1 / image.height),
                "width": float(width / image.width),
                "height": float(height / image.height)
            },
            "class_id": int(class_id)
        }
        results.append(result)
    
    # Save results
    with open(output_path, 'w') as f:
        json.dump(results, f)
    
    return results

def main():
    """Main function to run the processing job."""
    print("Starting RFDETR processing job")
    
    # SageMaker paths
    input_data_path = '/opt/ml/processing/input'
    output_data_path = '/opt/ml/processing/output'
    model_path = './checkpoints/checkpoint_best_regular.pth'
    
    # Ensure output directory exists
    os.makedirs(output_data_path, exist_ok=True)
    
    # Check model file existence and size
    if os.path.exists(model_path):
        model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
        print(f"Found model at {model_path} (Size: {model_size_mb:.2f} MB)")
    else:
        print(f"WARNING: Model file not found at {model_path}")
        # Try to download from S3 if environment variable is set
        model_s3_uri = os.environ.get('MODEL_S3_URI')
        if model_s3_uri:
            print(f"Attempting to download model from {model_s3_uri}")
            try:
                s3_path_parts = model_s3_uri.replace('s3://', '').split('/')
                bucket = s3_path_parts[0]
                key = '/'.join(s3_path_parts[1:])
                
                s3_client = boto3.client('s3')
                os.makedirs(os.path.dirname(model_path), exist_ok=True)
                s3_client.download_file(bucket, key, model_path)
                
                model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
                print(f"Downloaded model (Size: {model_size_mb:.2f} MB)")
            except Exception as e:
                print(f"Failed to download model from S3: {e}")
                return
    
    print(f"Loading model from {model_path}")
    try:
        model = RFDETRBase(pretrain_weights=model_path)
        print("Model loaded successfully")
    except Exception as e:
        print(f"Error loading model: {e}")
        return
    
    # Process all images in the input directory
    start_time = time.time()
    processed_count = 0
    
    for root, _, files in os.walk(input_data_path):
        for file in files:
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp')):
                input_file_path = os.path.join(root, file)
                relative_path = os.path.relpath(input_file_path, input_data_path)
                output_file_path = os.path.join(output_data_path, f"{os.path.splitext(relative_path)[0]}.json")
                
                if os.path.exists(output_file_path):
                    print(f"Skipping {relative_path}, already processed")
                    continue
                
                # Ensure output directory for this file exists
                os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
                
                print(f"Processing {relative_path}")
                try:
                    results = process_image(input_file_path, output_file_path, model)
                    print(f"Found {len(results)} objects in {relative_path}")
                    processed_count += 1
                except Exception as e:
                    print(f"Error processing {relative_path}: {e}")
    
    elapsed_time = time.time() - start_time
    print(f"Processed {processed_count} images in {elapsed_time:.2f} seconds")
    print("Processing job complete")

if __name__ == "__main__":
    main()