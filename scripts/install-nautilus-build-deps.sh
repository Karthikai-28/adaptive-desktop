#!/usr/bin/env bash
set -Eeuo pipefail

sudo apt update

sudo apt install -y \
  build-essential \
  meson \
  ninja-build \
  pkg-config \
  git \
  devscripts \
  dpkg-dev \
  desktop-file-utils \
  gvfs \
  gvfs-backends \
  gvfs-fuse \
  tracker \
  tracker-miner-fs

echo
echo "Installing Ubuntu Nautilus package build dependencies..."
sudo apt build-dep -y nautilus

echo
echo "Build dependencies installed."
