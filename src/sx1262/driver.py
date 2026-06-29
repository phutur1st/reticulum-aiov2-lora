"""Userspace SX1262 driver for the HackerGadgets uConsole AiO V2.

Drives the bare SX1262 over SPI from a Raspberry Pi CM5 (RP1) using
``spidev`` + ``lgpio``. Pin numbers are BCM offsets on gpiochip0:

    SPI:   /dev/spidev1.0   (SPI1-CE0 = GPIO18)
    BUSY:  GPIO24
    RESET: GPIO25
    DIO2 -> RF switch (configured on-chip)
    DIO3 -> TCXO power (configured on-chip)

Default LoRa parameters match the RNode firmware on-air format so the
radio can interoperate with an RNode peer: explicit header, CRC on,
sync word 0x1424. The TX preamble is 64 symbols (a 22-symbol preamble
is too short for the RNode's CSMA receiver to lock onto).
"""
import struct
import time

import lgpio
import spidev

# --- command opcodes ---
_SET_STANDBY = 0x80
_SET_PACKET_TYPE = 0x8A
_SET_RF_FREQ = 0x86
_SET_PA_CONFIG = 0x95
_SET_TX_PARAMS = 0x8E
_SET_MOD_PARAMS = 0x8B
_SET_PKT_PARAMS = 0x8C
_SET_BUF_BASE = 0x8F
_SET_TX = 0x83
_SET_RX = 0x82
_SET_DIO_IRQ = 0x08
_GET_IRQ = 0x12
_CLR_IRQ = 0x02
_GET_RXBUF = 0x13
_WRITE_BUF = 0x0E
_READ_BUF = 0x1E
_GET_PKT_STATUS = 0x14
_GET_RSSI_INST = 0x15
_GET_STATUS = 0xC0
_GET_ERRORS = 0x17
_CLR_ERRORS = 0x07
_CALIBRATE = 0x89
_SET_DIO3_TCXO = 0x97
_SET_DIO2_RF = 0x9D
_WRITE_REG = 0x0D
_READ_REG = 0x1D

# --- IRQ bits ---
IRQ_TXDONE = 0x0001
IRQ_RXDONE = 0x0002
IRQ_HDRVALID = 0x0010
IRQ_CRCERR = 0x0040
IRQ_TIMEOUT = 0x0200

# --- LoRa bandwidth code table (Hz -> register value) ---
_BW = {
    7800: 0x00, 10400: 0x08, 15600: 0x01, 20800: 0x09, 31250: 0x02,
    41700: 0x0A, 62500: 0x03, 125000: 0x04, 250000: 0x05, 500000: 0x06,
}

# --- TCXO control voltage codes for SetDIO3AsTCXOCtrl ---
_TCXO = {1.6: 0x00, 1.7: 0x01, 1.8: 0x02, 2.2: 0x03, 2.4: 0x04,
         2.7: 0x05, 3.0: 0x06, 3.3: 0x07}

_REG_SYNC_WORD = 0x0740
_REG_IQ_POLARITY = 0x0736
_REG_TX_CLAMP = 0x08D8      # erratum 15.2 (antenna mismatch)
_REG_RX_GAIN = 0x08AC       # LNA gain boost
_FXTAL = 32_000_000

CHIPMODE = {2: "STDBY_RC", 3: "STDBY_XOSC", 4: "FS", 5: "RX", 6: "TX"}


