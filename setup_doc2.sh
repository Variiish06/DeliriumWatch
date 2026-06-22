#!/bin/bash
set -e

echo "Installing apt dependencies..."
echo "toor" | sudo -S apt-get update
echo "toor" | sudo -S apt-get install -y python3-pil python3-numpy python3-pip python3-spidev python3-rpi.gpio git

echo "Installing paho-mqtt..."
pip3 install paho-mqtt --break-system-packages || pip3 install paho-mqtt

echo "Cloning e-Paper repository..."
if [ ! -d "/home/pi/e-Paper" ]; then
    git clone https://github.com/waveshare/e-Paper.git /home/pi/e-Paper
fi

echo "Creating systemd service..."
cat << 'EOF' > /home/pi/delirium-pager.service
[Unit]
Description=DeliriumWatch Clinical IoT Pager (doc2 / Bay B)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/rpi_pager.py
WorkingDirectory=/home/pi
StandardOutput=journal
StandardError=journal
Restart=always
RestartSec=5
User=root
Environment=PYTHONUNBUFFERED=1
Environment="PAGER_ID=doc2"
Environment="PAGER_ZONE=Bay B"
Environment="MQTT_BROKER=10.92.9.50"

[Install]
WantedBy=multi-user.target
EOF

echo "toor" | sudo -S mv /home/pi/delirium-pager.service /etc/systemd/system/delirium-pager.service
echo "toor" | sudo -S systemctl daemon-reload
echo "toor" | sudo -S systemctl enable delirium-pager.service
echo "toor" | sudo -S systemctl restart delirium-pager.service
echo "Setup complete!"
