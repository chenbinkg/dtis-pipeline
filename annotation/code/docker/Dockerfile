FROM python:3.11.11-bookworm

# Set working directory
WORKDIR /opt/ml/processing

# Install AWS CLI for S3 access and build dependencies for potential compiled libraries
RUN apt-get update && apt-get install -y \
    wget \
    awscli \
    libgl1-mesa-glx \
    build-essential \
    cmake \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create checkpoint directory
RUN mkdir -p ./checkpoints

# Copy your code
COPY *.py ./

# Set environment variables if needed
ENV PYTHONUNBUFFERED=1
ENV MODEL_S3_URI=""

# Create entrypoint script to download model at runtime
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Use entrypoint script
ENTRYPOINT ["/opt/ml/processing/entrypoint.sh"]