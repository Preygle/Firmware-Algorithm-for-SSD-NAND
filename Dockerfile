# Use an older Ubuntu release to get Python 2 and an older GCC
FROM ubuntu:18.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install all the legacy gem5 dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    m4 \
    scons \
    zlib1g \
    zlib1g-dev \
    libprotobuf-dev \
    protobuf-compiler \
    libprotoc-dev \
    libgoogle-perftools-dev \
    python \
    python-dev \
    && rm -rf /var/lib/apt/lists/*

# Set the default working directory
WORKDIR /workspace