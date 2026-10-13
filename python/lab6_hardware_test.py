import os
import time

os.environ['OK_API_PATH'] = 'C:/Program Files/Opal Kelly/FrontPanelUSB/API/Python/x64'
dll_dir = os.add_dll_directory('C:/Program Files/Opal Kelly/FrontPanelUSB/API/lib/x64')

from sensor_board import SensorBoard, parse_bitfile_arg


def transaction(sb, address, pointer, read_count=0, data=0, expect_nack=False):
    mode = {0: 0, 1: 1, 2: 3}[read_count]
    sb.set_params(param1=address << 1,
                  param2=(data << 8) | pointer,
                  param3=mode)
    sb.start()
    # Allow the start pulse to clear the previous transaction's done flag.
    time.sleep(0.002)
    sb.wait_done(timeout=1.0)
    r0, r1, r2 = sb.results()
    st = sb.status()
    ack = r0 & 1
    label = 'READ %d byte(s)' % read_count if read_count else 'WRITE'
    print('%s address=0x%02X ACK=%d error=%d state=%d busy=%d done=%d result1=0x%08X result2=%d'
          % (label, address, ack, st['error'], st['state'],
             st['busy'], st['done'], r1, r2), flush=True)
    if st['state'] != 0 or st['busy'] or not st['done']:
        raise RuntimeError('Transaction did not return to idle: %s' % st)
    if st['error'] != expect_nack or ack != int(expect_nack):
        raise RuntimeError('Unexpected ACK/error: %s, ACK=%d' % (st, ack))
    return r1


with SensorBoard(parse_bitfile_arg()) as sb:
    sb.reset()
    time.sleep(0.01)
    st = sb.status()
    if st['busy'] or st['done'] or st['error'] or st['state'] != 0:
        raise RuntimeError('Reset did not clear the FSM: %s' % st)

    # Configuration register: normal 13-bit temperature operation.
    transaction(sb, 0x48, 0x03, data=0x00)
    transaction(sb, 0x49, 0x03, data=0x00, expect_nack=True)
    transaction(sb, 0x48, 0x03, data=0x00)

    ident = transaction(sb, 0x48, 0x0B, read_count=1)
    if ident != 0xCB:
        raise RuntimeError('Expected ID 0x000000CB, got 0x%08X' % ident)
    print('PASS: one-byte ID read completed and returned to idle', flush=True)

    raw = transaction(sb, 0x48, 0x00, read_count=2)
    if raw & 0xFFFF0000:
        raise RuntimeError('Unexpected upper result bits: 0x%08X' % raw)
    first, second = (raw >> 8) & 0xFF, raw & 0xFF
    signed = raw if raw < 0x8000 else raw - 0x10000
    temperature = (signed >> 3) * 0.0625
    print('Temperature: first=0x%02X second=0x%02X raw=0x%04X -> %.4f C'
          % (first, second, raw, temperature), flush=True)
    print('PASS: two-byte temperature read completed and returned to idle', flush=True)

    ident = transaction(sb, 0x48, 0x0B, read_count=1)
    if ident != 0xCB:
        raise RuntimeError('Repeated ID read failed: 0x%08X' % ident)
    print('PASS: another read completed without resetting', flush=True)
    print('RESULT: ALL PASS (completed read/write hardware checks)', flush=True)
