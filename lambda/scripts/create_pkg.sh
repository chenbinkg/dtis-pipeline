#!/bin/bash

echo "Executing create_pkg.sh..."

cd $path_cwd # Change to the directory containing lambda functions and scripts folders
parent_dir=$(dirname "$path_cwd")
echo "$parent_dir"
# mkdir $dir_name

# remove the zip file if it exists in the terraform directory
if [ -f "$parent_dir/infrastructure/2-seafloor-data/lambda_$function_name.zip" ]; then
  rm "$parent_dir/infrastructure/2-seafloor-data/lambda_$function_name.zip"
fi

# Verify runtime path and print Python version
runtime_path=$(command -v "$runtime")
if [ -z "$runtime_path" ]; then
  echo "Error: $runtime not found. Ensure the correct Python version is installed."
  exit 1
fi

# Display the Python version to confirm it's the expected one
echo "Using Python interpreter at: $runtime_path"
"$runtime_path" --version || { echo "Error retrieving Python version"; exit 1; }

# Create and activate virtual environment...
# virtualenv -p $runtime env_$function_name
"$runtime" -m venv "$path_cwd/env_$function_name"
source $path_cwd/env_$function_name/bin/activate || { echo "Failed to activate virtual environment"; exit 1; }

# Installing python dependencies...
FILE=$path_cwd/lambda_functions/$function_name/requirements.txt

if [ -f "$FILE" ]; then
  echo "Installing dependencies..."
  echo "From: requirement.txt file exists..."
  pip install -r "$FILE" || { echo "Dependency installation failed"; exit 1; }

else
  echo "requirement.txt does not exist! no dependencies to install."
fi

# Deactivate virtual environment...
deactivate

# Create deployment package...
echo "Creating deployment package..."

# # remove copying files from site-packages to lambda_functions directory, replaced with zip file creation
# zip -r9 "$parent_dir/infrastructure/2-seafloor-data/$function_name.zip" $path_cwd/env_$function_name/lib/*/site-packages/.

# Only zip site-packages if requirements.txt exists and the site-packages directory is found
if [ -f "$FILE" ]; then
  site_pkg_dir=$(echo "$path_cwd/env_$function_name/lib/"*/site-packages)
  if [ -d "$site_pkg_dir" ]; then
    # zip -r9 "$parent_dir/infrastructure/2-seafloor-data/$function_name.zip" "$site_pkg_dir"
    echo "Zipping contents of: $site_pkg_dir"
    cd $site_pkg_dir
    zip -r9 "$parent_dir/infrastructure/2-seafloor-data/lambda_${function_name}.zip" .
    cd $path_cwd
  else
    echo "site-packages directory not found; skipping zipping dependencies."
  fi
else
  echo "requirements.txt not found; no dependencies to zip."
fi

# Add the lambda function code to the deployment package in the terraform directory
# zip -g "$parent_dir/infrastructure/2-seafloor-data/$function_name.zip" "$path_cwd/lambda_functions/$function_name/$function_name.py"
target_dir="$path_cwd/lambda_functions/$function_name"
if [ -d "$target_dir" ]; then
  # zip -r9 "$parent_dir/infrastructure/2-seafloor-data/lambda_${function_name}.zip" "$target_dir"
  echo "Zipping contents of: $target_dir"
  cd $target_dir
  zip -r9 "$parent_dir/infrastructure/2-seafloor-data/lambda_${function_name}.zip" .
  cd $path_cwd
else
  echo "Directory $target_dir does not exist. Please check your path."
fi

# Removing virtual environment folder...
echo "Removing virtual environment folder..."
rm -rf $path_cwd/env_$function_name

echo "Finished script execution!"