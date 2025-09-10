
#!/bin/bash
set -e

# Check for required arguments
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <function_name> <script_file.py>"
  exit 1
fi

FUNC="$1"
SCRIPT="$2"
LAMBDA_BASE="./lambda/lambda_functions"
FUNC_DIR="${LAMBDA_BASE}/${FUNC}"
REQUIREMENTS_FILE="${FUNC_DIR}/requirements.txt"
ZIP_FILE="${FUNC_DIR}/lambda_${FUNC}.zip"

# Create virtual environment
python3 -m venv ${FUNC_DIR}/venv
source ${FUNC_DIR}/venv/bin/activate
pip install --upgrade pip
pip install -r ${REQUIREMENTS_FILE}
deactivate

# Determine Python version used in venv
PYTHON_VERSION=$(ls ${FUNC_DIR}/venv/lib | grep python)
SITE_PACKAGES="${FUNC_DIR}/venv/lib/${PYTHON_VERSION}/site-packages"

# Remove old zip file if exists
rm -f ${ZIP_FILE}

# Zip dependencies
zip -r9 ${ZIP_FILE} ${SITE_PACKAGES}

# Zip Lambda function code
zip -g ${ZIP_FILE} ${FUNC_DIR}/${SCRIPT}

echo "Packaged Lambda: ${ZIP_FILE}"
