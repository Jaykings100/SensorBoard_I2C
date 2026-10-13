`timescale 1ns / 1ps
//============================================================================
// I2C_Transmit.v - Complete one/two-byte reads and writes with STOP.
// All parameters are latched on start. No top-level port changes.
// param1[7:1]: slave address; param1[8]: bus (top-level selector).
// param2[7:0]: register pointer; param2[15:8]: write-data byte.
// param3[0]: 0 WRITE, 1 READ. Frame 1 always forces R/W=0.
// WRITE: START, addr+W, ACK, pointer, ACK, data, ACK, STOP.
// READ: START, addr+W, ACK, pointer, ACK, repeated START, addr+R, ACK.
// READ one or two bytes; ACK intermediate byte, NACK last, execute STOP states 152-154.
// param3[1]: 0 = one byte, 1 = two bytes; latched on start. READ ends with NACK and STOP.
// A slave NACK on any frame sets error_bit and takes STOP to idle.
// ADT7420 datasheet Figure 14 p.18, Figure 16 p.19, Table 2 p.5.
//
// HOW THE TIMING WORKS
//   The state machine advances one state per `tick`, made below from the
//   100.8 MHz clock: TICK_DIVIDE = 252 -> one tick every 2.5 us.
//   One SCL period is four states (low + set SDA, high, high, low) =
//   10 us = 100 kHz SCL, inside the 400 kHz limit of every sensor on the
//   board. t_LOW = t_HIGH = 5 us; SDA changes 2.5 us after SCL fell
//   (t_HD;DAT) and 2.5 us before it rises (t_SU;DAT); START hold and STOP
//   setup are 2.5 us. TICK_DIVIDE (set in SensorBoard_Top.v) scales all of
//   it: 126 -> 200 kHz, 63 -> 400 kHz. A one-clock enable pulse is used
//   instead of a divided clock so the whole design stays on one clock.
//
// HOW THE LINES WORK (open drain, ADT7420.pdf Table 4 p.7)
//   SCL / SDA below are what WE do to the line:
//       0 = pull the line low
//       1 = RELEASE it - the pull-up makes it high unless another device
//           (the slave, during ACK or data) is holding it low.
//   The FPGA never drives a line high. sda_in / scl_in are the real levels
//   on the wires: always read those, never SDA/SCL - while we are released
//   our own register says nothing about what the slave is doing.
//   (SensorBoard_Top.v turns scl_low/sda_low into tristate pads.)
//
// HANDSHAKE: WRITE or NACK -> done=1, busy=0, State=0 after STOP.
// Successful READ -> done=1, busy=0, State=0 after final NACK and STOP.
// One byte -> rx_data[7:0]; two bytes -> rx_data[15:8]=first, [7:0]=second.
//============================================================================
module I2C_Transmit #(
    parameter integer TICK_DIVIDE = 252   // clocks per state: 100.8 MHz / 252 = 2.5 us -> 100 kHz SCL
)(
    input  wire        clk,         // 100.8 MHz
    input  wire        rst,         // synchronous, active high
    input  wire        start,       // one-clock pulse: start selected operation (ignored while busy)
    input  wire [7:0]  tx_byte,     // byte to send = {7-bit slave address, R/W}  (param1[7:0])
    input  wire [31:0] param2,      // WireIn 0x02 - [7:0] = pointer, [15:8] = write-data byte
    input  wire [31:0] param3,      // WireIn 0x03 - [0]: READ; [1]: receive second byte
    output wire        scl_low,     // 1 = pull SCL low, 0 = release   (open drain)
    output wire        sda_low,     // 1 = pull SDA low, 0 = release
    input  wire        scl_in,      // real level on the SCL wire (for clock stretching)
    input  wire        sda_in,      // real level on the SDA wire (the slave's ACK / data)
    output reg         ACK_bit,     // sampled in the 9th clock: 0 = ACK, 1 = NACK
    output wire [31:0] rx_data,     // WireOut 0x21 - one byte [7:0] or two bytes [15:0]
    output reg         busy,        // 1 while the transaction is on the bus
    output reg         done,        // 1 after STOP for reads, writes, or slave NACK
    output reg         error_bit,   // 1 = slave NACK or undefined state
    output reg  [7:0]  State,       // 151 branch; 152-154 STOP; 155-186 second byte; 187-190 final NACK
    output wire        marker_ack   // 1 during State 34 and ACK (states 34..38) for scope trigger
);

    assign marker_ack = (State >= 8'd34 && State <= 8'd38);

    // What we drive on the two lines: 1 = release, 0 = pull low (see header)
    reg SCL = 1'b1;
    reg SDA = 1'b1;
    assign scl_low = ~SCL;
    assign sda_low = ~SDA;
    reg [7:0] ReceivedByte = 8'h00;
    reg [7:0] ReceivedByte2 = 8'h00;
    reg       ReadSecondByte = 1'b0;
    assign rx_data = ReadSecondByte ? {16'd0, ReceivedByte, ReceivedByte2}
                                    : {24'd0, ReceivedByte};

    // Tick generator: one-clock pulse every TICK_DIVIDE clocks (= 2.5 us)
    localparam integer TW = (TICK_DIVIDE <= 2) ? 1 : $clog2(TICK_DIVIDE);
    reg [TW-1:0] tick_cnt = {TW{1'b0}};
    reg          tick     = 1'b0;
    always @(posedge clk) begin
        if (rst || tick_cnt == TICK_DIVIDE - 1) begin
            tick_cnt <= {TW{1'b0}};
            tick     <= ~rst;
        end else begin
            tick_cnt <= tick_cnt + 1'b1;
            tick     <= 1'b0;
        end
    end

    // The byte being shifted out (latched from tx_byte on start)
    reg [7:0] SingleByteData = 8'h00;
    reg       ReadOperation = 1'b0;
    reg [7:0] ThirdByteData = 8'h00;
    reg [7:0] RegPointer     = 8'h00;   // latched from param2[7:0] on start
    reg       start_pending  = 1'b0;   // start seen, waiting for the next tick

    localparam STATE_INIT = 8'd0;

    initial begin
        ACK_bit   = 1'b1;
        busy      = 1'b0;
        done      = 1'b0;
        error_bit = 1'b0;
        State     = STATE_INIT;
    end

    always @(posedge clk) begin
        if (rst) begin
            State          <= STATE_INIT;
            SCL            <= 1'b1;
            SDA            <= 1'b1;
            ACK_bit        <= 1'b1;
            busy           <= 1'b0;
            done           <= 1'b0;
            error_bit      <= 1'b0;
            start_pending  <= 1'b0;
            ReceivedByte   <= 8'h00;
                ReceivedByte2  <= 8'h00;
        end else begin
            // ---- accept a start pulse at clock rate, act on it at the next tick
            if (start && !busy) begin
                SingleByteData <= {tx_byte[7:1], 1'b0};
                ReadOperation  <= param3[0];
                ReadSecondByte <= param3[1];
                ThirdByteData  <= param3[0] ? {tx_byte[7:1], 1'b1} : param2[15:8];
                RegPointer     <= param2[7:0];
                ReceivedByte   <= 8'h00;
                ReceivedByte2  <= 8'h00;
                start_pending  <= 1'b1;
                busy           <= 1'b1;
                done           <= 1'b0;
                error_bit      <= 1'b0;
                ACK_bit        <= 1'b1;
            end

            // ---- one state per tick (2.5 us)
            if (tick) begin
                case (State)

// ***************************************************
// Idle: both lines released (high). Wait for start.
// ***************************************************
            STATE_INIT : begin  SCL <= 1'b1; SDA <= 1'b1;
                                if (start_pending) begin start_pending <= 1'b0; State <= 8'd1; end   end

// ***************************************************
// Start sequence: SDA falls while SCL is high
// ***************************************************
            8'd1  :  begin  SCL <= 1'b1; State <= State + 1'b1; SDA <= 1'b0; end
            8'd2  :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b0; end

// ***************************************************
// Transmit the 1st BYTE to a sensor (MSB first, 4 states per bit)
// ***************************************************
            8'd3  :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= SingleByteData[7]; end   // transmit bit 7
            8'd4  :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd5  :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd6  :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd7  :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= SingleByteData[6]; end   // transmit bit 6
            8'd8  :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd9  :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd10 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd11 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= SingleByteData[5]; end   // transmit bit 5
            8'd12 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd13 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd14 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd15 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= SingleByteData[4]; end   // transmit bit 4
            8'd16 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd17 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd18 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd19 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= SingleByteData[3]; end   // transmit bit 3
            8'd20 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd21 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd22 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd23 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= SingleByteData[2]; end   // transmit bit 2
            8'd24 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd25 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd26 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd27 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= SingleByteData[1]; end   // transmit bit 1
            8'd28 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd29 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd30 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd31 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= SingleByteData[0]; end   // transmit bit 0
            8'd32 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd33 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd34 :  begin  SCL <= 1'b0; State <= State + 1'b1; end

// ***************************************************
// Release SDA and read the ACK the sensor drives (9th clock)
// ***************************************************
            8'd35 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // RELEASE the line (1 = let go, pull-up/slave decide)
            8'd36 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd37 :  begin  SCL <= 1'b1; State <= State + 1'b1; ACK_bit <= sda_in;
                            if (sda_in) error_bit <= 1'b1; end   // read the real wire
            8'd38 :  begin  SCL <= 1'b0;
                            if (ACK_bit) State <= 8'd152; else State <= 8'd39; end   // NACK: STOP; ACK: frame 2

// ***************************************************
// Transmit the 2nd BYTE: register pointer (MSB first, 4 states per bit)
// ***************************************************
            8'd39 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= RegPointer[7]; end   // transmit bit 7
            8'd40 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd41 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd42 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd43 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= RegPointer[6]; end   // transmit bit 6
            8'd44 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd45 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd46 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd47 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= RegPointer[5]; end   // transmit bit 5
            8'd48 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd49 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd50 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd51 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= RegPointer[4]; end   // transmit bit 4
            8'd52 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd53 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd54 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd55 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= RegPointer[3]; end   // transmit bit 3
            8'd56 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd57 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd58 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd59 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= RegPointer[2]; end   // transmit bit 2
            8'd60 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd61 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd62 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd63 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= RegPointer[1]; end   // transmit bit 1
            8'd64 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd65 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd66 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd67 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= RegPointer[0]; end   // transmit bit 0
            8'd68 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd69 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd70 :  begin  SCL <= 1'b0; State <= State + 1'b1; end

// ***************************************************
// Release SDA and read the frame 2 ACK the sensor drives (9th clock)
// ***************************************************
            8'd71 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // RELEASE SDA for the sensor
            8'd72 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd73 :  begin  SCL <= 1'b1; State <= State + 1'b1; ACK_bit <= sda_in;
                            if (sda_in) error_bit <= 1'b1; end   // read the real wire
            8'd74 :  begin  SCL <= 1'b0;
                            if (ACK_bit) State <= 8'd152;
                            else if (ReadOperation) State <= 8'd75;
                            else State <= 8'd79; end   // WRITE skips repeated START

// ***************************************************
// READ only: repeated START (SDA falls while SCL is high)
// ***************************************************
            8'd75 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end
            8'd76 :  begin  SCL <= 1'b1; State <= State + 1'b1; SDA <= 1'b1; end
            8'd77 :  begin  SCL <= 1'b1; State <= State + 1'b1; SDA <= 1'b0; end
            8'd78 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b0; end

// ***************************************************
// Frame 3: WRITE data or READ slave address with R/W=1
// ***************************************************
            8'd79 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= ThirdByteData[7]; end   // transmit bit 7
            8'd80 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd81 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd82 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd83 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= ThirdByteData[6]; end   // transmit bit 6
            8'd84 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd85 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd86 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd87 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= ThirdByteData[5]; end   // transmit bit 5
            8'd88 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd89 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd90 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd91 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= ThirdByteData[4]; end   // transmit bit 4
            8'd92 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd93 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd94 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd95 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= ThirdByteData[3]; end   // transmit bit 3
            8'd96 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd97 :  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd98 :  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd99 :  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= ThirdByteData[2]; end   // transmit bit 2
            8'd100:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd101:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd102:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd103:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= ThirdByteData[1]; end   // transmit bit 1
            8'd104:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd105:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd106:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd107:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= ThirdByteData[0]; end   // transmit bit 0
            8'd108:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd109:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd110:  begin  SCL <= 1'b0; State <= State + 1'b1; end

// ***************************************************
// Frame 3: release SDA and sample the slave ACK
// ***************************************************
            8'd111:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end
            8'd112:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd113:  begin  SCL <= 1'b1; State <= State + 1'b1; ACK_bit <= sda_in;
                            if (sda_in) error_bit <= 1'b1; end
            8'd114:  begin  SCL <= 1'b0;
                            if (ACK_bit || !ReadOperation) State <= 8'd152;
                            else State <= 8'd115; end

// ***************************************************
// Receive first data BYTE: MSB first, release SDA, sample while SCL high
// ***************************************************
            8'd115:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 7
            8'd116:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd117:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte[7] <= sda_in; end   // sample bit 7
            8'd118:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd119:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 6
            8'd120:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd121:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte[6] <= sda_in; end   // sample bit 6
            8'd122:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd123:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 5
            8'd124:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd125:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte[5] <= sda_in; end   // sample bit 5
            8'd126:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd127:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 4
            8'd128:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd129:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte[4] <= sda_in; end   // sample bit 4
            8'd130:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd131:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 3
            8'd132:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd133:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte[3] <= sda_in; end   // sample bit 3
            8'd134:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd135:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 2
            8'd136:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd137:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte[2] <= sda_in; end   // sample bit 2
            8'd138:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd139:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 1
            8'd140:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd141:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte[1] <= sda_in; end   // sample bit 1
            8'd142:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd143:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 0
            8'd144:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd145:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte[0] <= sda_in; end   // sample bit 0
            8'd146:  begin  SCL <= 1'b0; State <= State + 1'b1; end

// ***************************************************
// First byte: master ACK if reading another byte; master NACK if last
// ***************************************************
            8'd147:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= ~ReadSecondByte; end
            8'd148:  begin  SCL <= 1'b1; State <= State + 1'b1; SDA <= ~ReadSecondByte; end
            8'd149:  begin  SCL <= 1'b1; State <= State + 1'b1; SDA <= ~ReadSecondByte; end
            8'd150:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= ~ReadSecondByte; end

// ***************************************************
// Read another byte? YES -> second receive; NO -> STOP entry
// ***************************************************
            8'd151:  begin  SCL <= 1'b0; SDA <= 1'b1;
                            if (ReadSecondByte) State <= 8'd155;
                            else State <= 8'd152; end


// ***************************************************
// STOP: SDA low with SCL low; raise SCL; release SDA while SCL high
// ***************************************************
            8'd152:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b0; end
            8'd153:  begin  SCL <= 1'b1; State <= State + 1'b1; SDA <= 1'b0; end
            8'd154:  begin  SCL <= 1'b1; SDA <= 1'b1;
                            busy <= 1'b0; done <= 1'b1; State <= STATE_INIT; end

// ***************************************************
// Receive second data BYTE (MSB first, same four-state layout)
// ***************************************************
            8'd155:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 7
            8'd156:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd157:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte2[7] <= sda_in; end   // sample bit 7
            8'd158:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd159:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 6
            8'd160:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd161:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte2[6] <= sda_in; end   // sample bit 6
            8'd162:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd163:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 5
            8'd164:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd165:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte2[5] <= sda_in; end   // sample bit 5
            8'd166:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd167:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 4
            8'd168:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd169:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte2[4] <= sda_in; end   // sample bit 4
            8'd170:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd171:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 3
            8'd172:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd173:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte2[3] <= sda_in; end   // sample bit 3
            8'd174:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd175:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 2
            8'd176:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd177:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte2[2] <= sda_in; end   // sample bit 2
            8'd178:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd179:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 1
            8'd180:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd181:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte2[1] <= sda_in; end   // sample bit 1
            8'd182:  begin  SCL <= 1'b0; State <= State + 1'b1; end
            8'd183:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end   // release SDA for bit 0
            8'd184:  begin  SCL <= 1'b1; State <= State + 1'b1; end
            8'd185:  begin  SCL <= 1'b1; State <= State + 1'b1; ReceivedByte2[0] <= sda_in; end   // sample bit 0
            8'd186:  begin  SCL <= 1'b0; State <= State + 1'b1; end

// ***************************************************
// Second byte is last: master NACK (SDA released on ninth clock)
// ***************************************************
            8'd187:  begin  SCL <= 1'b0; State <= State + 1'b1; SDA <= 1'b1; end
            8'd188:  begin  SCL <= 1'b1; State <= State + 1'b1; SDA <= 1'b1; end
            8'd189:  begin  SCL <= 1'b1; State <= State + 1'b1; SDA <= 1'b1; end
            8'd190:  begin  SCL <= 1'b0; State <= 8'd152; SDA <= 1'b1; end   // final NACK complete; execute STOP next

            // If the FSM ends up here, there was an error in the FSM code:
            // flag it, release the bus and go back to idle.
            default : begin  error_bit <= 1'b1; SCL <= 1'b1; SDA <= 1'b1;
                             busy <= 1'b0; done <= 1'b1; State <= STATE_INIT; end

                endcase
            end
        end
    end

endmodule
