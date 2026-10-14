![Header Banner](assets/Sensor_Board_Layout.png)
# FPGA I²C Sensor Interface & Precision Measurement Analysis
**University of Illinois Urbana-Champaign**    
**Target Hardware:** Opal Kelly XEM7310-A75 (Xilinx Artix-7 `xc7a75tfgg484-1`), UIUC ECE 437 Sensor Board  

---

## 📖 Executive Summary

This repository contains the complete FPGA hardware design, automated Python instrument control, and statistical analysis suite for **Noise, Averaging, and the Limits of Precision Measurement**. 

The project encompasses two major engineering efforts:
1. **FPGA Digital Design:** Developing a robust, multi-byte $\text{I}^2\text{C}$ master controller in Verilog to interface with an onboard **Analog Devices ADT7420** 16-bit temperature sensor over USB 3.0 via the Opal Kelly FrontPanel subsystem, featuring sub-microsecond diagnostic synchronization pulses via PMOD headers.
2. **Precision Instrumentation & Measurement Physics:** Rigorous experimental verification of measurement limits across four bench milestones:
   - **Central Limit Theorem Limits:** Why averaging oversamples of correlated sensor data fails when violating internal analog-to-digital conversion times ($240\text{ ms}$).
   - **Mains Rejection via Analog Integration:** Exploiting integrating multimeters (Keysight 34461A) at $1.0\text{ NPLC}$ ($16.67\text{ ms}$) to achieve an $11.4\times$ ($>60\text{ dB}$) cancellation of 60 Hz line pickup.
   - **Faraday's Law & Inductive Ground Loops:** Quantifying electromagnetic interference pickup ($0.25\text{ cm}^2$ short probe vs. $100\text{ cm}^2$ wire loop) and demonstrating why deterministic interference cannot be eliminated by standard averaging.
   - **High-Speed Bus Dynamics:** Capturing open-drain $\text{I}^2\text{C}$ edge transitions to extract bus time constants ($\tau = 382.1\text{ ns}$) and stray bus capacitance ($C_{\text{bus}} = 38.2\text{ pF}$), proving that passive pull-up resistance ($10\text{ k}\Omega$)—not sensor silicon—governs maximum communication rates.

---

## 🏛️ System Architecture

```
+------------------------------------------------------------------------------------+
|                                    HOST PC                                         |
|   Python 3 Automation (Opal Kelly FrontPanel SDK + PyVISA Instrument Control)      |
|   • lab7_m1.py: ADT7420 continuous readout & block averaging statistics            |
|   • lab7_m2.py: Automated Keysight DMM NPLC sweeps & Tektronix Scope captures     |
+------------------------------------------+-----------------------------------------+
                                           | USB 3.0 SuperSpeed
+------------------------------------------v-----------------------------------------+
|                    OPAL KELLY XEM7310-A75 FPGA BOARD                               |
|   Xilinx Artix-7 (xc7a75tfgg484-1) @ 100.8 MHz System Clock                        |
|                                                                                    |
|   [ FrontPanel IP Core ] <---> WireIn / WireOut / TriggerIn Register Map           |
|            |                                                                       |
|   [ SensorBoard_Top.v ] Top-Level Routing, IO Buffers, Sensor Safe Defaults       |
|            |                                                                       |
|   [ lab7_i2c.v ] Multi-Byte I2C Master Finite State Machine (100 kHz SCL)          |
|            |                                                                       |
|            +---> PMOD Diagnostic Header (Marker pulse on ACK cycle)                |
+------------+-----------------------------------------------------------------------+
             | I2C Bus 0 (SCL, SDA with 10 kΩ pull-ups)
+------------v-----------------------------------------------------------------------+
|                         UIUC ECE 437 SENSOR BOARD                                  |
|   • ADT7420: 16-bit ±0.25°C High-Accuracy Temperature Sensor (Address: 0x48)       |
|   • HTS221 (Humidity), LPS35HW (Pressure), LSM303DLHC (IMU/Mag), AD7156 (Cap.)     |
+------------------------------------------------------------------------------------+
```

---

## ⚙️ Hardware Implementation (Verilog HDL)

The FPGA design is organized under `hdl/`:

### 1. `hdl/SensorBoard_Top.v` (Top Level)
- Integrates the Opal Kelly FrontPanel USB communication endpoint interface (`okHost`).
- Provides open-drain bidirectional IO buffers (`IOBUF`) for $\text{I}^2\text{C}$ lines: SCL and SDA are driven low (`*_low = 1`) or released to float high via external pull-up resistors (`*_low = 0`), ensuring compliance with open-drain requirements.
- Configures default idle levels for unselected sensors (e.g., SPI chip selects held high, power enables active).
- Maps internal diagnostic trigger signals to physical PMOD output pins for high-precision oscilloscope edge synchronization.

