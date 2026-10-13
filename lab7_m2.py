#!/usr/bin/env python3
"""ECE 437 Lab 7 Milestone 2: Instrument noise floor and I2C bus characterization.

Implements:
  - 2a: Keysight 34461A DMM NPLC integration-time sweep and log-log noise plot.
  - 2b: Keysight MSO-X 3024T oscilloscope ground-loop FFT (spring vs long-wire).
  - 2c: I2C ACK edge acquisition with PMOD marker trigger, 10-90% rise & fall time.
"""
import argparse
import csv
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

DESIGN_ID = 0xEC437001
DEFAULT_NPLC_LIST = (0.02, 0.2, 1.0, 10.0, 100.0)


# ============================================================================
# SCPI Instrument Drivers
# ============================================================================
class ScpiInstrument:
    def __init__(self, resource_name, timeout_ms=10000):
        try:
            import pyvisa
        except ImportError as exc:
            raise RuntimeError("Install PyVISA before running instrument scripts") from exc
        self.manager = pyvisa.ResourceManager()
        self.inst = self.manager.open_resource(resource_name)
        self.inst.timeout = timeout_ms
        self.inst.write_termination = "\n"
        self.inst.read_termination = "\n"

    def close(self):
        try:
            self.inst.close()
        finally:
            self.manager.close()

    def error_check(self, context=""):
        try:
            resp = self.inst.query("SYST:ERR?").strip()
            code = int(resp.split(",", 1)[0].strip())
            if code != 0:
                print(f"WARNING: SCPI error {resp} after {context}", file=sys.stderr)
            return code, resp
        except Exception as exc:
            print(f"WARNING: SYST:ERR? query failed: {exc}", file=sys.stderr)
            return -1, str(exc)

    def write(self, cmd):
        self.inst.write(cmd)
        self.error_check(cmd)

    def query(self, cmd):
        res = self.inst.query(cmd).strip()
        self.error_check(cmd)
        return res


class Dmm34461A(ScpiInstrument):
    """Driver for Keysight 34461A 6.5 digit Truevolt DMM."""

    def __init__(self, resource_name):
        super().__init__(resource_name, timeout_ms=30000)
        idn = self.query("*IDN?")
        if "34461A" not in idn:
            print(f"Notice: Connected DMM identity is: {idn}")

    def acquire_nplc_block(self, nplc, count=200):
        """Acquires a block of DC voltage readings at the specified NPLC setting.

        Uses the DMM internal memory buffer so all samples are acquired at
        native hardware ADC speed without individual USB query latency.
        """
        # Set timeout dynamically: 100 NPLC = 1.67 s per reading
        per_sample_s = max(0.005, (nplc / 60.0) * 1.2)
        expected_s = per_sample_s * count + 5.0
        self.inst.timeout = int(expected_s * 1000)

        self.inst.write("ABOR")
        self.inst.write("CONF:VOLT:DC")
        self.inst.write(f"VOLT:DC:NPLC {nplc}")
        self.inst.write(f"SAMP:COUN {count}")
        self.inst.write("TRIG:SOUR IMM")
        self.inst.write("TRIG:DEL 0")
        self.error_check("Configuring DMM for block capture")

        print(f"DMM acquiring {count} samples at NPLC={nplc} (est. {expected_s:.1f} s)...", flush=True)
        raw = self.inst.query("READ?").strip()
        self.error_check("READ? block fetch")

        readings = [float(x.strip()) for x in raw.split(",") if x.strip()]
        if len(readings) != count:
            print(f"Notice: expected {count} readings, got {len(readings)}", file=sys.stderr)
        return readings


