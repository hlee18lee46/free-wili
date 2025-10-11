#!/usr/bin/env python3
import argparse, csv, json, sys, time, math
from datetime import datetime
from typing import Optional, Tuple

try:
    import serial
    from serial.tools import list_ports
except Exception as e:
    print("pyserial not installed? Try: pip install pyserial")
    raise

try:
    from rich import print as rprint
except Exception:
    def rprint(*a, **k): print(*a, **k)

def list_serial_ports():
    ports = list(list_ports.comports())
    return [p.device for p in ports]

def parse_csv_line(line: str) -> Optional[Tuple[float, float, float]]:
    # Expect: ax,ay,az
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 3:
        return None
    try:
        ax, ay, az = map(float, parts)
        return ax, ay, az
    except ValueError:
        return None

def parse_json_line(line: str) -> Optional[Tuple[float, float, float]]:
    try:
        obj = json.loads(line)
        # common keys: ax, ay, az (fallbacks included)
        for keys in (("ax","ay","az"),("x","y","z")):
            if all(k in obj for k in keys):
                return float(obj[keys[0]]), float(obj[keys[1]]), float(obj[keys[2]])
        return None
    except json.JSONDecodeError:
        return None

def magnitude(ax: float, ay: float, az: float) -> float:
    return math.sqrt(ax*ax + ay*ay + az*az)

def moving_avg(old: Optional[float], new: float, alpha: float) -> float:
    if old is None: return new
    return alpha*new + (1.0 - alpha)*old

def main():
    ap = argparse.ArgumentParser(description="Read Free-WILi accelerometer over serial, log CSV, and alert on motion.")
    ap.add_argument("--port", "-p", help="Serial port (e.g., /dev/tty.usbmodemXXXX). If omitted, auto-pick if only one is found.")
    ap.add_argument("--baud", "-b", type=int, default=115200, help="Baud rate (default: 115200)")
    ap.add_argument("--format", "-f", choices=["auto","csv","json"], default="auto", help="Input line format (default: auto)")
    ap.add_argument("--out", "-o", default="accel_log.csv", help="CSV output file")
    ap.add_argument("--units", choices=["g","ms2"], default="ms2", help="Incoming units: g or m/s^2 (default: ms2)")
    ap.add_argument("--g-to-ms2", type=float, default=9.80665, help="Conversion factor g→m/s^2 (default: 9.80665)")
    ap.add_argument("--alpha", type=float, default=0.2, help="EMA smoothing factor for |a| (0..1, default 0.2)")
    ap.add_argument("--alert-threshold", type=float, default=15.0, help="Trigger alert if |a| (m/s^2) exceeds this (default 15.0)")
    ap.add_argument("--print-raw", action="store_true", help="Also print raw lines for debugging")
    args = ap.parse_args()

    # Pick port
    port = args.port
    if not port:
        ports = list_serial_ports()
        if not ports:
            rprint("[red]No serial ports found. Plug in your device and try again.[/red]")
            sys.exit(1)
        if len(ports) > 1:
            rprint("[yellow]Multiple ports found. Specify one with --port. Candidates:[/yellow]")
            for p in ports:
                rprint("  ", p)
            sys.exit(1)
        port = ports[0]
        rprint(f"[green]Auto-selected port:[/green] {port}")

    # Open serial
    # Open serial
    try:
        ser = serial.Serial(port, args.baud, timeout=1)
    except Exception as e:
        rprint(f"[red]Failed to open {port}: {e}[/red]")
        sys.exit(1)

    # ---- wake/handshake (ADD THIS) ----
    try:
        ser.reset_input_buffer(); ser.reset_output_buffer()
        # Some boards start streaming only after DTR/RTS or a command
        ser.dtr = False; ser.rts = False; time.sleep(0.1)
        ser.dtr = True;  ser.rts = True;  time.sleep(0.1)
        # Try a few likely start commands
        for msg in [b"\r\n", b"start\r\n", b"START\r\n", b"a\r\n", b"accel on\r\n", b"stream accel on\r\n", b"?\r\n"]:
            ser.write(msg); time.sleep(0.05)
    except Exception:
        pass
    # -----------------------------------


    # CSV setup
    csv_file = open(args.out, "a", newline="")
    writer = csv.writer(csv_file)
    # Write header if file is empty
    if csv_file.tell() == 0:
        writer.writerow(["timestamp_iso", "ax_ms2", "ay_ms2", "az_ms2", "mag_ms2"])

    rprint(f"[cyan]Reading from {port} @ {args.baud} baud. Logging → {args.out}[/cyan]")
    rprint("[cyan]Press Ctrl+C to stop.[/cyan]")

    # State
    ema_mag = None
    fmt = args.format  # 'csv', 'json', or 'auto'

    def to_ms2(ax, ay, az):
        if args.units == "g":
            c = args.g_to_ms2
            return ax*c, ay*c, az*c
        return ax, ay, az
    last_rx = time.time()
    idle_warned = False
    try:
        while True:
            raw = ser.readline().decode(errors="ignore").strip()
            if not raw:
                continue
            if args.print_raw:
                rprint(f"[dim]{raw}[/dim]")

            parsed = None
            # format handling
            if fmt == "csv":
                parsed = parse_csv_line(raw)
            elif fmt == "json":
                parsed = parse_json_line(raw)
            else:  # auto
                # try JSON first, then CSV
                parsed = parse_json_line(raw)
                if parsed is None:
                    parsed = parse_csv_line(raw)

            if parsed is None:
                # Not a recognized line; skip but show the first few to help debugging
                continue

            ax, ay, az = to_ms2(*parsed)
            mag = magnitude(ax, ay, az)
            ema_mag = moving_avg(ema_mag, mag, args.alpha)

            ts = datetime.utcnow().isoformat()
            writer.writerow([ts, f"{ax:.5f}", f"{ay:.5f}", f"{az:.5f}", f"{mag:.5f}"])
            csv_file.flush()

            # Console status
            rprint(f"[white]{ts}[/white] ax={ax:7.3f} ay={ay:7.3f} az={az:7.3f} | |a|={mag:6.2f}  ema={ema_mag:6.2f}")

            # Simple motion alert
            if mag >= args.alert_threshold:
                rprint(f"[bold red]⚠ Motion alert: |a|={mag:.2f} ≥ {args.alert_threshold:.2f} (m/s²)[/bold red]")
                # On macOS you can uncomment to get a quick voice alert:
                # import os; os.system('say "motion detected"')

    except KeyboardInterrupt:
        rprint("\n[blue]Stopping...[/blue]")
    finally:
        try:
            ser.close()
        except Exception:
            pass
        csv_file.close()

if __name__ == "__main__":
    main()