class SX1262:
    def __init__(self, spi_bus=1, spi_cs=0, busy=24, reset=25,
                 gpiochip=0, spi_hz=2_000_000):
        self.busy = busy
        self.reset_pin = reset
        self._h = lgpio.gpiochip_open(gpiochip)
        lgpio.gpio_claim_input(self._h, busy)
        lgpio.gpio_claim_output(self._h, reset, 1)
        self._spi = spidev.SpiDev()
        self._spi.open(spi_bus, spi_cs)
        self._spi.mode = 0
        self._spi.max_speed_hz = spi_hz

    # --- low level ---
    def _wait_busy(self, timeout=0.2):
        t0 = time.time()
        while lgpio.gpio_read(self._h, self.busy) == 1:
            if time.time() - t0 > timeout:
                return False
            time.sleep(0.00005)
        return True

    def cmd(self, data):
        self._wait_busy()
        return self._spi.xfer2(list(data))

    def reset(self):
        lgpio.gpio_write(self._h, self.reset_pin, 0)
        time.sleep(0.003)
        lgpio.gpio_write(self._h, self.reset_pin, 1)
        time.sleep(0.003)
        self._wait_busy()

    def write_reg(self, addr, vals):
        self.cmd([_WRITE_REG, (addr >> 8) & 0xFF, addr & 0xFF] + list(vals))

    def read_reg(self, addr, n):
        rx = self.cmd([_READ_REG, (addr >> 8) & 0xFF, addr & 0xFF, 0x00] + [0] * n)
        return rx[4:4 + n]

    def get_status(self):
        return self.cmd([_GET_STATUS, 0x00])[1]

    def get_device_errors(self):
        rx = self.cmd([_GET_ERRORS, 0, 0, 0])
        return (rx[2] << 8) | rx[3]

    # --- bring-up ---
    def begin(self, freq_hz=915_000_000, sf=8, bw_hz=125_000, cr_denom=5,
              preamble=64, sync=(0x14, 0x24), tcxo_voltage=1.8,
              tcxo_delay=0x000140, crc=True, explicit=True, ldro=None,
              tx_power=17):
        bw_code = _BW[bw_hz]
        cr_code = cr_denom - 4
        if ldro is None:
            ldro = 1 if (1 << sf) / bw_hz > 0.016 else 0
        self._sf, self._bw, self._cr, self._ldro = sf, bw_code, cr_code, ldro
        self._preamble, self._explicit, self._crc = preamble, explicit, crc
        self._sync = sync

        self.reset()
        self.cmd([_SET_STANDBY, 0x00])                              # STDBY_RC
        tv = _TCXO[tcxo_voltage]
        self.cmd([_SET_DIO3_TCXO, tv, (tcxo_delay >> 16) & 0xFF,
                  (tcxo_delay >> 8) & 0xFF, tcxo_delay & 0xFF])
        self.cmd([_CLR_ERRORS, 0, 0])
        self.cmd([_CALIBRATE, 0x7F])
        time.sleep(0.005)
        self._wait_busy()
        self.cmd([_SET_DIO2_RF, 0x01])                             # DIO2 -> RF switch
        self.cmd([_SET_PACKET_TYPE, 0x01])                        # LoRa
        fr = int(round(freq_hz * (1 << 25) / _FXTAL))
        self._fr = fr
        self.cmd([_SET_RF_FREQ, (fr >> 24) & 0xFF, (fr >> 16) & 0xFF,
                  (fr >> 8) & 0xFF, fr & 0xFF])
        # CalibrateImage for the operating band (902-928 MHz: 0xE1/0xE9). Must
        # run after SetRfFrequency; without it the TX chirps are malformed even
        # though RX tolerates it.
        self.cmd([0x98, 0xE1, 0xE9])
        self._wait_busy()
        self.cmd([_SET_BUF_BASE, 0x00, 0x00])
        self.cmd([_SET_MOD_PARAMS, sf, bw_code, cr_code, ldro])
        self._set_packet_params(0xFF)
        self.write_reg(_REG_SYNC_WORD, sync)
        # LNA gain boost, matching RNode firmware begin() (RX sensitivity).
        self.write_reg(_REG_RX_GAIN, [0x96])
        # erratum 15.2 "Better Resistance to Antenna Mismatch", as the RNode
        # firmware does in setTxPower().
        clamp = self.read_reg(_REG_TX_CLAMP, 1)[0]
        self.write_reg(_REG_TX_CLAMP, [clamp | 0x1E])
        # PA + TX power (SX1262 high-power PA)
        self.cmd([_SET_PA_CONFIG, 0x04, 0x07, 0x00, 0x01])
        self.cmd([_SET_TX_PARAMS, tx_power & 0xFF, 0x02])          # ramp 40us (match RNode)
        mask = IRQ_TXDONE | IRQ_RXDONE | IRQ_CRCERR | IRQ_HDRVALID | IRQ_TIMEOUT
        self.cmd([_SET_DIO_IRQ, (mask >> 8) & 0xFF, mask & 0xFF,
                  (mask >> 8) & 0xFF, mask & 0xFF, 0, 0, 0, 0])
        return self.get_device_errors()

    def _set_packet_params(self, payload_len):
        self.cmd([_SET_PKT_PARAMS, (self._preamble >> 8) & 0xFF,
                  self._preamble & 0xFF,
                  0x00 if self._explicit else 0x01,
                  payload_len & 0xFF,
                  0x01 if self._crc else 0x00, 0x00])     # invertIQ = standard
        # SX1262 erratum 15.4 (Optimizing the Inverted IQ Operation): for
        # standard (non-inverted) IQ, bit 2 of reg 0x0736 must be SET. The
        # POR default leaves it clear, which differs from the RNode firmware
        # (and every standard LoRa peer); without it the RNode will not
        # demodulate our frames. Apply after every SetPacketParams.
        iq = self.read_reg(_REG_IQ_POLARITY, 1)[0]
        self.write_reg(_REG_IQ_POLARITY, [iq | 0x04])

    # --- operation ---
    def standby(self):
        self.cmd([_SET_STANDBY, 0x00])

    def listen(self):
        self.cmd([_CLR_IRQ, 0xFF, 0xFF])
        self.cmd([_SET_RX, 0xFF, 0xFF, 0xFF])                     # continuous RX

    def rssi_inst(self):
        """Instantaneous wideband channel RSSI in dBm (only valid while in RX).

        Used for carrier sensing / CSMA. GetRssiInst returns rssiInst at SPI
        index 2 (opcode + status, then the value), like GetPacketStatus.
        """
        return -self.cmd([_GET_RSSI_INST, 0, 0])[2] / 2.0

    def poll_rx(self):
        """Return (payload, rssi_dbm, snr_db, crc_ok) if a packet arrived, else None.

        ``payload`` is the full on-air LoRa payload, i.e. the RNode 1-byte link
        header followed by the (possibly partial) frame. Stripping the header and
        reassembling split frames is the interface's job (see SX1262Interface).
        """
        rx = self.cmd([_GET_IRQ, 0, 0, 0])
        irq = (rx[2] << 8) | rx[3]
        if not irq:
            return None
        self.cmd([_CLR_IRQ, (irq >> 8) & 0xFF, irq & 0xFF])
        if not (irq & IRQ_RXDONE):
            return None
        rb = self.cmd([_GET_RXBUF, 0, 0, 0])
        plen, start = rb[2], rb[3]
        # With this command framing (opcode, offset, NOP, NOP, data...) the first
        # FIFO byte lands at SPI index 3; read the full plen-byte payload.
        raw = self.cmd([_READ_BUF, start, 0, 0] + [0] * plen)[3:3 + plen]
        ps = self.cmd([_GET_PKT_STATUS, 0, 0, 0, 0])
        rssi = -ps[2] / 2.0
        snr = struct.unpack("b", bytes([ps[3]]))[0] / 4.0
        return bytes(raw), rssi, snr, not bool(irq & IRQ_CRCERR)

    def transmit(self, data, timeout=5.0):
        """Send one LoRa packet. Returns True on TxDone."""
        data = bytes(data)
        self.cmd([_SET_STANDBY, 0x01])               # STDBY_XOSC (TCXO stays up)
        self.cmd([_CLR_IRQ, 0xFF, 0xFF])
        self._set_packet_params(len(data))
        self.cmd([_WRITE_BUF, 0x00] + list(data))
        self.cmd([_SET_TX, 0x00, 0x00, 0x00])                     # no timeout
        t0 = time.time()
        while time.time() - t0 < timeout:
            rx = self.cmd([_GET_IRQ, 0, 0, 0])
            irq = (rx[2] << 8) | rx[3]
            if irq & IRQ_TXDONE:
                self.cmd([_CLR_IRQ, 0xFF, 0xFF])
                return True
            if irq & IRQ_TIMEOUT:
                self.cmd([_CLR_IRQ, 0xFF, 0xFF])
                return False
            time.sleep(0.002)
        return False

    def close(self):
        try:
            self.standby()
        finally:
            self._spi.close()
            lgpio.gpiochip_close(self._h)