class Scope3024T(ScpiInstrument):
    """Driver for Keysight InfiniiVision MSO-X 3024T Oscilloscope."""

    def __init__(self, resource_name):
        super().__init__(resource_name, timeout_ms=10000)
        idn = self.query("*IDN?")
        print(f"Connected Scope: {idn}")

    def acquire_waveform(self, channel="CHAN1"):
        """Fetches the current on-screen waveform from the specified channel.

        Returns time array (seconds) and voltage array (volts) converted
        via the official waveform preamble parameters.
        """
        self.inst.write(f":WAV:SOUR {channel}")
        self.inst.write(":WAV:FORM BYTE")
        self.inst.write(":WAV:POIN:MODE NORMAL")
        self.error_check("Waveform setup")

        preamble_str = self.inst.query(":WAV:PRE?").strip()
        self.error_check("Waveform preamble query")
        pre = [float(x) for x in preamble_str.split(",")]
        # Preamble format:
        # format(0), type(1), points(2), count(3), xincrement(4), xorigin(5),
        # xreference(6), yincrement(7), yorigin(8), yreference(9)
        num_points = int(pre[2])
        x_inc = pre[4]
        x_orig = pre[5]
        y_inc = pre[7]
        y_orig = pre[8]
        y_ref = pre[9]

        raw_bytes = self.inst.query_binary_values(
            ":WAV:DATA?", datatype="B", container=np.array
        )
        self.error_check("Waveform data query")

        times = np.arange(len(raw_bytes)) * x_inc + x_orig
        volts = (raw_bytes - y_ref) * y_inc + y_orig
        return times, volts


# ============================================================================
# Analysis Routines
# ============================================================================
def compute_rise_fall_times(times, volts, v_low=None, v_high=None):
    """Computes 10%-90% rise and fall times via linear interpolation."""
    if v_low is None:
        v_low = float(np.percentile(volts, 5))
    if v_high is None:
        v_high = float(np.percentile(volts, 95))

    v10 = v_low + 0.10 * (v_high - v_low)
    v90 = v_low + 0.90 * (v_high - v_low)

    rise_time_s = None
    fall_time_s = None
    t10_rise, t90_rise = None, None
    t90_fall, t10_fall = None, None

    # Detect rising edge: where signal crosses v10 upward, then v90 upward
    for i in range(len(volts) - 1):
        if volts[i] <= v10 < volts[i + 1]:
            t10 = times[i] + (v10 - volts[i]) * (times[i + 1] - times[i]) / (volts[i + 1] - volts[i])
            for j in range(i + 1, len(volts) - 1):
                if volts[j] <= v90 < volts[j + 1]:
                    t90 = times[j] + (v90 - volts[j]) * (times[j + 1] - times[j]) / (volts[j + 1] - volts[j])
                    rise_time_s = t90 - t10
                    t10_rise, t90_rise = t10, t90
                    break
            if rise_time_s is not None:
                break

    # Detect falling edge: where signal crosses v90 downward, then v10 downward
    for i in range(len(volts) - 1):
        if volts[i] >= v90 > volts[i + 1]:
            t90 = times[i] + (v90 - volts[i]) * (times[i + 1] - times[i]) / (volts[i + 1] - volts[i])
            for j in range(i + 1, len(volts) - 1):
                if volts[j] >= v10 > volts[j + 1]:
                    t10 = times[j] + (v10 - volts[j]) * (times[j + 1] - times[j]) / (volts[j + 1] - volts[j])
                    fall_time_s = t10 - t90
                    t90_fall, t10_fall = t90, t10
                    break
            if fall_time_s is not None:
                break

    return rise_time_s, fall_time_s, v10, v90, (t10_rise, t90_rise, t90_fall, t10_fall)


