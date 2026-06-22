#!/bin/bash
set -e
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
echo "Done!"