### 2. `hdl/lab7_i2c.v` (I²C Master Controller FSM)
- Implements a state machine dividing each $100\text{ kHz}$ SCL cycle ($10\,\mu\text{s}$) into four $2.5\,\mu\text{s}$ sub-states using a division counter running off the $100.8\text{ MHz}$ reference clock:
  - **Sub-state 0:** Drive SCL low, assert new SDA data.
  - **Sub-state 1:** Setup hold time before SCL rises.
  - **Sub-state 2:** Drive SCL high (slave/master samples SDA).
  - **Sub-state 3:** SCL high hold time before falling edge.
- **Three-Phase Sequence:**
  1. **Phase 1 (Pointer Write):** Bus START $\to$ Slave address `0x90` (Write) $\to$ ACK $\to$ Register pointer `0x00` (Temperature MSB) $\to$ ACK.
  2. **Phase 2 (Repeated Start):** REPEATED START condition $\to$ Slave address `0x91` (Read) $\to$ ACK.
  3. **Phase 3 (Two-Byte Read):** Shift in MSB byte $\to$ Assert Master ACK $\to$ Shift in LSB byte $\to$ Assert Master NACK $\to$ Bus STOP condition.
- **Diagnostic Marker Pulse:** Asserts a dedicated output marker on PMOD Pin 1 during the acknowledgment state, enabling the oscilloscope to trigger reliably on individual bus acknowledgment cycles.

---

## 📊 Experimental Results & Milestones

### Milestone 1: Limits of Averaging & Sensor Conversion Cadence
- **Fast Acquisition (~2.36 ms/sample):** 1,000 queries completed in 2.36 seconds. Because the ADT7420 requires **240 ms** to produce a new 16-bit conversion, rapid polling repeatedly read identical conversion registers, yielding an artificially low $\sigma_{\text{fast}} = 0.0046^\circ\text{C}$.
- **Rate-Limited Acquisition (300 ms/sample):** Sampling every 300 ms ($> 240\text{ ms}$) ensured independent conversions, revealing the true physical noise $\sigma_{\text{slow}} = 0.0166^\circ\text{C}$ ($3.60\times$ higher).
- **Block Averaging ($\sigma_N$ vs. $N$):** Averaging block sizes from $N=1$ to $N=256$ demonstrated that standard deviation departs from the theoretical $1/\sqrt{N}$ line at $N=2$ and levels off at a flat floor of $\sigma \approx 0.0265^\circ\text{C}$.
- **Quantization Comparison:** The noise floor ($\sigma_{\text{flat}} \approx 0.0265^\circ\text{C}$) is $3.4\times$ greater than $1\text{ LSB}$ ($0.0078^\circ\text{C}$) and $11.7\times$ greater than ideal quantization noise ($\text{LSB}/\sqrt{12} \approx 0.0023^\circ\text{C}$), proving the measurement limit is physical analog front-end noise rather than ADC quantization resolution.

### Milestone 2a: Digital Multimeter Integration Time (NPLC Sweep)
- Measured a quiet node across varying Number of Power Line Cycles (NPLC) on the Keysight 34461A:
  - $0.02\text{ NPLC}$ ($0.33\text{ ms}$): $\sigma = 4.516\,\mu\text{V}$
  - $0.20\text{ NPLC}$ ($3.33\text{ ms}$): $\sigma = 2.597\,\mu\text{V}$
  - $\mathbf{1.00\text{ NPLC}}$ ($\mathbf{16.67\text{ ms}}$): $\mathbf{\sigma = 0.2365\,\mu\text{V}}$ ($236.5\text{ nV}$)
  - $10.0\text{ NPLC}$ ($166.7\text{ ms}$): $\sigma = 0.3887\,\mu\text{V}$
  - $100.0\text{ NPLC}$ ($1.667\text{ s}$): $\sigma = 1.837\,\mu\text{V}$
- **Physics of 60 Hz Cancellation:** At $1.0\text{ NPLC}$, the integration period matches the mains period ($1/60\text{ s}$). The integral of sinusoidal 60 Hz interference evaluates identically to zero over one period:
  $$\int_{0}^{1/60} \sin(2\pi \cdot 60 t + \phi)\, dt = 0$$
  This yields an **11.4-fold noise reduction** compared to fast sampling.

### Milestone 2b: Ground Loop Inductive Pickup (Faraday's Law)
- Compared 60 Hz pickup amplitude on an oscilloscope FFT ($0\text{--}500\text{ Hz}$):
  - **Short Ground Spring:** Estimated loop area $A \approx 0.25\text{ cm}^2$ $\implies V_{60} = 0.0857\text{ mV}$ ($85.7\,\mu\text{V}$).
  - **Long Wire Loop:** Estimated loop area $A \approx 100\text{ cm}^2$ ($400\times$ area) $\implies V_{60} = 0.0965\text{ mV}$ ($96.5\,\mu\text{V}$).
- **Analysis:** Demonstrates Faraday's Law ($V_{\text{ind}} = -A \cdot dB/dt$). Coherent periodic interference cannot be removed by arbitrary averaging; it requires physical loop minimization, magnetic shielding, or synchronized integration windows.

