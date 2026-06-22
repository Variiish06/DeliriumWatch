#!/usr/bin/env python3
"""
ClinicalOS IoT Pager — Raspberry Pi Service
Display: Waveshare 2.13" e-Paper HAT V4  (250 × 122 px, B/W)
"""
import sys, os, time, json, signal, logging, subprocess, threading

EPAPER_LIB = "/home/pi/e-Paper/RaspberryPi_JetsonNano/python/lib"
if os.path.exists(EPAPER_LIB):
    sys.path.append(EPAPER_LIB)

import paho.mqtt.client as mqtt
from PIL import Image, ImageDraw, ImageFont
from waveshare_epd import epd2in13_V4 as epd_driver

# ─── CONFIG ──────────────────────────────────────────────────────
PAGER_ID    = os.environ.get("PAGER_ID",    "doc1")
PAGER_ZONE  = os.environ.get("PAGER_ZONE",  "Bay A")
MQTT_BROKER = os.environ.get("MQTT_BROKER", "10.92.9.50")
MQTT_PORT   = int(os.environ.get("MQTT_PORT", "1883"))
CLEAR_AFTER = 300          # seconds before auto-clear

TOPIC_DIRECT    = f"deliriumwatch/pager/{PAGER_ID}/alerts"
TOPIC_ZONE_GRP  = f"deliriumwatch/zone/{PAGER_ZONE}/alerts"
TOPIC_BROADCAST = "deliriumwatch/pager/broadcast"
TOPIC_CLEAR     = f"deliriumwatch/pager/{PAGER_ID}/clear"
TOPIC_STATUS    = f"deliriumwatch/pager/{PAGER_ID}/status"
TOPIC_RSSI      = f"deliriumwatch/pager/{PAGER_ID}/rssi"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pager")

# ─── DISPLAY SETUP ───────────────────────────────────────────────
W, H = 250, 122
epd = None

def init_display():
    global epd, W, H
    try:
        epd = epd_driver.EPD()
        epd.init()
        epd.Clear(0xFF)
        W, H = epd.height, epd.width
        log.info(f"Display ready: {W}×{H}")
    except Exception as e:
        log.warning(f"Display init failed (headless mode): {e}")
        epd = None

def render_full(img):
    if epd:
        try: epd.display(epd.getbuffer(img))
        except Exception as e: log.error(f"render_full: {e}")

def render_partial(img):
    if epd:
        try: epd.displayPartial(epd.getbuffer(img))
        except Exception:
            try: render_full(img)
            except: pass

def flash_screen(img):
    """Rapidly invert display B/W to grab attention."""
    if not epd: return
    img_inv = img.point(lambda p: 255 - p)
    for _ in range(3):
        render_partial(img_inv)
        time.sleep(0.3)
        render_partial(img)
        time.sleep(0.3)

# ─── FONT LOADING ─────────────────────────────────────────────────
def load_fonts():
    bases = [
        "/usr/share/fonts/truetype/dejavu/",
        "/usr/share/fonts/truetype/freefont/",
        "/usr/share/fonts/truetype/liberation/",
    ]
    bold_path = reg_path = None
    for b in bases:
        if os.path.exists(b + "DejaVuSans-Bold.ttf"):
            bold_path = b + "DejaVuSans-Bold.ttf"; reg_path = b + "DejaVuSans.ttf"; break
        if os.path.exists(b + "FreeSansBold.ttf"):
            bold_path = b + "FreeSansBold.ttf"; reg_path = b + "FreeSans.ttf"; break
    try:
        return {
            "b22": ImageFont.truetype(bold_path, 22),
            "b16": ImageFont.truetype(bold_path, 16),
            "b13": ImageFont.truetype(bold_path, 13),
            "b11": ImageFont.truetype(bold_path, 11),
            "r11": ImageFont.truetype(reg_path,  11),
            "r9":  ImageFont.truetype(reg_path,   9),
        }
    except Exception:
        d = ImageFont.load_default()
        return {k: d for k in ["b22","b16","b13","b11","r11","r9"]}

F = load_fonts()

