#!/usr/bin/env python3
"""ECE 437 Lab 7 Milestone 1: ADT7420 sensor floor measurements.

Requires a Keysight/Agilent E3631A programmable DC supply and the Opal Kelly board.
The supply must be connected to the isolated power-resistor board, which is
mated thermally (not electrically) with the sensor board.
"""
import argparse
import csv
import math
import os
import statistics
import sys
import time
from pathlib import Path

DESIGN_ID = 0xEC437001

MAX_RESISTOR_W = 0.5
MIN_RESISTANCE_OHM = 39.9
MAX_SWEEP_V = 4.0
SUPPLY_CURRENT_LIMIT_A = 0.105
SOFTWARE_POWER_TRIP_W = 0.42
SWEEP_LEVELS_V = tuple(MAX_SWEEP_V * math.sqrt(k / 5) for k in range(1, 6))
SETTLE_SAMPLE_PERIOD_S = 1.0
SETTLE_WINDOW_SAMPLES = 60
SETTLE_MINIMUM_S = 120.0
SETTLE_MAX_SLOPE_C_PER_S = 0.0005
SETTLE_RANGE_C = 0.15
SETTLE_TIMEOUT_S = 900.0
FAST_SAMPLE_COUNT = 1000
SLOW_SAMPLE_COUNT = 100
SLOW_SAMPLE_PERIOD_S = 0.300


class ScpiSupply:
    """Small checked SCPI wrapper; every normal command is followed by SYST:ERR?."""

    def __init__(self, resource_name, channel="P25V"):
        self.channel = channel
        try:
            import pyvisa
        except ImportError as exc:
            raise RuntimeError("Install PyVISA with the project's requirements before running this test") from exc
        self.manager = pyvisa.ResourceManager()
        self.instrument = self.manager.open_resource(resource_name)
        self.instrument.timeout = 5000
        self.instrument.write_termination = "\n"
        self.instrument.read_termination = "\n"

    def close(self):
        try:
            self.instrument.close()
        finally:
            self.manager.close()

    def _error_check(self, command):
        response = self.instrument.query("SYST:ERR?").strip()
        try:
            code = int(response.split(",", 1)[0].strip())
        except ValueError as exc:
            raise RuntimeError("Cannot parse supply error response %r after %s" % (response, command)) from exc
        if code != 0:
            raise RuntimeError("Supply reported SCPI error after %s: %s" % (command, response))

    def command(self, command):
        self.instrument.write(command)
        self._error_check(command)

    def query(self, command):
        response = self.instrument.query(command).strip()
        self._error_check(command)
        return response

    def query_float(self, command):
        response = self.query(command)
        try:
            value = float(response)
        except ValueError as exc:
            raise RuntimeError("Supply returned a non-numeric value for %s: %r" % (command, response)) from exc
        if not math.isfinite(value):
            raise RuntimeError("Supply returned a non-finite value for %s: %r" % (command, response))
        return value

    def disable_output(self):
        self.command("OUTP OFF")

    @staticmethod
    def list_resources():
        try:
            import pyvisa
        except ImportError as exc:
            raise RuntimeError("Install PyVISA with the project's requirements before discovering supplies") from exc
        manager = pyvisa.ResourceManager()
        try:
            return manager.list_resources()
        finally:
            manager.close()

    def identify(self):
        identity = self.query("*IDN?")
        if "E3631A" not in identity.upper():
            raise RuntimeError("This SCPI driver is verified for E3631A only: %s" % identity)
        return identity

    def configure(self):
        self.command("OUTP OFF")
        self.command("INST:SEL %s" % self.channel)
        if self.query("INST:SEL?").upper() != self.channel:
            raise RuntimeError("Supply output selection did not verify")
        self.command("VOLT 0")
        self.command("CURR %.3f" % SUPPLY_CURRENT_LIMIT_A)
        actual_limit = self.query_float("CURR?")
        minimum_limit = MAX_SWEEP_V / MIN_RESISTANCE_OHM
        if actual_limit < minimum_limit or actual_limit > SUPPLY_CURRENT_LIMIT_A + 0.001:
            raise RuntimeError("Supply current limit readback %.4f A is outside safe %.4f..%.4f A range" %
                               (actual_limit, minimum_limit, SUPPLY_CURRENT_LIMIT_A + 0.001))
        if self.query_float("VOLT?") > 0.05:
            raise RuntimeError("Supply setpoint readback is not zero before enabling output")
        self.command("OUTP ON")
        if self.query("OUTP?").strip().upper() not in ("1", "ON"):
            raise RuntimeError("Supply did not confirm output enabled")

    def set_voltage(self, voltage):
        if voltage < 0.0 or voltage > MAX_SWEEP_V:
            raise ValueError("Requested supply voltage is outside the 0..4.0 V lab limit")
        self.command("VOLT %.3f" % voltage)

    def readings(self):
        voltage = self.query_float("MEAS:VOLT?")
        current = self.query_float("MEAS:CURR?")
        return voltage, current, abs(voltage * current)


