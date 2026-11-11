// Generic LoRaWAN uplink decoder for the 12-byte airq payload (layout in airq/payload.py).
//
// Follows the common decodeUplink(input) convention used by The Things Stack
// and ChirpStack: input.bytes is an array of byte values, the result is
// { data, warnings, errors }. Unknown values are returned as null.

function decodeUplink(input) {
  const bytes = input.bytes;
  if (!bytes || bytes.length !== 12) {
    return { data: {}, warnings: [], errors: ["expected a 12-byte payload"] };
  }

  const u16 = (i) => (bytes[i] << 8) | bytes[i + 1];
  const i16 = (i) => {
    const v = u16(i);
    return v & 0x8000 ? v - 0x10000 : v;
  };
  const round = (value, digits) => Number(value.toFixed(digits));

  const temperature = i16(0);
  const humidity = u16(2);
  const co2 = u16(4);
  const pm25 = u16(6);
  const pm10 = u16(8);
  const voc = bytes[10];
  const nox = bytes[11];

  return {
    data: {
      temperature: temperature === 0x7fff ? null : round(temperature / 100, 2),
      humidity: humidity === 0xffff ? null : round(humidity / 100, 2),
      co2: co2 === 0xffff ? null : co2,
      pm2_5: pm25 === 0xffff ? null : round(pm25 / 10, 1),
      pm10: pm10 === 0xffff ? null : round(pm10 / 10, 1),
      vocIndex: voc === 0xff ? null : voc * 2,
      noxIndex: nox === 0xff ? null : nox * 2,
    },
    warnings: [],
    errors: [],
  };
}

// Allow `require()` from the node test; the decoder itself stays a plain global function.
if (typeof module !== "undefined") {
  module.exports = { decodeUplink };
}
