import serial, time, re, sys

MAIN  = "/dev/cu.usbmodem1133101"   # MainCPU v80
DISP  = "/dev/cu.usbmodem1133201"   # DisplayCPU v62
BAUD  = 115200

def openp(port):
    s = serial.Serial(port, BAUD, timeout=0.35)
    time.sleep(0.2)
    s.reset_input_buffer(); s.reset_output_buffer()
    return s

def send(ser, cmd, pause=0.18):
    ser.write(cmd); ser.flush(); time.sleep(pause)

def quick_read(ser, secs=1.5, echo=False):
    t0=time.time(); lines=[]
    while time.time()-t0<secs:
        ln=ser.readline()
        if ln:
            lines.append(ln)
            if echo:
                try: sys.stdout.write(ln.decode('utf-8','ignore'))
                except: pass
    sys.stdout.flush()
    return b"".join(lines)

# 1) Start accel on Main CPU (GUI->Stream Accel->100)
try:
    m = openp(MAIN)
    # optional: API mode for cleaner text
    for c in (b"u\r", b"t\r", b"q\r"): send(m,c,0.14)
    # GUI path
    for c in (b"g\r", b"g\r", b"o\r", b"100\r"): send(m,c,0.20)
    ack = quick_read(m, 0.8, echo=True)
    # fallback: also try Extended->AnalogIn->s->100
    for c in (b"e\r", b"a\r", b"s\r", b"100\r"): send(m,c,0.20)
    ack += quick_read(m, 0.8, echo=True)
    m.close()
    print("\n[MainCPU] attempted to start accel streams.")
except Exception as e:
    print(f"[MainCPU] open/start failed: {e}")

# 2) Start accel on Display CPU (Sensor Functions, try starters)
started=False
try:
    d = openp(DISP)
    # back out to main menu just in case
    for _ in range(3): send(d, b"q\r")
    # enter Sensor Functions
    send(d, b"r\r"); send(d, b"h\r")
    for starter in (b"s\r", b"a\r", b"o\r", b"i\r"):
        for c in (b"r\r", starter, b"100\r"):
            send(d, c)
        buf = quick_read(d, 1.2, echo=True)
        if re.search(rb'[-+]?\d+(\.\d+)?[,\s]+[-+]?\d+(\.\d+)?[,\s]+[-+]?\d+(\.\d+)?', buf) or \
           re.search(rb'"\s*a[x|y|z]"\s*:\s*[-+]?\d', buf) or \
           re.search(rb'Accel\s*\(2g\)', buf, re.I):
            started=True
            break
    print("\n[DisplayCPU] attempted to start sensor accel stream.")
    # 3) Read a bit more to verify
    print("\n--- 3s sniff on DisplayCPU ---")
    sniff = quick_read(d, 3.0, echo=True)
    d.close()
except Exception as e:
    print(f"[DisplayCPU] open/start failed: {e}")

print("\nDone.")