# ─── RSSI HELPERS ────────────────────────────────────────────────
def get_wifi_rssi() -> int:
    try:
        res = subprocess.run(["iwconfig","wlan0"], capture_output=True, text=True, timeout=3)
        for line in res.stdout.split("\n"):
            if "Signal level" in line:
                return int(line.split("Signal level=")[1].split(" ")[0])
    except Exception: pass
    return -100

def rssi_bars(rssi: int) -> int:
    if rssi > -50: return 4
    if rssi > -65: return 3
    if rssi > -80: return 2
    if rssi > -90: return 1
    return 0

def draw_signal_bars(draw: ImageDraw.Draw, x: int, y: int, rssi: int, fill_color: int = 0):
    bars = rssi_bars(rssi)
    heights = [4, 7, 11, 16]
    widths  = [3, 3, 3, 3]
    gap = 2
    for i, (h, w) in enumerate(zip(heights, widths)):
        bx = x + i * (w + gap)
        by = y - h
        color = fill_color if i < bars else 200
        draw.rectangle([bx, by, bx + w - 1, y], fill=color)

# ─── SCREENS ─────────────────────────────────────────────────────
def _truncate(text: str, font, max_px: int) -> str:
    while text and font.getlength(text) > max_px:
        text = text[:-1]
    return text

