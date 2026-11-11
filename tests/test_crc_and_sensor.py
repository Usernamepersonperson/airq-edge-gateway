import math

import pytest
from sensirion_i2c_driver import I2cConnection
from sensirion_i2c_driver.errors import I2cChecksumError
from sensirion_i2c_sen5x import Sen5xI2cDevice

from airq.crc import add_crcs, crc8
from airq.mock_i2c import PM_ADDR, MockI2cTransceiver
from airq.sensor import AirQualitySensor, open_sensor


def test_crc8_documented_example():
    assert crc8(bytes([0xBE, 0xEF])) == 0x92


def test_crc8_matches_driver_calculator():
    from sensirion_i2c_driver import CrcCalculator

    ref = CrcCalculator(8, 0x31, 0xFF, 0x00)
    for word in (b"\x00\x00", b"\x12\x34", b"\xff\xff", b"\x03\xc4"):
        assert crc8(word) == ref(word)


def test_add_crcs_layout():
    assert add_crcs(b"\xbe\xef\x00\x00") == bytes([0xBE, 0xEF, 0x92, 0x00, 0x00, crc8(b"\0\0")])
    with pytest.raises(ValueError):
        add_crcs(b"\x01")


def test_real_pm_driver_reads_mock_bus():
    mock = MockI2cTransceiver(seed=3)
    dev = Sen5xI2cDevice(I2cConnection(mock))  # vendor driver code, unmodified
    assert dev.get_product_name() == "MOCK-PM-SENSOR"
    dev.start_measurement()
    assert dev.read_data_ready() is True
    v = dev.read_measured_values()
    assert 0 < v.mass_concentration_2p5.physical < 60
    assert 15 < v.ambient_temperature.degrees_celsius < 30
    assert 20 < v.ambient_humidity.percent_rh < 80
    assert 1 <= v.voc_index.scaled <= 500
    assert (PM_ADDR, 0x03C4) in mock.log  # driver really issued Read Measured Values


def test_driver_reports_unavailable_before_start():
    dev = Sen5xI2cDevice(I2cConnection(MockI2cTransceiver()))
    v = dev.read_measured_values()
    assert not v.mass_concentration_2p5.available
    assert math.isnan(v.ambient_temperature.degrees_celsius)


def test_driver_rejects_corrupt_crc():
    class Corrupt(MockI2cTransceiver):
        def transceive(self, *a, **k):
            status, err, data = super().transceive(*a, **k)
            if len(data) == 24:
                data = data[:-1] + bytes([data[-1] ^ 0x01])
            return status, err, data

    dev = Sen5xI2cDevice(I2cConnection(Corrupt()))
    dev.start_measurement()
    with pytest.raises(I2cChecksumError):
        dev.read_measured_values()


def test_airq_sensor_wrapper_full_reading():
    sensor = open_sensor("mock")
    assert sensor.start() == "MOCK-PM-SENSOR"
    r = sensor.read(ts=1000.0)
    sensor.stop()
    assert r.ts == 1000.0
    assert r.co2_ppm is not None and 400 < r.co2_ppm < 2000
    assert r.pm2_5 is not None and r.pm10 is not None and r.pm10 > r.pm2_5


def test_without_co2_leaves_none():
    sensor = AirQualitySensor(MockI2cTransceiver(), with_co2=False)
    assert sensor.read().co2_ppm is None


def test_unknown_backend():
    with pytest.raises(ValueError):
        open_sensor("serial")
