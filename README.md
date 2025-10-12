How to Run python app that streams of accelerometer data using pyserial. 

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
python app.py
Go to localhost:7001

How to Run Google Gemini 2.5 Computer Use (gemini-2.5-computer-use-preview-10-2025), this handles tasks with UI such as clicking button.

stay at root
python main.py

This one is the main Gemini 2.5 Computer Use python file that automates the configuration of clicking connect button and configure the port to connect to the Free-WILi, this type of automation would help blind people as well.

To reduce token usage, we made another python file for Gemini 2.5 Computer Use.

Stay at root
python tiny.py

This one is the reduced version of Gemini 2.5 Computer Use python file that automates the configuration of clicking connect button and configure the port to connect to the Free-WILi, this type of automation would help blind people as well.

However, configure your Google Studio key in environmental variable that is paid-tier. Free-tier has 0 quota on "gemini-2.5-computer-use-preview-10-2025".


To provide alternative, we used playwrite to automate clicking "Connect button". But, still this leaves us to manually to configuration of which port to choose for the theft detection system. Only clicking "Connect button" was automated with this file.

stay at root
python auto_connect.py



