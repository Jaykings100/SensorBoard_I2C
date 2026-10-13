"""
build_postlab_pdf.py - Builds the official Lab 7 Post-Lab PDF report using ReportLab.
Includes all plots, tables, derivations, and answers for Questions 1-4.
"""
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

def build_pdf():
    pdf_path = Path("docs/lab7_postlab.pdf")
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        rightMargin=45,
        leftMargin=45,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#1a2a3a')
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=13,
        leading=16,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#3a506b')
    )
    author_style = ParagraphStyle(
        'DocAuthor',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#2c3e50')
    )
    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=colors.HexColor('#0b3954'),
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True
    )
    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#2c3e50'),
        spaceBefore=6,
        spaceAfter=3,
        keepWithNext=True
    )
    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        alignment=TA_JUSTIFY,
        spaceAfter=4
    )
    body_bold = ParagraphStyle(
        'BodyBold',
        parent=body_style,
        fontName='Helvetica-Bold'
    )
    caption_style = ParagraphStyle(
        'Caption',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8.5,
        leading=11.5,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#4a5568'),
        spaceBefore=3,
        spaceAfter=6
    )
    bullet_style = ParagraphStyle(
        'Bullet',
        parent=body_style,
        leftIndent=14,
        firstLineIndent=-10,
        spaceAfter=3
    )

    story = []

    # Title Block
    story.append(Paragraph("ECE 437 Lab 7: Noise, Averaging, and the Limits of Measurement", title_style))
    story.append(Spacer(1, 3))
    story.append(Paragraph("Official Post-Lab Report", subtitle_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Author: <b>Jason Osei-Tutu</b> &nbsp;|&nbsp; Date: October 13, 2026", author_style))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0b3954'), spaceBefore=2, spaceAfter=8))

    # =========================================================================
    # QUESTION 1
    # =========================================================================
    story.append(Paragraph("Question 1: Where Averaging Stops Helping (10 points)", h1_style))
    
    # 1a
    story.append(Paragraph("<b>(a) Averaging Law Departure Analysis</b>", h2_style))
    story.append(Paragraph(
        "Figure 1 displays the log-log plot of the standard deviation of block averages &sigma;<sub>N</sub> against block averaging count <i>N</i> &isin; {1, 2, 4, 8, ..., 256}, plotted alongside the theoretical 1/&radic;N reference line (&sigma;<sub>1</sub>/&radic;N).",
        body_style
    ))
    
    avg_img_path = Path("lab7_milestone1_data/milestone1_averaging.png")
    if avg_img_path.exists():
        story.append(Image(str(avg_img_path), width=5.8*inch, height=3.0*inch))
        story.append(Paragraph("<b>Figure 1:</b> Milestone 1b log-log plot of block mean standard deviation vs. <i>N</i> with 1/&radic;N reference line.", caption_style))

    story.append(Paragraph("<b>Departure Point & Range of Follow:</b>", body_style))
    story.append(Paragraph("&bull; <b>Follow Range:</b> The experimental data does <b>not</b> follow the theoretical 1/&radic;N reference curve over any extended range.", bullet_style))
    story.append(Paragraph("&bull; <b>Departure Point:</b> The measured standard deviation departs from the 1/&radic;N line immediately at <b>N = 2</b>. While the theoretical model predicts &sigma; should scale down by 1/&radic;N (dropping from 0.0269&deg;C at <i>N</i>=1 down to 0.00168&deg;C at <i>N</i>=256), the measured standard deviation stays virtually flat across the entire sweep: &sigma;<sub>1</sub> = 0.02687&deg;C, &sigma;<sub>2</sub> = 0.02688&deg;C, &sigma;<sub>4</sub> = 0.02672&deg;C, &sigma;<sub>16</sub> = 0.02645&deg;C, and &sigma;<sub>256</sub> = 0.02775&deg;C.", bullet_style))

    # 1b
    story.append(Paragraph("<b>(b) Fast vs. Slow (300 ms) 100-Reading Sets</b>", h2_style))
    story.append(Paragraph("From the experimental capture summarized in <code>milestone1_summary.txt</code>:", body_style))
    story.append(Paragraph("&bull; <b>First 100 Fast Readings Standard Deviation:</b> &sigma;<sub>fast, 100</sub> = <b>0.004616&deg;C</b>", bullet_style))
    story.append(Paragraph("&bull; <b>100 Slow Readings (300 ms Cadence) Standard Deviation:</b> &sigma;<sub>slow, 100</sub> = <b>0.016614&deg;C</b>", bullet_style))
    story.append(Paragraph("&bull; <b>Ratio (&sigma;<sub>slow</sub> / &sigma;<sub>fast</sub>):</b> <b>3.60&times;</b> higher standard deviation in the slow set.", bullet_style))
    story.append(Paragraph(
        "<b>Physical Explanation:</b> The ADT7420 temperature sensor has an internal continuous conversion period of approximately <b>240 ms</b> in 16-bit mode. "
        "During the fast loop, 1,000 readings were fetched over USB in only 2.36 seconds (~2.36 ms per reading). Therefore, the first 100 readings completed in less than 240 ms total, repeatedly reading the <i>exact same internal conversion word</i> from the sensor's register. This resulted in an artificially low standard deviation (&sigma; &approx; 0.0046&deg;C) because the software was measuring repeated copies of identical data rather than genuine noise.<br/>"
        "In contrast, the slow set waited 300 ms between queries (300 ms &gt; 240 ms), ensuring that every single reading captured a <b>genuinely new, independent analog-to-digital conversion</b> with its own independent thermal noise sample.<br/>"
        "<b>Which set averaging helps:</b> Averaging <b>only ever helps the 300 ms slow set</b>. The Central Limit Theorem (&sigma;<sub>N</sub> = &sigma;/&radic;N) strictly requires samples to be independent and identically distributed (i.i.d.). Averaging repeated identical conversions provides zero new statistical information.",
        body_style
    ))

    # 1c
    story.append(Paragraph("<b>(c) Noise Floor vs. Quantization Resolution</b>", h2_style))
    story.append(Paragraph(
        "In 16-bit mode, 1 LSB = 1/128&deg;C = <b>0.0078125&deg;C</b>, and the ideal quantization noise floor is LSB/&radic;12 = <b>0.002255&deg;C</b>. "
        "The flat region of our averaging plot sits at approximately &sigma;<sub>flat</sub> &approx; <b>0.0265&deg;C</b>.<br/>"
        "Comparing these values: &sigma;<sub>flat</sub> (0.0265&deg;C) &gt;&gt; 1 LSB (0.0078&deg;C) &gt;&gt; LSB/&radic;12 (0.0023&deg;C). Specifically, &sigma;<sub>flat</sub> is <b>3.4&times; larger than 1 full LSB</b> and <b>11.7&times; larger than the quantization noise limit</b>. "
        "This proves that the flat floor is <b>not quantization-limited</b>. Once the curve levels off, we are observing the true analog front-end noise floor of the ADT7420 (bandgap thermal noise, amplifier flicker noise, and reference fluctuation), spanning multiple raw ADC codes.",
        body_style
    ))

    story.append(PageBreak())

    # =========================================================================
    # QUESTION 2
    # =========================================================================
    story.append(Paragraph("Question 2: What Integration Time Does (5 points)", h1_style))
    story.append(Paragraph("<b>(a) Multimeter Integration Time (NPLC) Sweep</b>", h2_style))
    story.append(Paragraph(
        "Figure 2 displays the standard deviation of DC voltage readings on the Keysight 34461A digital multimeter plotted against integration time (NPLC) on log-log axes.",
        body_style
    ))

    nplc_img_path = Path("milestone2_data/part_2a/milestone2a_nplc.png")
    if not nplc_img_path.exists():
        nplc_img_path = Path("lab7_milestone2_data/milestone2a_nplc.png")
    if nplc_img_path.exists():
        story.append(Image(str(nplc_img_path), width=5.6*inch, height=2.8*inch))
        story.append(Paragraph("<b>Figure 2:</b> Milestone 2a DC voltage standard deviation vs. integration time (NPLC) on log-log axes.", caption_style))

    # NPLC Table
    nplc_data = [
        ["NPLC", "Integration Time", "Mean Voltage (V)", "Std Dev (V)", "Sample Count"],
        ["0.02", "0.33 ms", "-6.136 × 10⁻⁶", "4.516 × 10⁻⁶ (4.52 µV)", "200"],
        ["0.20", "3.33 ms", "-6.417 × 10⁻⁶", "2.597 × 10⁻⁶ (2.60 µV)", "200"],
        ["1.00", "16.67 ms", "-6.376 × 10⁻⁶", "2.365 × 10⁻⁷ (0.24 µV)", "200"],
        ["10.00", "166.7 ms", "-5.777 × 10⁻⁶", "3.887 × 10⁻⁷ (0.39 µV)", "200"],
        ["100.00", "1.667 s", "-0.951 × 10⁻⁶", "1.837 × 10⁻⁶ (1.84 µV)", "200"]
    ]
    t_nplc = Table(nplc_data, colWidths=[1.0*inch, 1.3*inch, 1.4*inch, 1.6*inch, 1.0*inch])
    t_nplc.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0b3954')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8.5),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f7fafc')])
    ]))
    story.append(t_nplc)
    story.append(Spacer(1, 4))

    # 2b
    story.append(Paragraph("<b>(b) 60 Hz Cancellation & Integrating vs. Sampling</b>", h2_style))
    story.append(Paragraph(
        "<b>1. Effect of NPLC = 1 on 60 Hz Interference:</b><br/>"
        "At a line frequency of 60 Hz, one power line cycle corresponds to exactly <i>T</i><sub>line</sub> = 1/60 s &approx; <b>16.67 ms</b>. "
        "The integrating multislope ADC calculates the time-average of the input signal over its integration window <i>T</i><sub>int</sub>:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;<i>V</i><sub>meas</sub> = (1 / <i>T</i><sub>int</sub>) &int; [ <i>V</i><sub>DC</sub> + <i>A</i><sub>60</sub> sin(2&pi;&middot;60<i>t</i> + &phi;) ] dt<br/>"
        "When <i>T</i><sub>int</sub> = 1 NPLC = 16.67 ms, the integral of the 60 Hz sinusoid over exactly one full cycle evaluates to identically <b>zero</b>, producing an infinite notch filter (&gt; 60 dB Normal Mode Rejection) at 60 Hz and all its integer harmonics.<br/>"
        "At 0.02 and 0.2 NPLC, the meter integrates over only a fraction of the cycle (0.33 ms or 3.33 ms), capturing instantaneous AC ripple at random phases, which inflates the measured noise to 4.52 &mu;V. Integrating over exactly 1 NPLC cancels the 60 Hz interference completely, reducing standard deviation by <b>19.1&times;</b> down to just <b>236 nV</b>.",
        body_style
    ))
    story.append(Paragraph(
        "<b>2. What the Meter Does That a Single Scope Sample Does Not:</b><br/>"
        "An oscilloscope takes an instantaneous point sample over a sub-nanosecond aperture, capturing whatever instantaneous noise or 60 Hz voltage exists at that microsecond. The multimeter, in contrast, performs <b>continuous analog time-integration</b> over the entire measurement window (a boxcar filter in the time domain, producing a sinc(<i>f</i>&middot;<i>T</i><sub>int</sub>) response in frequency), which continuously averages away wideband noise and places nulls at mains frequencies prior to digitization.",
        body_style
    ))

    story.append(PageBreak())

    # =========================================================================
    # QUESTION 3
    # =========================================================================
    story.append(Paragraph("Question 3: The Loop You Built by Accident (5 points)", h1_style))
    story.append(Paragraph("<b>(a) FFT Spectra, Loop Areas, and Induced Voltage Ratio</b>", h2_style))
    story.append(Paragraph(
        "Figure 3 displays the physical bench setups for both the minimal short wire configuration and the intentional long wire loop across the DC power supply terminals. Figure 4 shows the corresponding frequency spectra captured with the oscilloscope on common axes.",
        body_style
    ))

    short_img_path = Path("docs/images/short_wire_loop.png")
    long_img_path = Path("docs/images/long_wire_loop.jpg")
    if short_img_path.exists() and long_img_path.exists():
        photos_table = Table([
            [Image(str(short_img_path), width=3.3*inch, height=2.48*inch),
             Image(str(long_img_path), width=3.3*inch, height=2.48*inch)],
            [Paragraph("<b>(a) Short Wire Configuration</b><br/>Minimal loop at supply terminals (<i>A</i> &approx; 0.25 cm²)", caption_style),
             Paragraph("<b>(b) Long Wire Loop Configuration</b><br/>Extended loop antenna (<i>A</i> &approx; 100 cm²)", caption_style)]
        ], colWidths=[3.5*inch, 3.5*inch])
        photos_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))
        story.append(photos_table)
        story.append(Paragraph("<b>Figure 3:</b> Milestone 2b physical bench setups showing the contrast in enclosed inductive loop area.", caption_style))
        story.append(Spacer(1, 4))

    fft_img_path = Path("milestone2_data/part_2b/milestone2b_fft.png")
    if fft_img_path.exists():
        story.append(Image(str(fft_img_path), width=5.8*inch, height=2.8*inch))
        story.append(Paragraph("<b>Figure 4:</b> Milestone 2b FFT comparison on common axes (0–500 Hz): Short Ground Spring vs. Long Wire Loop.", caption_style))

    # Loop table
    loop_data = [
        ["Configuration", "Estimated Loop Area (A)", "60 Hz Peak Amplitude (V₆₀)"],
        ["Config 1: Short Ground Spring", "≈ 0.5 cm × 0.5 cm ≈ 0.25 cm²", "0.0857 mV (85.7 µV)"],
        ["Config 2: Long Wire Loop", "≈ 10 cm × 10 cm ≈ 100 cm²", "0.0965 mV (96.5 µV)"],
        ["Ratio (Loop / Spring)", "≈ 400×", "1.13× (measured open bench)"]
    ]
    t_loop = Table(loop_data, colWidths=[2.2*inch, 2.3*inch, 2.0*inch])
    t_loop.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0b3954')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8.5),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f7fafc')])
    ]))
    story.append(t_loop)
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "<b>Faraday's Law Analysis & Discrepancy Discussion:</b><br/>"
        "According to Faraday's Law of Magnetic Induction, the electromotive force induced in a closed loop by an alternating magnetic field <i>B</i>(<i>t</i>) = <i>B</i><sub>0</sub> sin(&omega;<i>t</i>) is:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;<i>V</i><sub>ind</sub> = -d&Phi;<sub>B</sub>/dt = -<i>A</i> &middot; (dB/dt) = -<i>A</i> &middot; &omega; <i>B</i><sub>0</sub> cos(&omega;<i>t</i>)<br/>"
        "In theory, the induced 60 Hz pickup voltage is directly proportional to the enclosed loop area <i>A</i>. In our initial bench run, the measured amplitude ratio was 1.13&times; because the DC power supply was in the <code>OUTPUT OFF</code> state (internal relay open), leaving the long wire dangling open without completing a low-impedance loop. When a closed loop is completed and oriented normal to the bench transformers, Faraday's Law predicts the induced voltage scales directly with the loop area ratio (&approx; 400&times;).",
        body_style
    ))

    # 3b
    story.append(Paragraph("<b>(b) Noise Classification & Averaging</b>", h2_style))
    story.append(Paragraph(
        "<b>Classification:</b> The 60 Hz line is <b>interference</b> (deterministic, coherent electromagnetic pickup), not random Gaussian noise and not static DC bias.<br/>"
        "<b>Would averaging remove it?</b> <b>No.</b> Standard unsynchronized averaging does not reliably remove periodic interference. Because the 60 Hz signal is coherent and deterministic, averaging arbitrary samples without synchronization does not obey the 1/&radic;N decay law. It can only be eliminated by physical shielding, minimizing loop area, or explicitly synchronizing the integration window to integer multiples of 16.67 ms (1 NPLC).",
        body_style
    ))

    story.append(PageBreak())

    # =========================================================================
    # QUESTION 4
    # =========================================================================
    story.append(Paragraph("Question 4: What the Bus Can Really Do (5 points)", h1_style))
    story.append(Paragraph("<b>(a) Captured ACK Edge and Asymmetry</b>", h2_style))
    story.append(Paragraph(
        "Figure 5 shows the oscilloscope capture of the I²C bus acknowledgment edge, triggered by the FPGA's PMOD marker pulse right before the ACK cycle.",
        body_style
    ))

    edge_img_path = Path("milestone2_data/part_2c/milestone2c_sda_edge.png")
    if edge_img_path.exists():
        story.append(Image(str(edge_img_path), width=5.8*inch, height=3.0*inch))
        story.append(Paragraph("<b>Figure 5:</b> Milestone 2c I²C SDA Acknowledgment Edge and PMOD Marker on common axes.", caption_style))

    story.append(Paragraph("<b>Measured Parameters (from Python edge analysis):</b>", body_style))
    story.append(Paragraph("&bull; <b>10%–90% Rise Time (t<sub>rise</sub>):</b> <b>839.52 ns</b>", bullet_style))
    story.append(Paragraph("&bull; <b>90%–10% Fall Time (t<sub>fall</sub>):</b> <b>1.60 ns</b>", bullet_style))
    story.append(Paragraph("&bull; <b>Asymmetry Ratio (t<sub>rise</sub> / t<sub>fall</sub>):</b> <b>526.0&times;</b> slower rise than fall!", bullet_style))
    story.append(Paragraph("&bull; <b>Voltage Thresholds:</b> <i>V</i><sub>10%</sub> = 1.009 V, <i>V</i><sub>90%</sub> = 2.006 V", bullet_style))

    story.append(Paragraph(
        "<b>Explanation of Asymmetry:</b> I²C is an open-drain bus with passive 10 k&Omega; pull-up resistors:<br/>"
        "&bull; <b>Slow Rise:</b> When the FPGA master releases SDA, neither chip actively drives the line. The line is charged purely passively through the 10 k&Omega; pull-up resistor into the bus capacitance, resulting in a classic exponential RC charging curve with a long time constant (&tau; &approx; 382 ns).<br/>"
        "&bull; <b>Fast Fall:</b> When the ADT7420 sensor asserts ACK on the 9th clock cycle, its internal open-drain NMOS transistor actively turns on, sinking charge directly to ground through a low on-resistance (<i>R</i><sub>on</sub> &approx; 15 &Omega;). This active discharge takes only <b>1.6 ns</b>.",
        body_style
    ))

    # 4b
    story.append(Paragraph("<b>(b) Bus Capacitance & Supported Speed Mode</b>", h2_style))
    story.append(Paragraph(
        "For an exponential RC charge <i>V</i>(<i>t</i>) = <i>V</i><sub>DD</sub>(1 - e<sup>-t/&tau;</sup>), the 10% to 90% rise time is:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;<i>t</i><sub>rise</sub> = &tau; &middot; ln(0.90 / 0.10) = &tau; &middot; ln(9) &approx; <b>2.1972 &middot; &tau;</b><br/>"
        "Extracting the bus time constant &tau; from our measured <i>t</i><sub>rise</sub> = 839.52 ns:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&tau; = <i>t</i><sub>rise</sub> / 2.1972 = 839.52 ns / 2.1972 = <b>382.08 ns</b><br/>"
        "Using the schematic pull-up resistor <i>R</i><sub>pullup</sub> = 10 k&Omega; = 10,000 &Omega; (resistors R4–R7 on bus 0):<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;<b>C<sub>bus</sub> = &tau; / R<sub>pullup</sub> = 382.08 ns / 10,000 &Omega; = 38.21 pF</b>",
        body_style
    ))
    story.append(Paragraph(
        "<b>Speed Mode & Bottleneck Analysis:</b><br/>"
        "&bull; <b>Standard Mode (100 kHz):</b> The I²C specification allows a maximum rise time of <b>1000 ns</b>. Since 839.52 ns &lt; 1000 ns, our board <b>can support Standard Mode</b>.<br/>"
        "&bull; <b>Fast Mode (400 kHz):</b> The I²C specification allows a maximum rise time of <b>300 ns</b>. Since 839.52 ns &gt; 300 ns, our board <b>cannot support Fast Mode</b>.<br/>"
        "&bull; <b>ADT7420 Datasheet vs. Real Limit:</b> The ADT7420 datasheet states the sensor silicon supports up to 400 kHz Fast Mode. The sensor is therefore <b>not</b> the limiting factor. The <b>real limit is the board's RC time constant</b> governed by the large 10 k&Omega; pull-up resistor and 38.2 pF trace capacitance. To support Fast Mode, <i>R</i><sub>pullup</sub> would need to be reduced to &le; 300 ns / (2.1972 &middot; 38.21 pF) &approx; <b>3.57 k&Omega;</b> (e.g. 2.2 k&Omega;).",
        body_style
    ))

    # 4c
    story.append(Paragraph("<b>(c) Summary: Random Noise, Interference, and Bias</b>", h2_style))
    summary_data = [
        ["Category", "Example from Our Data", "Corrective Action", "Helped by Averaging?"],
        ["Random Noise", "ADT7420 analog conversion noise in 16-bit mode (σ = 0.0166°C).", "Space samples by ≥ 240 ms to ensure independent conversions; average N samples.", "Yes (proportional to 1/√N)"],
        ["Interference", "60 Hz magnetic pickup in oscilloscope probe ground loop (V₆₀ ≈ 0.1 mV).", "Minimize enclosed loop area (ground spring) or integrate over 1 PLC (16.67 ms).", "No (deterministic; averaging does not decay periodic noise)"],
        ["Bias", "Static room-temp sensor calibration offset or DMM DC offset (-6.4 µV).", "Perform multi-point calibration and subtract the baseline offset.", "No (bias is constant and does not decay with sample count)"]
    ]
    t_sum = Table(summary_data, colWidths=[1.3*inch, 2.0*inch, 2.1*inch, 1.4*inch])
    t_sum.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0b3954')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f7fafc')])
    ]))
    story.append(t_sum)

    doc.build(story)
    print(f"Successfully compiled {pdf_path} ({pdf_path.stat().st_size} bytes)")

if __name__ == "__main__":
    build_pdf()

