html_path = "flaskui/app.py"
with open(html_path, "r") as f:
    text = f.read()

insert_text = '''
        # --- RASPBERRY PI E-INK PAGER TRIGGER ---
        if label == "HIGH" or label == "MEDIUM":
            try:
                import paho.mqtt.publish as publish
                import json
                payload = json.dumps({
                    "patient": "SMITH, ROBERT", 
                    "bed": "MSICU-A-04", 
                    "risk": f"{prob*100:.1f}%", 
                    "action": "INITIATE CAM-ICU"
                })
                # Publishes to localhost broker
                publish.single("deliriumwatch/pager/doc1", payload, hostname="127.0.0.1")
                print(">>> ALERT DISPATCHED TO RPI E-INK PAGER (doc1) <<<")
            except Exception as e:
                pass # print(f"MQTT Broadcast skipped (ensure Mosquitto broker is running on laptop): {e}")
        # ----------------------------------------
'''

text = text.replace('label = risk_label(prob)', 'label = risk_label(prob)\n' + insert_text)

with open(html_path, "w") as f:
    f.write(text)

