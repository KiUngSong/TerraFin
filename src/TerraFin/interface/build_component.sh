#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define colors for output
GREEN='\\033[0;32m'
RED='\\033[0;31m'
YELLOW='\\033[0;33m'
CYAN='\\033[0;36m'
NC='\\033[0m'

# Define log prefixes
ERROR="${RED}[ERROR]${NC} "
INFO="${CYAN}[INFO]${NC} "
WARNING="${YELLOW}[WARNING]${NC} "

# Get the directory of this script
SCRIPT_DIR=$(dirname "$0")
COMPONENT_DIR="${SCRIPT_DIR}/frontend"

echo -e "${INFO}Building TerraFin frontend bundle..."
cd "$COMPONENT_DIR"

# Install dependencies if node_modules doesn't exist
if [ ! -d "node_modules" ]; then
    echo -e "${INFO}Installing dependencies..."
    npm install
fi

# Build the component
echo -e "${INFO}Building React component..."
npm run build

echo -e "${GREEN}[BUILD SUCCESS]${NC} TerraFin frontend bundle built successfully!"
echo -e "${INFO}Built files are in: $COMPONENT_DIR/build"

# Return to the original directory
cd - > /dev/null