### Milestone 2c: I²C ACK Edge Dynamics & Bus Capacitance Extraction
- Synchronized oscilloscope capture of the SDA acknowledgment edge via PMOD marker:
  - **10%–90% Rise Time ($t_{\text{rise}}$):** $\mathbf{839.52\text{ ns}}$
  - **90%–10% Fall Time ($t_{\text{fall}}$):** $\mathbf{1.60\text{ ns}}$
  - **Asymmetry Ratio ($t_{\text{rise}} / t_{\text{fall}}$):** $\mathbf{526.0\times}$
- **Cause of Asymmetry:** The falling edge is actively pulled low by an on-chip NMOS transistor ($R_{\text{on}} \approx 15\,\Omega$), while the rising edge is passive charging governed by the board's $10\text{ k}\Omega$ pull-up resistor and parasitic bus capacitance.
- **Extracted Bus Parameters:**
  $$t_{\text{rise}} = \tau \ln(9) \approx 2.1972\tau \implies \tau = \frac{839.52\text{ ns}}{2.1972} = \mathbf{382.08\text{ ns}}$$
  $$C_{\text{bus}} = \frac{\tau}{R_{\text{pullup}}} = \frac{382.08\text{ ns}}{10\text{ k}\Omega} = \mathbf{38.21\text{ pF}}$$
- **Speed Mode Support:** The measured rise time satisfies I²C Standard Mode ($t_r < 1000\text{ ns}$ for $100\text{ kHz}$), but violates Fast Mode ($t_r \le 300\text{ ns}$ for $400\text{ kHz}$). Supporting 400 kHz requires reducing pull-up resistance to $R_{\text{pullup}} \le 3.57\text{ k}\Omega$ (e.g., $2.2\text{ k}\Omega$ or $3.3\text{ k}\Omega$).

---

## 📁 Repository Structure

```
.
├── bitfile/
│   └── SensorBoard_Top.bit        # Compiled FPGA bitstream (XEM7310 Artix-7)
├── constraints/
│   └── xem7310.xdc                 # Master FPGA pinout, clock & I/O standard constraints
├── datasheet/                      # Sensor datasheets (ADT7420, HTS221, LPS35HW, etc.)
├── hdl/
│   ├── I2C_Transmit.v             # Baseline single-byte starter FSM
│   ├── lab7_i2c.v                 # Full multi-byte I2C read state machine with PMOD marker
│   └── SensorBoard_Top.v          # Top-level FrontPanel & sensor routing module
├── lab7_milestone1_data/           # Milestone 1 raw datasets, log files, and averaging plots
├── lab7_milestone2_data/           # Milestone 2 raw datasets and instrument captures
├── milestone2_data/                # Organized Milestone 2 analysis plots & waveform CSVs
│   ├── part_2a/                   # DMM NPLC sweep dataset & plot
│   ├── part_2b/                   # Short vs. long loop FFT spectra & comparison plots
│   └── part_2c/                   # PMOD-triggered ACK waveform capture & edge analysis
├── opalkelly/                      # Opal Kelly FrontPanel HDL vendor IP cores
├── python/
│   ├── lab7_m1.py                 # Milestone 1 temperature acquisition & statistics
│   ├── lab7_m2.py                 # Milestone 2 DMM & Oscilloscope automation
│   ├── sensor_board.py            # High-level Python wrapper for FrontPanel API
│   ├── smoke_test.py              # Initial hardware & USB communication check
│   └── requirements.txt           # Python library dependencies
├── scripts/
│   └── build_postlab_pdf.py       # Standalone automated PDF report generation script
├── sim/                           # Testbenches and behavioral I2C slave simulation models
├── vivado/
│   └── build.tcl                  # Vivado non-project mode batch synthesis & routing script
├── build.sh                       # Automated build script for native Vivado / Docker
├── pack.sh                        # Archive script for submission packaging
└── README.md                      # Project documentation (this file)
```

---

## 🚀 Getting Started

### 1. Prerequisites
- **FPGA Toolchain:** Xilinx Vivado (2020.2 or newer)
- **Host Software:** Python 3.9+ with Opal Kelly FrontPanel SDK installed
- **Python Libraries:**
  ```bash
  pip install pyvisa pyvisa-py matplotlib numpy scipy reportlab
  ```

### 2. Building the FPGA Bitstream
To run non-project mode synthesis and place-and-route:
```bash
./build.sh --detach          # Starts Vivado batch build in the background
./build.sh --status          # Checks build progress until STATUS: FINISHED OK
```
The resulting bitstream is written to `bitfile/SensorBoard_Top.bit`.

### 3. Running Hardware Smoke Test
Connect the Opal Kelly XEM7310 board via USB 3.0:
```bash
python python/smoke_test.py
```
Expected output confirms that the FrontPanel USB link, PLL clocking, and $\text{I}^2\text{C}$ bus communication are healthy (`RESULT: ALL PASS`).

### 4. Running Experiments
- **Milestone 1 Acquisition & Averaging Analysis:**
  ```bash
  python python/lab7_m1.py
  ```
- **Milestone 2 Instrument Automation (DMM & Scope):**
  ```bash
  python python/lab7_m2.py
  ```

---

