FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends linux-image-virtual initramfs-tools live-boot live-boot-initramfs-tools udev btrfs-progs util-linux bubblewrap weston dbus-x11 at-spi2-core python3-gi python3-pyqt6 qt6-wayland gir1.2-gtk-3.0 gir1.2-atspi-2.0 fonts-dejavu-core python3-venv && rm -rf /var/lib/apt/lists/*
COPY runtime /opt/aios/
RUN python3 -m venv /opt/aios/venv && /opt/aios/venv/bin/pip install --no-cache-dir -r /opt/aios/requirements.txt
COPY build/runtime-aios /usr/local/bin/aios
RUN update-initramfs -u -k all && ln -sf /usr/local/bin/aios /sbin/init