# ============================================================================
# Main Milestone 2 Workflows
# ============================================================================
def run_part_2a(dmm_resource, outdir, nplc_list=DEFAULT_NPLC_LIST, count=200):
    """2a: Multimeter Integration Time (NPLC) Sweep."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    print("\n" + "=" * 60)
    print("MILESTONE 2a: Multimeter Integration Time (NPLC) Sweep")
    print("=" * 60)

    part_dir = outdir / "part_2a"
    part_dir.mkdir(parents=True, exist_ok=True)

    dmm = Dmm34461A(dmm_resource)
    results = []

    try:
        for nplc in nplc_list:
            readings = dmm.acquire_nplc_block(nplc, count=count)
            std = float(np.std(readings, ddof=1))
            mean = float(np.mean(readings))
            print(f"NPLC = {nplc:6.2f} | Mean = {mean:+.6f} V | Std Dev = {std * 1e6:8.2f} uV")
            results.append({"nplc": nplc, "mean_v": mean, "std_v": std, "count": len(readings)})

        # Save summary CSV
        csv_path = part_dir / "milestone2a_nplc.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=("nplc", "mean_v", "std_v", "count"))
            writer.writeheader()
            writer.writerows(results)
        print(f"Saved NPLC summary data to {csv_path}")

        # Plot log-log NPLC vs Std Dev
        nplcs = [r["nplc"] for r in results]
        stds = [r["std_v"] for r in results]

        fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
        ax.loglog(nplcs, stds, "o-", color="tab:blue", lw=2, markersize=8, label="Measured Standard Deviation")
        ax.set_xlabel("Integration Time (NPLC)", fontsize=11)
        ax.set_ylabel("Standard Deviation of DC Voltage (V)", fontsize=11)
        ax.set_title("Milestone 2a: 34461A Multimeter Noise Floor vs NPLC", fontsize=12)
        ax.grid(True, which="both", ls="--", alpha=0.6)
        ax.legend()

        plot_path = part_dir / "milestone2a_nplc.png"
        fig.savefig(plot_path, dpi=160)
        plt.close(fig)
        print(f"Saved NPLC plot to {plot_path}")

    finally:
        dmm.close()


def run_part_2b(scope_resource, outdir):
    """2b: Ground Loop FFT Analysis (Spring vs Long Loop)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    print("\n" + "=" * 60)
    print("MILESTONE 2b: Ground Loop FFT Analysis")
    print("=" * 60)

    part_dir = outdir / "part_2b"
    part_dir.mkdir(parents=True, exist_ok=True)

    scope = Scope3024T(scope_resource)
    try:
        # Configure scope for 60 Hz pickup: 20 ms/div = 200 ms span (12 cycles of 60 Hz), 10 mV/div, AC coupling
        scope.write(":CHAN1:DISP ON")
        scope.write(":TIM:SCAL 0.020")
        scope.write(":CHAN1:SCAL 0.010")
        scope.write(":CHAN1:COUP AC")
        time.sleep(0.5)

        input("\n[STEP 1] Attach the PROBE GROUND SPRING (minimal loop). Press Enter when ready...")
        times_spring, volts_spring = scope.acquire_waveform("CHAN1")
        print(f"Captured spring waveform: {len(volts_spring)} points, span = {(times_spring[-1]-times_spring[0])*1000:.2f} ms")

        input("\n[STEP 2] Attach the LONG WIRE GROUND LEAD to the supply GND. Press Enter when ready...")
        times_loop, volts_loop = scope.acquire_waveform("CHAN1")
        print(f"Captured loop waveform: {len(volts_loop)} points, span = {(times_loop[-1]-times_loop[0])*1000:.2f} ms")

        # Compute FFTs (removing DC offset)
        dt_s = times_spring[1] - times_spring[0]
        n_s = len(volts_spring)
        freqs_s = np.fft.rfftfreq(n_s, d=dt_s)
        fft_s = np.abs(np.fft.rfft(volts_spring - np.mean(volts_spring))) * 2.0 / n_s

        dt_l = times_loop[1] - times_loop[0]
        n_l = len(volts_loop)
        freqs_l = np.fft.rfftfreq(n_l, d=dt_l)
        fft_l = np.abs(np.fft.rfft(volts_loop - np.mean(volts_loop))) * 2.0 / n_l

        # Find 60 Hz amplitude
        idx60_s = np.argmin(np.abs(freqs_s - 60.0))
        idx60_l = np.argmin(np.abs(freqs_l - 60.0))
        amp60_s = fft_s[idx60_s]
        amp60_l = fft_l[idx60_l]

        print(f"60 Hz peak (Ground Spring): {amp60_s * 1000:.3f} mV")
        print(f"60 Hz peak (Large Loop)   : {amp60_l * 1000:.3f} mV")
        ratio = amp60_l / max(amp60_s, 1e-9)
        print(f"Ratio (Loop / Spring)     : {ratio:.1f}x")

        # Save summary CSV
        with (part_dir / "milestone2b_fft_summary.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(("configuration", "freq_hz", "amplitude_v", "amplitude_mv"))
            writer.writerow(("ground_spring", f"{freqs_s[idx60_s]:.1f}", f"{amp60_s:.6e}", f"{amp60_s*1000:.4f}"))
            writer.writerow(("long_wire_loop", f"{freqs_l[idx60_l]:.1f}", f"{amp60_l:.6e}", f"{amp60_l*1000:.4f}"))
            writer.writerow(("ratio_loop_to_spring", "-", "-", f"{ratio:.2f}"))

        # Plot comparison on a single common axes
        fig, ax = plt.subplots(figsize=(9, 5.5), constrained_layout=True)
        max_f = 500  # Display up to 500 Hz

        m_s = freqs_s <= max_f
        m_l = freqs_l <= max_f
        ax.plot(freqs_s[m_s], fft_s[m_s] * 1000, color="tab:blue", lw=1.6,
                label=f"Short Ground Spring (60 Hz: {amp60_s*1000:.2f} mV)")
        ax.plot(freqs_l[m_l], fft_l[m_l] * 1000, color="tab:red", lw=1.6,
                label=f"Long Wire Loop (60 Hz: {amp60_l*1000:.2f} mV, {ratio:.1f}x)")
        ax.set_xlabel("Frequency (Hz)", fontsize=11)
        ax.set_ylabel("Amplitude (mV)", fontsize=11)
        ax.set_title("Milestone 2b: Ground Loop FFT Comparison (Common Axes)", fontsize=12)
        ax.grid(True, alpha=0.6)
        ax.legend(loc="upper right")

        plot_path = part_dir / "milestone2b_fft.png"
        fig.savefig(plot_path, dpi=160)
        plt.close(fig)
        print(f"Saved FFT comparison plot to {plot_path}")

    finally:
        scope.close()


def run_part_2c(scope_resource, outdir):
    """2c: I2C Bus Acknowledgment Edge Capture and Rise/Fall Time."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from sensor_board import SensorBoard

    print("\n" + "=" * 60)
    print("MILESTONE 2c: I2C SDA Acknowledgment Edge Capture")
    print("=" * 60)

    part_dir = outdir / "part_2c"
    part_dir.mkdir(parents=True, exist_ok=True)

    scope = Scope3024T(scope_resource)
    try:
        print("\nConfiguring oscilloscope channels and trigger...")
        # Setup Channel 1 and Channel 2
        scope.write(":CHAN1:DISP ON")
        scope.write(":CHAN1:COUP DC")
        scope.write(":CHAN1:SCAL 1.0")
        scope.write(":CHAN1:OFFS 0.0")

        scope.write(":CHAN2:DISP ON")
        scope.write(":CHAN2:COUP DC")
        scope.write(":CHAN2:SCAL 1.0")
        scope.write(":CHAN2:OFFS 0.0")

        # Timebase: 2.0 us/div (20 us span), delay 7.0 us to show trigger, marker, and ACK edge
        scope.write(":TIM:SCAL 2.0e-6")
        scope.write(":TIM:POS 7.0e-6")

        # Trigger on Channel 1 (PMOD Marker) rising edge
        scope.write(":TRIG:MODE EDGE")
        scope.write(":TRIG:EDGE:SOUR CHAN1")
        scope.write(":TRIG:EDGE:SLOP POS")
        scope.write(":TRIG:EDGE:LEV 1.5")
        scope.write(":TRIG:SWE NORM")

        # Arm single sweep
        scope.write(":SINGle")
        time.sleep(0.3)

        print("Triggering I2C transaction on FPGA (ADT7420 ID register read)...")
        with SensorBoard() as sb:
            # Trigger ADT7420 register read: param1=0x90, param2=0x0B, param3=1
            sb.run(param1=0x90, param2=0x0000000B, param3=1, timeout=1.0)
            time.sleep(0.3)

        print("Acquiring waveforms from Scope...")
        times1, volts1 = scope.acquire_waveform("CHAN1")
        times2, volts2 = scope.acquire_waveform("CHAN2")

        # Determine which channel is Marker and which is SDA:
        # Marker starts near 0V, pulses to ~3.3V, and returns to ~0V at the end
        if np.min(volts1) < 0.2 and volts1[-1] < 1.0 and np.max(volts1) > 2.0:
            times_mkr, volts_mkr = times1, volts1
            times_sda, volts_sda = times2, volts2
            mkr_label = "Ch 1: PMOD_A1 Marker"
            sda_label = "Ch 2: I2C SDA_0"
        else:
            times_sda, volts_sda = times1, volts1
            times_mkr, volts_mkr = times2, volts2
            sda_label = "Ch 1: I2C SDA_0"
            mkr_label = "Ch 2: PMOD_A1 Marker"

        # Locate the ACK edge: it begins right when the Marker drops at the end of the ACK cycle
        idx_high = np.where(volts_mkr > 2.0)[0]
        if len(idx_high) > 0:
            t_mkr_end = times_mkr[idx_high[-1]]
            m_pulse = (times_sda >= t_mkr_end - 0.5e-6) & (times_sda <= t_mkr_end + 3.5e-6)
        else:
            t_us = (times_sda - times_sda[0]) * 1e6
            m_pulse = (t_us >= 10.0) & (t_us <= 18.0)

        t_p = times_sda[m_pulse]
        v_p = volts_sda[m_pulse]

        if len(v_p) > 20 and (np.max(v_p) - np.min(v_p) > 0.4):
            idx_peak = np.argmax(v_p)
            v_low = float(np.percentile(v_p[:max(5, int(len(v_p)*0.15))], 50))
            v_high = float(v_p[idx_peak])
            v10 = v_low + 0.10 * (v_high - v_low)
            v90 = v_low + 0.90 * (v_high - v_low)

            # Rising edge before peak:
            r_10_arr = np.where(v_p[:idx_peak] <= v10)[0]
            r_90_arr = np.where(v_p[:idx_peak] >= v90)[0]
            if len(r_10_arr) > 0 and len(r_90_arr) > 0:
                r_10 = r_10_arr[-1]
                r_90 = r_90_arr[0]
                t10_r = np.interp(v10, [v_p[r_10], v_p[r_10+1]], [t_p[r_10], t_p[r_10+1]])
                t90_r = np.interp(v90, [v_p[r_90-1], v_p[r_90]], [t_p[r_90-1], t_p[r_90]])
                rise_s = float(t90_r - t10_r)
            else:
                rise_s = float("nan")

            # Falling edge after peak:
            f_90_arr = np.where(v_p[idx_peak:] <= v90)[0]
            f_10_arr = np.where(v_p[idx_peak:] <= v10)[0]
            if len(f_90_arr) > 0 and len(f_10_arr) > 0:
                f_90 = idx_peak + f_90_arr[0]
                f_10 = idx_peak + f_10_arr[0]
                t90_f = np.interp(v90, [v_p[f_90], v_p[f_90-1]], [t_p[f_90], t_p[f_90-1]])
                t10_f = np.interp(v10, [v_p[f_10], v_p[f_10-1]], [t_p[f_10], t_p[f_10-1]])
                fall_s = float(t10_f - t90_f)
            else:
                fall_s = float("nan")
        else:
            rise_s, fall_s, v10, v90, _ = compute_rise_fall_times(times_sda, volts_sda)

        rise_ns = rise_s * 1e9 if rise_s is not None else float("nan")
        fall_ns = fall_s * 1e9 if fall_s is not None else float("nan")

        # Bus time constant tau and capacitance
        # t_rise = tau * ln(9) = tau * 2.1972
        # tau = R_pullup * C_bus, R_pullup = 10 kOhm
        r_pullup = 10000.0  # 10 kOhms (schematic R4-R7)
        if not np.isnan(rise_s) and rise_s > 0:
            tau_s = rise_s / np.log(9.0)
            c_bus_pf = (tau_s / r_pullup) * 1e12
        else:
            tau_s = float("nan")
            c_bus_pf = float("nan")

        print(f"\nResults:")
        print(f"  10-90% Rise Time : {rise_ns:.2f} ns")
        print(f"  90-10% Fall Time : {fall_ns:.2f} ns")
        print(f"  Ratio Rise/Fall  : {rise_ns / max(fall_ns, 1e-3):.1f}x")
        print(f"  V_10% Level      : {v10:.3f} V")
        print(f"  V_90% Level      : {v90:.3f} V")
        print(f"  Estimated tau    : {tau_s * 1e9:.2f} ns")
        print(f"  Bus Capacitance  : {c_bus_pf:.2f} pF (assuming R_pullup = 10 kOhm)")

        # Save summary text
        summary_path = part_dir / "milestone2c_edge_summary.txt"
        with summary_path.open("w", encoding="utf-8") as f:
            f.write(f"Milestone 2c: I2C SDA Acknowledgment Edge Analysis\n")
            f.write(f"================================================\n")
            f.write(f"10-90% Rise Time  : {rise_ns:.2f} ns\n")
            f.write(f"90-10% Fall Time  : {fall_ns:.2f} ns\n")
            f.write(f"Ratio (Rise/Fall) : {rise_ns / max(fall_ns, 1e-3):.1f}x\n")
            f.write(f"V_10% Threshold   : {v10:.3f} V\n")
            f.write(f"V_90% Threshold   : {v90:.3f} V\n")
            f.write(f"Time Constant tau : {tau_s * 1e9:.2f} ns\n")
            f.write(f"Bus Capacitance   : {c_bus_pf:.2f} pF\n")
            f.write(f"Pull-up Resistor  : 10 kOhm (schematic R4-R7)\n")
        print(f"Saved summary to {summary_path}")

        # Save waveform CSV
        csv_path = part_dir / "milestone2c_sda_waveform.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(("time_s", "sda_voltage_v", "marker_voltage_v"))
            writer.writerows(zip(times_sda, volts_sda, volts_mkr))
        print(f"Saved waveform data to {csv_path}")

        # Plot waveform on a single axes (one plot with both data sets)
        t_plot_us = (times_sda - times_sda[0]) * 1e6
        fig, ax = plt.subplots(figsize=(9.5, 5.5), constrained_layout=True)

        ax.plot(t_plot_us, volts_sda, color="tab:blue", lw=2, label=sda_label)
        ax.plot(t_plot_us, volts_mkr, color="tab:orange", lw=1.8, ls="--", label=mkr_label)
        ax.axhline(v10, color="gray", ls=":", alpha=0.7, label=f"10% Level ({v10:.2f} V)")
        ax.axhline(v90, color="gray", ls="-.", alpha=0.7, label=f"90% Level ({v90:.2f} V)")
        ax.set_xlabel("Time (µs)", fontsize=11)
        ax.set_ylabel("Voltage (V)", fontsize=11)
        ax.set_title(f"Milestone 2c: I2C Acknowledgment Edge & PMOD Marker\n"
                     f"Rise (10-90%): {rise_ns:.1f} ns | Fall (90-10%): {fall_ns:.1f} ns | "
                     f"τ: {tau_s*1e9:.1f} ns | C_bus: {c_bus_pf:.1f} pF", fontsize=12)
        ax.grid(True, alpha=0.6)
        ax.legend(loc="upper right")

        plot_path = part_dir / "milestone2c_sda_edge.png"
        fig.savefig(plot_path, dpi=160)
        plt.close(fig)
        print(f"Saved SDA edge plot to {plot_path}")

    finally:
        scope.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", choices=("2a", "2b", "2c", "all"), default="all")
    parser.add_argument("--dmm-resource", default="USB0::0x0957::0x1A07::MY53208035::INSTR",
                        help="VISA resource string for 34461A DMM")
    parser.add_argument("--scope-resource", default="",
                        help="VISA resource string for MSO-X 3024T Scope")
    parser.add_argument("--nplc-count", type=int, default=200,
                        help="Sample count per NPLC setting (default 200)")
    parser.add_argument("--fast", action="store_true",
                        help="Fast demo mode (fewer samples at 100 NPLC for speed)")
    parser.add_argument("--output-dir", default="milestone2_data")
    parser.add_argument("--list-resources", action="store_true")
    args = parser.parse_args()

    if args.list_resources:
        import pyvisa
        rm = pyvisa.ResourceManager()
        print("Available VISA resources:")
        for r in rm.list_resources():
            print(" ", r)
        rm.close()
        return 0

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    nplc_list = (0.02, 0.2, 1.0, 10.0, 50.0 if args.fast else 100.0)

    if args.part in ("2a", "all"):
        run_part_2a(args.dmm_resource, outdir, nplc_list=nplc_list, count=args.nplc_count)

    if args.part in ("2b", "2c", "all"):
        if not args.scope_resource:
            import pyvisa
            rm = pyvisa.ResourceManager()
            candidates = [r for r in rm.list_resources() if "USB" in r and r != args.dmm_resource]
            rm.close()
            if candidates:
                args.scope_resource = candidates[0]
                print(f"Auto-detected scope candidate: {args.scope_resource}")
            else:
                if args.part != "all":
                    parser.error("--scope-resource is required for oscilloscope measurements (part 2b/2c)")
                else:
                    print("Notice: No scope detected on USB yet. Skipping parts 2b and 2c for now.")
                    return 0

    if args.part in ("2b", "all"):
        run_part_2b(args.scope_resource, outdir)

    if args.part in ("2c", "all"):
        run_part_2c(args.scope_resource, outdir)


if __name__ == "__main__":
    main()