def make_standby_screen(rssi: int = -100) -> Image.Image:
    img  = Image.new("1", (W, H), 255)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, W-1, H-1], outline=0, width=2)
    draw.rectangle([2, 2, W-3, 20], fill=0)
    draw.text((6, 4),     "CLINICAL PAGER", font=F["r9"],  fill=255)
    draw.text((W-55, 4),  time.strftime("%H:%M"), font=F["r9"], fill=255)

    rssi_str = f"{rssi} dBm"
    draw.text((W-120, 4), rssi_str, font=F["r9"], fill=255)
    draw_signal_bars(draw, W-48, 18, rssi, fill_color=255)

    cy = H // 2 - 8
    draw.text((W//2 - 50, cy - 16), "PAGER ACTIVE", font=F["b16"], fill=0, anchor="la")
    msg = "Waiting for alerts..."
    draw.text((6, cy + 8), msg, font=F["r11"], fill=0)

    draw.rectangle([2, H-18, W-3, H-3], outline=0)
    footer = f"ID: {PAGER_ID}   Zone: {PAGER_ZONE}"
    draw.text((6, H-16), footer, font=F["r9"], fill=0)
    return img

def make_alert_screen(patient: str, bed: str, label: str,
                       risk: str, action: str,
                       timestamp: str, rssi: int = -100) -> Image.Image:
    is_crit = label == "HIGH"
    bg  = 0   if is_crit else 255
    fg  = 255 if is_crit else 0
    ibg = 255 if is_crit else 0
    ifg = 0   if is_crit else 255

    img  = Image.new("1", (W, H), bg)
    draw = ImageDraw.Draw(img)

    bw = 4 if is_crit else 2
    draw.rectangle([0, 0, W-1, H-1], outline=fg, width=bw)

    # HEADER
    draw.rectangle([2, 2, W-3, 19], fill=ibg)
    pri_text = f"!! CRITICAL !!" if is_crit else f"! WARNING !"
    draw.text((5, 4), pri_text, font=F["b11"], fill=ifg)
    draw.text((W-52, 4), timestamp, font=F["r9"], fill=ifg)
    draw_signal_bars(draw, W-120, 18, rssi, fill_color=ifg)

    # PATIENT
    pt_trunc = _truncate(patient, F["b16"], W - 12)
    draw.text((5, 25), pt_trunc, font=F["b16"], fill=fg)

    # BED AND RISK
    draw.text((5, 48), f"BED: {bed}", font=F["b13"], fill=fg)
    draw.text((W//2, 48), f"RISK: {risk}", font=F["b13"], fill=fg)

    # ACTION
    act_trunc = _truncate(action, F["b16"], W - 12)
    draw.text((5, 75), act_trunc, font=F["b16"], fill=fg)

    return img

# ─── STATE ───────────────────────────────────────────────────────
alert_lock       = threading.Lock()
current_alert    = None
last_alert_time  = 0.0
current_rssi     = -100

# ─── MQTT CALLBACKS ──────────────────────────────────────────────
def on_connect(client, userdata, flags, rc, props):
    log.info(f"MQTT connected rc={rc}")
    for t in [TOPIC_DIRECT, TOPIC_ZONE_GRP, TOPIC_BROADCAST, TOPIC_CLEAR]:
        client.subscribe(t)
        log.info(f"  subscribed: {t}")

def on_message(client, userdata, msg):
    global current_alert, last_alert_time
    topic   = msg.topic
    payload = msg.payload.decode()
    log.info(f"MSG [{topic}]: {payload[:80]}")

    if topic == TOPIC_CLEAR:
        with alert_lock: current_alert = None
        if epd:
            epd.init()
            render_full(make_standby_screen(current_rssi))
        return

    try:
        data = json.loads(payload)
        with alert_lock:
            current_alert   = data
            last_alert_time = time.time()
    except Exception as e:
        log.error(f"JSON parse error: {e}")

# ─── HEARTBEAT ───────────────────────────────────────────────────
def heartbeat_loop(client: mqtt.Client):
    global current_rssi
    while True:
        try:
            rssi = get_wifi_rssi()
            current_rssi = rssi
            client.publish(TOPIC_STATUS, json.dumps({
                "id": PAGER_ID, "zone": PAGER_ZONE, "status": "online"
            }))
            client.publish(TOPIC_RSSI, json.dumps({
                "id": PAGER_ID, "rssi": rssi
            }))
            log.debug(f"Heartbeat RSSI={rssi}")
        except Exception as e:
            log.warning(f"Heartbeat error: {e}")
        time.sleep(10)

# ─── MAIN ────────────────────────────────────────────────────────
def main():
    global current_alert, last_alert_time

    init_display()
    if epd:
        standby = make_standby_screen(current_rssi)
        render_full(standby)
        try: epd.displayPartBaseImage(epd.getbuffer(standby))
        except: pass

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    while True:
        try: client.connect(MQTT_BROKER, MQTT_PORT, 60); break
        except Exception as e: log.warning(f"MQTT connect failed: {e}"); time.sleep(5)

    client.loop_start()
    threading.Thread(target=heartbeat_loop, args=(client,), daemon=True).start()

    log.info(f"Pager {PAGER_ID} live — zone {PAGER_ZONE}")

    last_rendered   = None
    showing_standby = True

    def graceful_exit(*_):
        log.info("Shutting down...")
        client.loop_stop()
        if epd:
            epd.init()
            epd.Clear(0xFF)
            epd.sleep()
        sys.exit(0)

    signal.signal(signal.SIGTERM, graceful_exit)
    signal.signal(signal.SIGINT,  graceful_exit)

    try:
        while True:
            with alert_lock:
                alert_snap = current_alert

            if alert_snap and alert_snap != last_rendered:
                showing_standby = False
                if epd:
                    img = make_alert_screen(
                        alert_snap.get("patient",    "UNKNOWN"),
                        alert_snap.get("bed",        "N/A"),
                        alert_snap.get("label",      "MEDIUM"),
                        alert_snap.get("risk",       ""),
                        alert_snap.get("action",     ""),
                        alert_snap.get("timestamp",  time.strftime("%H:%M")),
                        rssi=current_rssi,
                    )
                    flash_screen(img)
                    try:
                        render_partial(img)
                    except Exception:
                        epd.init()
                        render_full(img)
                        try: epd.displayPartBaseImage(epd.getbuffer(img))
                        except: pass
                last_rendered = alert_snap

            elif not showing_standby and (time.time() - last_alert_time > CLEAR_AFTER):
                with alert_lock: current_alert = None
                last_rendered = None
                if epd:
                    epd.init()
                    render_full(make_standby_screen(current_rssi))
                showing_standby = True
                log.info("Alert auto-cleared — back to standby")

            elif showing_standby:
                if int(time.time()) % 60 == 0 and epd:
                    try: render_partial(make_standby_screen(current_rssi))
                    except: pass

            time.sleep(1)

    except KeyboardInterrupt:
        graceful_exit()

if __name__ == "__main__":
    main()
