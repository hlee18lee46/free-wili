python -m serial.tools.miniterm /dev/cu.usbmodem1133101 115200 --raw

python -m serial.tools.miniterm /dev/cu.usbmodem1133101 115200 --raw

/dev/cu.usbmodem1133201

Main Menu

o) GPIO Functions
s) SPI Functions
r) Radio Functions
i) I2C Functions
u) UART Functions
e) Extended Functions
g) Display Functions
w) Run Script
m) Load FPGA From File
d) Download FPGA
x) Files
z) Settings


Enter Letter:

g

Display Functions
====================
i) IR Functions
s) System Functions
a) Audio Functions
g) GUI Functions
n) Sensor Functions
====================
h) Help
d) Reset To Defaults
z) Fuzzzzzzz


Enter Letter: (q to exit) 

[g\n 0E18CB1751B79D70 3554  1]


GUI Functions
====================
o) Stream Accel
====================
h) Help
d) Reset To Defaults
z) Fuzzzzzzz


Enter Letter: (q to exit) 

o






Building Rust & run WASM app

cd accel_wasm
wasm-pack build --release --target web -d web/pkg

python app.py --port 7001 --web-root web