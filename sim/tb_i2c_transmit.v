`timescale 1ns / 1ps
//============================================================================
// tb_i2c_transmit.v - Testbench for hdl/I2C_Transmit.v (the file you edit).
//
// Run:  ./build.sh --sim        (xsim, log in sim/sim.log, waveform sim/tb.vcd)
// or open the Vivado project in build/vivado and "Run Simulation".
//
// The state machine is simulated on its own (the top level only adds pads,
// the bus selector and the PC endpoints): 100.8 MHz clock, reset, a byte,
// a start pulse, wait for done (with a timeout), print and check the results.
// One I2C bus with a pull-up carries two behavioural slaves from
// sim/i2c_slave_model.v: an "ADT7420" at 0x48 (ID 0x0B = 0xCB, temperature
// 0x00/0x01 = 0x0C 0xA0) and an "LSM303 accel" at 0x19. The slaves print
// START / STOP / address / byte events, so a protocol error is visible in
// the log without a scope.
//
// Transactions sent:
//   1. LSM303 accel register write (address 0x19, pointer 0x20, data 0x57)
//   2. ADT7420 ID single-byte read (register 0x0B -> 0xCB)
//   3. ADT7420 temperature two-byte read (register 0x00 -> 0x0C, 0xA0)
//   4. Missing address 0x49 -> NACK, error, STOP; next transaction checks recovery.
// Preload other registers / add slaves at other addresses to match the
// sensor you are implementing, and extend the checks as the FSM grows.
//============================================================================
module tb_i2c_transmit;

    // ---- clock / reset ---------------------------------------------------
    reg clk = 1'b0;
    always #4.96 clk = ~clk;              // 100.8 MHz
    reg rst = 1'b1;

    // ---- host side --------------------------------------------------------
    reg         start = 1'b0;
    reg  [7:0]  tx_byte = 8'h00;
    reg  [31:0] param2 = 32'd0, param3 = 32'd0;
    wire        ACK_bit, busy, done, error_bit;
    wire [31:0] rx_data;
    wire [7:0]  State;

    // ---- one I2C bus with pull-ups and two slaves --------------------------
    wire scl, sda;
    pullup (scl); pullup (sda);
    wire scl_low, sda_low;
    assign scl = scl_low ? 1'b0 : 1'bz;
    assign sda = sda_low ? 1'b0 : 1'bz;

    i2c_slave_model #(.ADDR(7'h48), .NAME("ADT7420"))  u_adt7420 (.scl(scl), .sda(sda));
    i2c_slave_model #(.ADDR(7'h19), .NAME("LSM303_A")) u_lsm303a (.scl(scl), .sda(sda));

    I2C_Transmit #(.TICK_DIVIDE(252)) dut (
        .clk(clk), .rst(rst), .start(start),
        .tx_byte(tx_byte), .param2(param2), .param3(param3),
        .scl_low(scl_low), .sda_low(sda_low), .scl_in(scl), .sda_in(sda),
        .ACK_bit(ACK_bit), .rx_data(rx_data),
        .busy(busy), .done(done), .error_bit(error_bit), .State(State)
    );

    // ---- bookkeeping: cycle counter (like result2), STOP counter -----------
    integer cycles = 0;
    always @(posedge clk) if (busy) cycles = cycles + 1;
    integer stops = 0;
    always @(posedge sda) if (scl === 1'b1) stops = stops + 1;

    integer fails = 0;
    task check(input [8*64-1:0] name, input cond);
        begin
            if (cond) $display("%0t  TB: PASS %0s", $time, name);
            else begin $display("%0t  TB: FAIL %0s", $time, name); fails = fails + 1; end
        end
    endtask

    // ---- one parameterized register transaction ---------------------------
    task run_transaction(
        input [7:0] address_byte,
        input [7:0] pointer,
        input [7:0] write_data,
        input       read_operation,
        input       read_second_byte,
        input integer timeout_us
    );
        integer t;
        begin
            tx_byte = address_byte;
            param2 = {16'd0, write_data, pointer};
            param3 = {30'd0, read_second_byte, read_operation};
            cycles = 0;
            @(posedge clk); start <= 1'b1; @(posedge clk); start <= 1'b0;
            @(negedge clk);                      // the FSM has now cleared done / raised busy
            t = 0;
            while (!done && t < timeout_us * 1000) begin #1 t = t + 1; end
            @(posedge clk); @(posedge clk);
            if (!done) $display("%0t  TB: TIMEOUT after %0d us (State %0d, busy %b)", $time, timeout_us, State, busy);
            else $display("%0t  TB: done. addr 0x%02X pointer 0x%02X read=%b -> ACK_bit=%0d error_bit=%b rx=0x%08X (%0d cycles)",
                          $time, address_byte, pointer, read_operation, ACK_bit, error_bit, rx_data, cycles);
        end
    endtask

    integer s0;
    initial begin
        $dumpfile("tb.vcd");
        $dumpvars(0, tb_i2c_transmit);

        // preload slave registers
        u_adt7420.mem[8'h00] = 8'h0C;   // temperature MSB (25.25 C)
        u_adt7420.mem[8'h01] = 8'hA0;   // temperature LSB
        u_adt7420.mem[8'h0B] = 8'hCB;   // ID
        u_lsm303a.mem[8'h20] = 8'h07;   // CTRL_REG1_A power-on default
        u_lsm303a.mem[8'h28] = 8'h00;   // OUT_X_L_A

        repeat (5) @(posedge clk); rst <= 1'b0;
        repeat (5) @(posedge clk);
        check("idle after reset: busy=0 done=0 State=0, lines released", !busy && !done && State == 8'd0 && !scl_low && !sda_low);

        $display("---- transaction 1: write LSM303 CTRL_REG1_A = 0x57 ----");
        s0 = stops;
        run_transaction(8'h32, 8'h20, 8'h57, 1'b0, 1'b0, 500);
        check("write: LSM303 ACKed and no error", done && ACK_bit == 1'b0 && !error_bit);
        check("write: slave register updated", u_lsm303a.mem[8'h20] == 8'h57);
        check("write: STOP seen", stops == s0 + 1);
        check("write: 100 kHz transaction duration", cycles >= 28000 && cycles <= 30000);
        check("write: idle, released lines after STOP", !busy && State == 8'd0 && !scl_low && !sda_low);

        $display("---- transaction 2: read ADT7420 ID register 0x0B ----");
        s0 = stops;
        run_transaction(8'h90, 8'h0B, 8'h00, 1'b1, 1'b0, 700);
        check("single-byte read: address ACK and no error", done && ACK_bit == 1'b0 && !error_bit);
        check("single-byte read: ID is 0xCB", rx_data[7:0] == 8'hCB);
        check("single-byte read: STOP seen", stops == s0 + 1);

        $display("---- transaction 3: read ADT7420 temperature bytes ----");
        s0 = stops;
        run_transaction(8'h90, 8'h00, 8'h00, 1'b1, 1'b1, 900);
        check("two-byte read: address ACK and no error", done && ACK_bit == 1'b0 && !error_bit);
        check("two-byte read: bytes are 0x0C, 0xA0", rx_data[15:0] == 16'h0CA0);
        check("two-byte read: STOP after final master NACK", stops == s0 + 1);

        $display("---- transaction 4: NACK missing address 0x49 ----");
        s0 = stops;
        run_transaction(8'h92, 8'h00, 8'h00, 1'b0, 1'b0, 500);
        check("missing address: NACK, error, and done", done && ACK_bit == 1'b1 && error_bit);
        check("missing address: STOP seen", stops == s0 + 1);

        $display("---- transaction 5: valid read after NACK ----");
        run_transaction(8'h90, 8'h0B, 8'h00, 1'b1, 1'b0, 700);
        check("recovery: ID read succeeds after NACK", done && !error_bit && rx_data[7:0] == 8'hCB);

        repeat (10) @(posedge clk);
        $display("%0t  TB: finished, %0d failure(s)  ->  %0s", $time, fails, fails == 0 ? "RESULT: ALL PASS" : "RESULT: FAIL");
        $finish;
    end
endmodule
