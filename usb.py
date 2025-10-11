import serial, time, re
PORT="/dev/cu.usbserial-FW5601"     # UART
ser=serial.Serial(PORT,115200,timeout=0.2)
t=time.time()
while time.time()-t<10:
    ln=ser.readline()
    if ln: print(ln.decode('utf-8','ignore').rstrip())
ser.close()