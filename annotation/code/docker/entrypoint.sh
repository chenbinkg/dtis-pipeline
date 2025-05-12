#!/bin/bash

# This script runs at container startup to download model weights from S3
# and then execute the Python script

set -e  # Exit immediately if a command exits with non-zero status

echo "Container starting..."

# Check if MODEL_S3_URI is provided
if [ -n "$MODEL_S3_URI" ]; then
    echo "Downloading model weights from $MODEL_S3_URI"
    aws s3 cp $MODEL_S3_URI ./checkpoints/checkpoint_best_regular.pth
    
    # Verify the download
    if [ -f "./checkpoints/checkpoint_best_regular.pth" ]; then
        MODEL_SIZE=$(du -h ./checkpoints/checkpoint_best_regular.pth | cut -f1)
        echo "Model weights downloaded successfully (Size: $MODEL_SIZE)"
    else
        echo "ERROR: Failed to download model weights from S3"
        exit 1
    fi
else
    echo "WARNING: MODEL_S3_URI not set. Using model weights from container if available."
    
    # Check if model exists in container
    if [ ! -f "./checkpoints/checkpoint_best_regular.pth" ]; then
        echo "ERROR: Model weights not found in container and MODEL_S3_URI not provided"
        echo "Please set the MODEL_S3_URI environment variable to the S3 location of your model weights"
        exit 1
    fi
fi

# Execute the command passed to the container
echo "Starting inference process..."
exec "$@"