class Dataset:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=(
            "phase", "level_v", "measured_v", "measured_a", "power_w",
            "sample", "timestamp_s", "temperature_c", "fpga_cycles",
        ))
        self.writer.writeheader()
        self.started = time.monotonic()
        self.pending = []

    def add(self, phase, level_v, measured, sample, temperature, cycles):
        voltage, current, power = measured
        self.pending.append({
            "phase": phase,
            "level_v": "" if level_v is None else "%.6f" % level_v,
            "measured_v": "%.6f" % voltage,
            "measured_a": "%.6f" % current,
            "power_w": "%.6f" % power,
            "sample": sample,
            "timestamp_s": "%.6f" % (time.monotonic() - self.started),
            "temperature_c": "%.6f" % temperature,
            "fpga_cycles": cycles,
        })
        if len(self.pending) >= 100:
            self.flush()

    def flush(self):
        if self.pending:
            self.writer.writerows(self.pending)
            self.pending.clear()
            self.file.flush()

    def close(self):
        self.flush()
        self.file.close()


def adt_temperature(sb):
    result0, raw, cycles = sb.run(
        param1=0x90, param2=0x00000000, param3=0x03, timeout=1.0
    )
    status = sb.status()
    if status["error"] or (result0 & 1) or not status["done"] or status["busy"] or status["state"] != 0:
        raise RuntimeError("ADT7420 read failed: status=%s result0=0x%08X" % (status, result0))
    raw16 = raw & 0xFFFF
    signed16 = raw16 if raw16 < 0x8000 else raw16 - 0x10000
    return signed16 / 128.0, cycles


def set_adt_16_bit_mode(sb):
    result0, _, _ = sb.run(param1=0x90, param2=0x00008003, param3=0, timeout=1.0)
    status = sb.status()
    if status["error"] or (result0 & 1) or not status["done"] or status["busy"] or status["state"] != 0:
        raise RuntimeError("Failed to write ADT7420 configuration register: %s" % status)
    result0, raw, _ = sb.run(param1=0x90, param2=0x00000003, param3=1, timeout=1.0)
    status = sb.status()
    if status["error"] or (result0 & 1) or not status["done"] or status["busy"] or status["state"] != 0:
        raise RuntimeError("Failed to read ADT7420 configuration register: %s" % status)
    if raw & 0xFF != 0x80:
        raise RuntimeError("ADT7420 16-bit mode did not verify; config=0x%02X" % (raw & 0xFF))


def check_hardware(sb, supply, expected_id, ambient_reference):
    if sb.design_id() != DESIGN_ID:
        raise RuntimeError("Unexpected FPGA design ID 0x%08X" % sb.design_id())
    identity = supply.identify()
    if expected_id.casefold() not in identity.casefold():
        raise RuntimeError("Supply identity %r did not contain expected reference %r" % (identity, expected_id))
    ident_result, ident, _ = sb.run(param1=0x90, param2=0x0000000B, param3=1, timeout=1.0)
    status = sb.status()
    if status["error"] or (ident_result & 1) or (ident & 0xFF) != 0xCB or not status["done"] or status["busy"]:
        raise RuntimeError("ADT7420 ID reference check failed: raw=0x%08X status=%s" % (ident, status))
    set_adt_16_bit_mode(sb)
    time.sleep(0.300)  # Allow a complete conversion in the new resolution mode.
    temp_c, _ = adt_temperature(sb)
    if abs(temp_c - ambient_reference) > 5.0:
        raise RuntimeError("Known-value temperature check failed: %.3f C vs reference %.3f C" % (temp_c, ambient_reference))
    print("PASS: FPGA ID, supply identity, ADT7420 ID, 16-bit config, and room-temperature reference")
    print("Supply: %s" % identity)
    print("ADT7420 room reference: %.3f C (independent value %.3f C)" % (temp_c, ambient_reference))


