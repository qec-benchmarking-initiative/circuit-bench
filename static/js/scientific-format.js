(() => {
  "use strict";

  const trimDecimal = (value) => (
    value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value
  );

  const format = (value, { significantDigits = 4 } = {}) => {
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    if (number === 0) return "0";

    const digits = Math.max(1, Math.floor(significantDigits));
    let exponent = Math.floor(Math.log10(Math.abs(number)));
    if (exponent <= -2 || exponent >= 4) {
      let mantissa = number / (10 ** exponent);
      let rendered = trimDecimal(mantissa.toFixed(digits - 1));
      if (Math.abs(Number(rendered)) >= 10) {
        exponent += 1;
        mantissa = Number(rendered) / 10;
        rendered = trimDecimal(mantissa.toFixed(digits - 1));
      }
      return `${rendered}e${exponent}`;
    }

    const decimalPlaces = Math.max(0, digits - exponent - 1);
    return trimDecimal(number.toFixed(decimalPlaces));
  };

  const formatRange = (
    minimum,
    maximum,
    {
      emptyLabel = null,
      minimumFallback = "0",
      maximumFallback = "∞",
      significantDigits = 4,
    } = {},
  ) => {
    const minimumMissing = minimum === null || minimum === undefined
      || String(minimum).trim() === "";
    const maximumMissing = maximum === null || maximum === undefined
      || String(maximum).trim() === "";
    if (minimumMissing && maximumMissing && emptyLabel !== null) return emptyLabel;
    return `${minimumMissing
      ? minimumFallback
      : format(minimum, { significantDigits })}–${maximumMissing
      ? maximumFallback
      : format(maximum, { significantDigits })}`;
  };

  globalThis.CircuitBenchNumber = Object.freeze({ format, formatRange });
})();
