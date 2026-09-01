(() => {
  "use strict";

  const PROFILES = Object.freeze({
    default: Object.freeze({ significantDigits: 4, below: -2, from: 4, group: true }),
    count: Object.freeze({ significantDigits: 4, below: -99, from: 6, group: true }),
    probability: Object.freeze({ significantDigits: 3, below: -2, from: 4, group: true }),
    duration: Object.freeze({ significantDigits: 4, below: -2, from: 4, group: true }),
    score: Object.freeze({ significantDigits: 4, below: -2, from: 4, group: true }),
  });
  const SUPERSCRIPTS = Object.freeze({
    "-": "⁻", "+": "⁺", 0: "⁰", 1: "¹", 2: "²", 3: "³",
    4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹",
  });

  const trimDecimal = (value) => (
    value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value
  );
  const superscript = (value) => String(value).split("")
    .map((character) => SUPERSCRIPTS[character] || character).join("");
  const groupThousands = (value) => {
    const match = String(value).match(/^([+-]?)(\d+)(\.\d+)?$/);
    if (!match) return String(value);
    return `${match[1]}${Number(match[2]).toLocaleString("en-GB")}${match[3] || ""}`;
  };

  const describe = (
    value,
    { profile = "default", significantDigits = null, unit = null } = {},
  ) => {
    const number = Number(value);
    const raw = String(value);
    if (!Number.isFinite(number)) {
      return Object.freeze({
        raw, text: raw, accessibleText: raw, scientific: false, mantissa: null,
        exponent: null, exponentText: null, unit, validNumber: false,
      });
    }
    const policy = PROFILES[profile] || PROFILES.default;
    const digits = Math.max(1, Math.floor(significantDigits || policy.significantDigits));
    if (number === 0) {
      return Object.freeze({
        raw, text: "0", accessibleText: "0", scientific: false, mantissa: null,
        exponent: null, exponentText: null, unit, validNumber: true,
      });
    }

    let exponent = Math.floor(Math.log10(Math.abs(number)));
    if (exponent <= policy.below || exponent >= policy.from) {
      let mantissa = number / (10 ** exponent);
      let rendered = trimDecimal(mantissa.toFixed(digits - 1));
      if (Math.abs(Number(rendered)) >= 10) {
        exponent += 1;
        mantissa = Number(rendered) / 10;
        rendered = trimDecimal(mantissa.toFixed(digits - 1));
      }
      const exponentText = superscript(exponent);
      return Object.freeze({
        raw,
        text: `${rendered}\u2009·\u200910${exponentText}`,
        accessibleText: `${rendered} times ten to the power of ${exponent}`,
        scientific: true,
        mantissa: rendered,
        exponent,
        exponentText,
        unit,
        validNumber: true,
      });
    }

    const decimalPlaces = Math.max(0, digits - exponent - 1);
    let rendered = trimDecimal(number.toFixed(decimalPlaces));
    if (policy.group) rendered = groupThousands(rendered);
    return Object.freeze({
      raw, text: rendered, accessibleText: rendered, scientific: false,
      mantissa: null, exponent: null, exponentText: null, unit, validNumber: true,
    });
  };

  const format = (value, options = {}) => describe(value, options).text;
  const formatRange = (
    minimum,
    maximum,
    {
      emptyLabel = null,
      minimumFallback = "0",
      maximumFallback = "∞",
      significantDigits = null,
      profile = "default",
    } = {},
  ) => {
    const minimumMissing = minimum === null || minimum === undefined
      || String(minimum).trim() === "";
    const maximumMissing = maximum === null || maximum === undefined
      || String(maximum).trim() === "";
    if (minimumMissing && maximumMissing && emptyLabel !== null) return emptyLabel;
    const options = { significantDigits, profile };
    return `${minimumMissing ? minimumFallback : format(minimum, options)}–${
      maximumMissing ? maximumFallback : format(maximum, options)}`;
  };

  globalThis.CircuitBenchNumber = Object.freeze({ describe, format, formatRange, PROFILES });
})();