def safe_supply_readings(supply, power_limit=SOFTWARE_POWER_TRIP_W):
    voltage, current, power = supply.readings()
    if voltage < -0.05 or voltage > MAX_SWEEP_V + 0.05:
        supply.disable_output()
        raise RuntimeError("Safety shutdown: measured voltage %.4f V exceeds 0..4.0 V limit" % voltage)
    if power > power_limit or power >= MAX_RESISTOR_W:
        supply.disable_output()
        raise RuntimeError("Safety shutdown: measured resistor power %.4f W reached the %.2f W trip" %
                           (power, power_limit))
    if abs(current) > SUPPLY_CURRENT_LIMIT_A * 1.10:
        supply.disable_output()
        raise RuntimeError("Safety shutdown: measured current %.4f A exceeds the configured current limit" % current)
    return voltage, current, power


def wait_for_settling(sb, supply, data, level_v):
    window = []
    started = time.monotonic()
    print("Waiting for thermal settling at %.2f V; max wait %.0f s" % (level_v, SETTLE_TIMEOUT_S), flush=True)
    while time.monotonic() - started < SETTLE_TIMEOUT_S:
        measured = safe_supply_readings(supply)
        temperature, cycles = adt_temperature(sb)
        window.append((time.monotonic() - started, temperature))
        data.add("settle", level_v, measured, len(window), temperature, cycles)
        elapsed = time.monotonic() - started
        if len(window) >= SETTLE_WINDOW_SAMPLES:
            recent = window[-SETTLE_WINDOW_SAMPLES:]
            span = max(t for _, t in recent) - min(t for _, t in recent)
            slope = statistics.linear_regression([t for t, _ in recent], [v for _, v in recent]).slope
        else:
            span = float("nan")
        print("settle %.0f s | V=%.3f V I=%.3f A P=%.3f W T=%.4f C span60=%.4f C" %
              (elapsed, measured[0], measured[1], measured[2], temperature, span), flush=True)
        if (elapsed >= SETTLE_MINIMUM_S and len(window) >= SETTLE_WINDOW_SAMPLES
                and span <= SETTLE_RANGE_C and abs(slope) <= SETTLE_MAX_SLOPE_C_PER_S):
            print("Settled after %.1f s: last %d samples span %.4f C" %
                  (elapsed, SETTLE_WINDOW_SAMPLES, span), flush=True)
            return elapsed
        time.sleep(SETTLE_SAMPLE_PERIOD_S)
    supply.disable_output()
    raise TimeoutError("Temperature did not settle at %.2f V within %.0f s; output switched off" %
                       (level_v, SETTLE_TIMEOUT_S))


def collect_fast(sb, supply, data, phase, level_v, count):
    temperatures = []
    t0 = time.monotonic()
    safety_interval = count + 1 if phase == "averaging_fast_1000" else 1
    measured = safe_supply_readings(supply)
    for sample in range(count):
        if sample and sample % safety_interval == 0:
            measured = safe_supply_readings(supply)
        temperature, cycles = adt_temperature(sb)
        temperatures.append(temperature)
        data.add(phase, level_v, measured, sample + 1, temperature, cycles)
        if phase != "averaging_fast_1000" and (sample == 0 or (sample + 1) % 100 == 0):
            print("%s %d/%d | V=%.3f V I=%.3f A P=%.3f W T=%.4f C" %
                  (phase, sample + 1, count, measured[0], measured[1], measured[2], temperature), flush=True)
    elapsed = time.monotonic() - t0
    safe_supply_readings(supply)
    return temperatures, elapsed


