#!/usr/bin/env python3
import re, time, sys
import serial

CANDIDATE_PORTS = [
    "/dev/cu.usbmodem1133101",
    "/dev/cu.usbmodem1133201",
    "/dev/cu.usbserial-FW5601",
]
BAUDS = [115200, 230400, 57600, 9600]

TRIPLET_CSV = re.compile(rb'[-+]?\d+(\.\d+)?[,\s]+[-+]?\d+(\.\d+)?[,\s]+[-+]?\d+(\.\d+)?')
JSON_AX = re.compile(rb'"\s*a[xX]"\s*:\s*[-+]?\d')
JSON_ALL = re.compile(rb'"\s*a[xX]"\s*:\s*[-+]?\d.*"\s*a[yY]"\s*:\s*[-+]?\d.*"\s*a[zZ]"\s*:\s*[-+]?\d')

def send(ser, s, pause=0.2):
    ser.write(s); ser.flush(); time.sleep(pause)

def try_read(ser, seconds=2.0, echo_prefix=""):
    """Read for a bit; return (got, sample_lines)"""
    t0 = time.time()
    lines = []
    got = False
    while time.time()-t0 < seconds:
        line = ser.readline()
        if line:
            lines.append(line)
            sys.stdout.write(echo_prefix + line.decode("utf-8","ignore"))
            if TRIPLET_CSV.search(line) or JSON_ALL.search(line) or JSON_AX.search(line):
                got = True
    sys.stdout.flush()
    return got, lines

def start_gui_stream(ser, period_ms=b"100\r"):
    # Main → Display(g) → GUI(g) → Stream Accel(o) → period
    for cmd in (b"\r\n", b"g\r", b"g\r", b"o\r", period_ms):
        send(ser, cmd)

def start_sensor_stream(ser, period_ms=b"100\r"):
    # Main → Display(g) → Sensor(n) → try (s|a|o) → period
    for starter in (b"s\r", b"a\r", b"o\r"):
        for cmd in (b"\r\n", b"g\r", b"n\r", starter, period_ms):
            send(ser, cmd)
            got,_ = try_read(ser, seconds=1.0)
            if got:
                return True
    return False

def list_and_try_scripts(ser):
    # Main → Run Script(w) → help(h) to list; try common names
    send(ser, b"w\r"); send(ser, b"h\r")
    _, lines = try_read(ser, seconds=1.5)
    text = b"".join(lines)
    # crude guesses for script names
    candidates = []
    for name in [b"imu.lua", b"imu", b"accel.lua", b"accel", b"stream_accel.lua", b"stream_accel"]:
        if name in text:
            candidates.append(name)
    if not candidates:
        # try anyway with likely names
        candidates = [b"imu.lua", b"accel.lua", b"imu", b"accel", b"stream_accel.lua", b"stream_accel"]

    for nm in candidates:
        for cmd in (b"run " + nm + b"\r", b"100\r"):
            send(ser, cmd)
        got,_ = try_read(ser, seconds=2.0)
        if got:
            return True
        # back out
        send(ser, b"q\r")
    # leave Run Script
    send(ser, b"q\r")
    return False

def main():
    for port in CANDIDATE_PORTS:
        for baud in BAUDS:
            print(f"\n=== Trying {port} @ {baud} ===")
            try:
                with serial.Serial(port, baud, timeout=0.3) as ser:
                    time.sleep(0.2)
                    ser.reset_input_buffer(); ser.reset_output_buffer()

                    # Enable UART API (cleaner text/JSON)
                    for cmd in (b"u\r", b"t\r", b"q\r"):
                        send(ser, cmd, 0.15)

                    # Read banner quickly
                    try_read(ser, seconds=0.8, echo_prefix="")

                    # Try GUI stream
                    print("-- GUI→Stream Accel @100ms --")
                    start_gui_stream(ser, b"100\r")
                    ok, lines = try_read(ser, seconds=2.0)
                    if ok:
                        print(f"\n[FOUND STREAM] via GUI on {port} @ {baud}")
                        print("Sample:")
                        for ln in lines[:10]: sys.stdout.write(ln.decode("utf-8","ignore"))
                        return

                    # Try Sensor Functions
                    print("-- Display→Sensor Functions --")
                    if start_sensor_stream(ser, b"100\r"):
                        print(f"\n[FOUND STREAM] via Sensor Functions on {port} @ {baud}")
                        return

                    # Try scripts
                    print("-- Run Script (imu/accel) --")
                    if list_and_try_scripts(ser):
                        print(f"\n[FOUND STREAM] via Script on {port} @ {baud}")
                        return

                    print("[No stream found on this combo]\n")

            except Exception as e:
                print(f"[Open failed] {port} @ {baud}: {e}")
                continue

    print("\n❗ No obvious accel stream found. Try moving the device, or share the last 30–40 lines printed above.")

if __name__ == "__main__":
    main()
