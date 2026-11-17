"""Send data/normal and data/fatigue to the SK-AM62B over the serial console (no network needed).

Usage (on the Mac, with miniterm CLOSED and the board at the root shell):
    python3 send_data_serial.py                     # auto-detects /dev/cu.usbserial-*0
    python3 send_data_serial.py /dev/cu.usbserial-XXXX0

Files land on the board in /root/hackedge/data/normal and /root/hackedge/data/fatigue.
At 115200 baud this takes about 8-10 minutes for ~4.5 MB compressed.
"""
import base64
import glob
import hashlib
import io
import sys
import tarfile
import time
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parent
DEST = '/root/hackedge/data'
REMOTE_B64 = '/tmp/hk_data.b64'


def build_archive():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for folder in ('normal', 'fatigue'):
            for p in sorted((ROOT / 'data' / folder).glob('*.csv')):
                tar.add(p, arcname=f'{folder}/{p.name}')
    return buf.getvalue()


def cmd(s, line, wait=1.0):
    s.reset_input_buffer()
    s.write((line + '\n').encode())
    time.sleep(wait)
    return s.read(s.in_waiting or 1).decode(errors='replace')


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else (sorted(glob.glob('/dev/cu.usbserial-*0')) or [None])[0]
    if not port:
        sys.exit('No board serial port found. Plug in the debug micro-USB cable.')
    data = build_archive()
    md5 = hashlib.md5(data).hexdigest()
    b64 = base64.encodebytes(data).decode().splitlines()       # 76-char lines
    print(f'{port}: sending {len(data)/1e6:.1f} MB as {len(b64)} lines (md5 {md5})')

    with serial.Serial(port, 115200, timeout=1) as s:
        out = cmd(s, '', 1)
        if '#' not in out and '$' not in out:
            print('Warning: no shell prompt seen. Make sure the board is logged in as root.\n', out)
        cmd(s, 'stty -echo')                                   # stop the board echoing the data back
        cmd(s, f'cat > {REMOTE_B64}', 0.5)
        t0 = time.time()
        for i, line in enumerate(b64, 1):
            s.write((line + '\n').encode())
            s.flush()
            if i % 200 == 0:
                s.reset_input_buffer()
                done = i / len(b64)
                eta = (time.time() - t0) / done * (1 - done)
                print(f'\r  {done:6.1%}  ~{eta/60:4.1f} min left', end='', flush=True)
        time.sleep(1)
        s.write(b'\x04')                                       # Ctrl-D ends `cat`
        time.sleep(1)
        print('\nDecoding on the board…')
        out = cmd(s, f'mkdir -p {DEST} && base64 -d {REMOTE_B64} > /tmp/hk_data.tgz && '
                     f'md5sum /tmp/hk_data.tgz && tar xzf /tmp/hk_data.tgz -C {DEST} && ls -l {DEST}/normal {DEST}/fatigue', 5)
        cmd(s, 'stty echo')
        print(out)
        print('OK: checksum matches.' if md5 in out else f'Checksum NOT found in output (expected {md5}). Re-run the script.')


if __name__ == '__main__':
    main()