def collect_slow(sb, supply, data, level_v):
    temperatures = []
    t0 = time.monotonic()
    for sample in range(SLOW_SAMPLE_COUNT):
        due = t0 + sample * SLOW_SAMPLE_PERIOD_S
        delay = due - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        temperature, cycles = adt_temperature(sb)
        measured = safe_supply_readings(supply)
        if time.monotonic() >= due + SLOW_SAMPLE_PERIOD_S:
            raise RuntimeError("Supply/USB loop cannot sustain 300 ms cadence; adjust instrument transport")
        temperatures.append(temperature)
        data.add("averaging_slow_300ms", level_v, measured, sample + 1, temperature, cycles)
        if sample == 0 or (sample + 1) % 10 == 0:
            print("averaging_slow_300ms %d/%d | V=%.3f V I=%.3f A P=%.3f W T=%.4f C" %
                  (sample + 1, SLOW_SAMPLE_COUNT, measured[0], measured[1], measured[2], temperature), flush=True)
    return temperatures


def averaging_statistics(values):
    max_n = min(256, len(values) // 2)
    ns = []
    observed = []
    expected = []
    sigma1 = statistics.stdev(values)
    n = 1
    while n <= max_n:
        means = [statistics.mean(values[i:i + n]) for i in range(0, len(values) - n + 1, n)]
        if len(means) >= 2:
            ns.append(n)
            observed.append(statistics.stdev(means))
            expected.append(sigma1 / math.sqrt(n))
        n *= 2
    return sigma1, ns, observed, expected


def write_analysis(outdir, sweep_rows, fast_temperatures, fast_elapsed, slow_temperatures, breakpoint_n):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("Install matplotlib before analysis/plot generation") from exc

    levels = [row["level_v"] for row in sweep_rows]
    means = [row["mean_c"] for row in sweep_rows]
    sigmas = [row["std_c"] for row in sweep_rows]
    powers = [row["power_w"] for row in sweep_rows]
    fig, axes = plt.subplots(2, 1, figsize=(8, 8), constrained_layout=True)
    axes[0].plot(powers, means, "o-")
    axes[0].set(xlabel="Measured resistor power (W)", ylabel="ADT7420 mean temperature (C)", title="Milestone 1a: temperature vs applied power")
    axes[0].grid(True)
    axes[1].plot(means, sigmas, "o-")
    axes[1].set(xlabel="Mean temperature (C)", ylabel="Temperature standard deviation (C)", title="Milestone 1a: sensor spread vs mean")
    axes[1].grid(True)
    fig.savefig(outdir / "milestone1_sweep.png", dpi=160)
    plt.close(fig)

    sigma1, ns, observed, expected = averaging_statistics(fast_temperatures)
    fig, axis = plt.subplots(figsize=(8, 6), constrained_layout=True)
    axis.loglog(ns, observed, "o-", label="Measured std. dev. of block means")
    axis.loglog(ns, expected, "--", label=r"$\sigma_1/\sqrt{N}$ reference")
    if breakpoint_n and breakpoint_n in ns:
        axis.axvline(breakpoint_n, color="red", linestyle=":", label="Recorded departure N=%d" % breakpoint_n)
    axis.set(xlabel="Averaging count N", ylabel="Standard deviation of average (C)", title="Milestone 1b: averaging law")
    axis.grid(True, which="both")
    axis.legend()
    fig.savefig(outdir / "milestone1_averaging.png", dpi=160)
    plt.close(fig)

    with (outdir / "milestone1_averaging_analysis.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("N", "observed_std_of_means_C", "sigma_single_sample_over_sqrtN_C"))
        writer.writerows(zip(ns, observed, expected))

    with (outdir / "milestone1_summary.txt").open("w", encoding="utf-8") as stream:
        stream.write("Fast 1000-reading wall time: %.6f s\n" % fast_elapsed)
        stream.write("Fast single-reading standard deviation: %.8f C\n" % sigma1)
        stream.write("Recorded averaging-law departure N: %s\n" % (breakpoint_n if breakpoint_n else "not supplied"))
        stream.write("Slow 100-reading standard deviation (300 ms interval): %.8f C\n" % statistics.stdev(slow_temperatures))
        fast100 = statistics.stdev(fast_temperatures[0:100])
        slow100 = statistics.stdev(slow_temperatures)
        stream.write("Fast first-100 standard deviation: %.8f C\n" % fast100)
        stream.write("Slow/fast standard-deviation ratio: %s\n" % (slow100 / fast100 if fast100 else "undefined: fast spread is zero"))
        stream.write("16-bit LSB: 0.0078125 C; nominal conversion time: 0.240 s\n")
        if sigma1 == 0:
            stream.write("WARNING: fast readings are identical; no averaging departure can be inferred. Repeat acquisition.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visa-resource", help="PyVISA resource string for the programmable supply")
    parser.add_argument("--supply-id-contains", help="Expected substring from the supply's *IDN? response")
    parser.add_argument("--ambient-reference-c", type=float, help="Independent room-temperature reading in C for the sensor reference check")
    parser.add_argument("--list-resources", action="store_true", help="list VISA resource names, without configuring the board or supply")
    parser.add_argument("--resistor-confirmed", action="store_true", help="Confirm resistor is 42 ohm +/-5%%, rated 0.5 W, and wired per Lab 7")
    parser.add_argument("--output-dir", default="lab7_milestone1_data")
    parser.add_argument("--breakpoint-n", type=int, default=0, help="N observed to leave the sqrt(N) trend after inspecting the generated plot")
    parser.add_argument("--supply-channel", choices=("P6V", "P25V"), default="P25V")
    parser.add_argument("--demo-cutoff", action="store_true", help="Demonstrate real shutdown at 2 V using a temporary 0.05 W threshold")
    args = parser.parse_args()
    if args.list_resources:
        print("\n".join(ScpiSupply.list_resources()))
        return 0
    if not args.visa_resource or not args.supply_id_contains or args.ambient_reference_c is None:
        parser.error("--visa-resource, --supply-id-contains, and --ambient-reference-c are required for data capture")
    if not args.resistor_confirmed:
        parser.error("do not run until you verify resistor value/rating and supply wiring; then pass --resistor-confirmed")
    if not 5.0 <= args.ambient_reference_c <= 45.0:
        parser.error("ambient reference must be a plausible room-temperature value in C")
    if args.breakpoint_n and args.breakpoint_n not in (1, 2, 4, 8, 16, 32, 64, 128, 256):
        parser.error("--breakpoint-n must be one of 1,2,4,8,16,32,64,128,256")

    from sensor_board import SensorBoard

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    data = Dataset(outdir / "milestone1_samples.csv")
    supply = ScpiSupply(args.visa_resource, args.supply_channel)
    try:
        supply.disable_output()
        with SensorBoard() as sb:
            print("Board %s, serial %s, design ID 0x%08X" % (sb.model, sb.serial, sb.design_id()), flush=True)
            sb.reset()
            time.sleep(0.01)
            if sb.status()["busy"] or sb.status()["state"] != 0:
                raise RuntimeError("FPGA reset failed: %s" % sb.status())
            check_hardware(sb, supply, args.supply_id_contains, args.ambient_reference_c)

            print("Safety limits: V<=%.2f V, current limit=%.3f A, software power trip=%.2f W" %
                  (MAX_SWEEP_V, SUPPLY_CURRENT_LIMIT_A, SOFTWARE_POWER_TRIP_W), flush=True)
            worst_case_power = MAX_SWEEP_V ** 2 / MIN_RESISTANCE_OHM
            if worst_case_power >= MAX_RESISTOR_W:
                raise RuntimeError("Configured voltage would exceed the resistor's worst-case rated power")
            print("Worst-case resistor power at sweep maximum: %.3f W (rating %.2f W)" %
                (worst_case_power, MAX_RESISTOR_W), flush=True)
            print("WARNING: resistor becomes hot; do not touch it or the resistor board during or after heating.", flush=True)
            confirmation = input("Verify resistor wiring and TA-approved 0.105 A limit; type READY to continue: ")
            if confirmation.strip() != "READY":
                raise RuntimeError("Hardware safety confirmation not provided; supply output remains off")
            supply.configure()

            supply.set_voltage(1.0)
            time.sleep(0.5)
            reference_v, reference_i, _ = safe_supply_readings(supply)
            if abs(reference_v - 1.0) > 0.05 or not 0.018 <= reference_i <= 0.030:
                raise RuntimeError("Known-load check failed: expected 1 V and about 24 mA; got %.4f V, %.4f A" % (reference_v, reference_i))
            print("PASS: selected-channel known-load check: %.4f V, %.4f A" % (reference_v, reference_i))
            supply.set_voltage(0.0)
            if args.demo_cutoff:
                supply.set_voltage(2.0)
                time.sleep(0.5)
                try:
                    safe_supply_readings(supply, power_limit=0.05)
                except RuntimeError as exc:
                    if "measured resistor power" not in str(exc):
                        raise
                    if supply.query("OUTP?").upper() not in ("0", "OFF"):
                        raise RuntimeError("Cutoff fired but output OFF did not verify")
                    print("PASS: real measured-power cutoff: %s; output OFF verified" % exc)
                    return 0
                raise RuntimeError("Cutoff demo did not trigger; check the heater wiring")

            sweep_rows = []
            for level in SWEEP_LEVELS_V:
                supply.set_voltage(level)
                safe_supply_readings(supply)
                settled_after = wait_for_settling(sb, supply, data, level)
                temperatures, _ = collect_fast(sb, supply, data, "sweep_100", level, 100)
                measured = safe_supply_readings(supply)
                row = {
                    "level_v": level,
                    "power_w": measured[2],
                    "mean_c": statistics.mean(temperatures),
                    "std_c": statistics.stdev(temperatures),
                    "settle_s": settled_after,
                }
                sweep_rows.append(row)
                print("Sweep %.2f V: P=%.4f W mean=%.4f C std=%.6f C settled=%.1f s" %
                      (level, row["power_w"], row["mean_c"], row["std_c"], settled_after), flush=True)
            with (outdir / "milestone1_sweep_summary.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=("level_v", "power_w", "mean_c", "std_c", "settle_s"))
                writer.writeheader()
                writer.writerows(sweep_rows)

            supply.set_voltage(0.0)
            safe_supply_readings(supply)
            wait_for_settling(sb, supply, data, 0.0)
            supply.disable_output()  # Heater off for both fast and slow noise experiments.
            fast_values, fast_elapsed = collect_fast(sb, supply, data, "averaging_fast_1000", 0.0, FAST_SAMPLE_COUNT)
            slow_values = collect_slow(sb, supply, data, 0.0)
            print("Averaging experiment: %d fast readings in %.3f s; then %d readings every %.0f ms" %
                  (len(fast_values), fast_elapsed, len(slow_values), SLOW_SAMPLE_PERIOD_S * 1000), flush=True)
            write_analysis(outdir, sweep_rows, fast_values, fast_elapsed, slow_values, 0)
            supply.disable_output()
            breakpoint_n = args.breakpoint_n
            if not breakpoint_n:
                valid_breakpoints = (1, 2, 4, 8, 16, 32, 64, 128, 256)
                while True:
                    answer = input("Inspect milestone1_averaging.png and enter the N where the data leaves the sqrt(N) line: ").strip()
                    try:
                        breakpoint_n = int(answer)
                    except ValueError:
                        breakpoint_n = 0
                    if breakpoint_n in valid_breakpoints:
                        break
                    print("Enter one of: %s" % ", ".join(str(n) for n in valid_breakpoints), flush=True)
            write_analysis(outdir, sweep_rows, fast_values, fast_elapsed, slow_values, breakpoint_n)
            supply.disable_output()
            print("Output disabled. Data and plots saved to %s" % outdir.resolve(), flush=True)
            print("RESULT: MILESTONE 1 DATA CAPTURE COMPLETE", flush=True)
    except BaseException:
        try:
            supply.disable_output()
        except Exception as shutdown_error:
            print("CRITICAL: failed to switch supply output off: %s" % shutdown_error, file=sys.stderr)
        raise
    finally:
        try:
            supply.disable_output()
        finally:
            data.close()
            supply.close()


if __name__ == "__main__":
    main()
