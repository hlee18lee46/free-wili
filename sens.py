import serial, time, sys, re, string
PORT="/dev/cu.usbmodem1133201"  # Display CPU
BAUD=115200

triplet = re.compile(rb'[-+]?\d+(\.\d+)?[,\s]+[-+]?\d+(\.\d+)?[,\s]+[-+]?\d+(\.\d+)?')
accelln = re.compile(rb'Accel\s*\(2g\)', re.I)
buttonln= re.compile(rb'\[\*button\b')

def send(ser, s, p=0.18): ser.write(s); ser.flush(); time.sleep(p)
def sniff(ser, secs=1.2):
    t=time.time(); buf=b""
    while time.time()-t<secs:
        ln=ser.readline()
        if ln:
            buf+=ln
            try: sys.stdout.write(ln.decode('utf-8','ignore'))
            except: pass
    sys.stdout.flush()
    return buf

with serial.Serial(PORT, BAUD, timeout=0.35) as ser:
    time.sleep(0.2)
    ser.reset_input_buffer(); ser.reset_output_buffer()

    # back out to Display main menu
    for _ in range(4): send(ser,b"q\r",0.15)

    # enter Sensor Functions
    send(ser,b"r\r"); send(ser,b"h\r")
    sniff(ser,0.8)

    winners=[]
    for ch in string.ascii_lowercase.encode():
        # re-enter Sensor menu each loop to reset state
        send(ser,b"r\r",0.12)
        send(ser,bytes([ch])+b"\r",0.20)  # try this starter
        send(ser,b"100\r",0.20)           # if it asks for period, this satisfies it
        buf = sniff(ser,1.5)
        if buttonln.search(buf):
            continue  # that's the GUI buttons stream; skip
        if triplet.search(buf) or accelln.search(buf):
            winners.append(chr(ch))
            break

    if winners:
        print(f"\n[FOUND] Sensor accel likely started by letter: {winners[0]!r}")
    else:
        print("\n[NO SENSOR STREAM FOUND] on Display CPU menu via brute force.")