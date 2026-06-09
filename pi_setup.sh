#!/bin/bash
# Raspberry Pi DeliriumWatch Pager Deployment Script

echo "=== 1. INSTALLING DEPENDENCIES ==="
sudo apt-get update
sudo apt-get install -y python3-pip python3-pil python3-numpy git python3-spidev python3-rpi.gpio
pip3 install paho-mqtt spidev waveshare-epd --break-system-packages

echo "=== 2. TESTING WAVESHARE E-INK DISPLAY ==="
if [ ! -d "e-Paper" ]; then
    git clone https://github.com/waveshareteam/e-Paper.git
fi
cd e-Paper/RaspberryPi_JetsonNano/python/examples || exit
echo "Running E-Ink Test (Should display Waveshare logo/text)..."
python3 epd_2in13_V4_test.py
cd ../../../..

echo "=== 3. CONFIGURING DELIRIUM PAGER SERVICE ==="
cat << 'SRV' | sudo tee /etc/systemd/system/delirium-pager.service
[Unit]
Description=DeliriumWatch MQTT e-Ink Pager
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/rpi_pager.py
WorkingDirectory=/home/pi
StandardOutput=inherit
StandardError=inherit
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
SRV

sudo systemctl daemon-reload
sudo systemctl enable delirium-pager.service
sudo systemctl restart delirium-pager.service

echo "=== DEPLOYMENT COMPLETE ==="
echo "Check service status with: sudo systemctl status delirium-pager.service"
