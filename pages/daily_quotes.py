import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

DAILY_QUOTES_PATH = Path(__file__).with_name("data") / "daily_quotes.json"
UNIX_EPOCH_DATE = date(1970, 1, 1)
_KET_PATTERN = re.compile(r"\|[01]+⟩")


class DailyQuoteDataError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class QuoteDisplayPart:
    text: str
    is_ket: bool = False


@dataclass(frozen=True, slots=True)
class DailyQuote:
    quote_original: str
    quote_display: str
    speaker: str
    speaker_kind: str
    work: str | None
    year: int | None
    source_url: str

    @property
    def display_parts(self) -> tuple[QuoteDisplayPart, ...]:
        return quote_display_parts(self.quote_display)


@dataclass(frozen=True, slots=True)
class ScheduledQuote:
    relative_day: int
    collection_index: int
    quote: DailyQuote

    @property
    def is_current(self) -> bool:
        return self.relative_day == 0

    @property
    def relative_label(self) -> str:
        if self.is_current:
            return "Current"
        unit = "day" if abs(self.relative_day) == 1 else "days"
        return f"{self.relative_day:+d} {unit}"


@lru_cache(maxsize=1)
def load_daily_quotes() -> tuple[DailyQuote, ...]:
    try:
        payload = json.loads(DAILY_QUOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DailyQuoteDataError(
            f"Cannot load {DAILY_QUOTES_PATH}: {error}"
        ) from error

    if not isinstance(payload, list) or not payload:
        raise DailyQuoteDataError(
            "The daily quote collection must be a non-empty list."
        )

    quotes = tuple(_parse_quote(item, index) for index, item in enumerate(payload))
    identities = {(item.quote_original, item.speaker, item.work) for item in quotes}
    if len(identities) != len(quotes):
        raise DailyQuoteDataError("The daily quote collection contains duplicates.")
    return quotes


def quote_index_for_date(day: date, day_offset: int = 0) -> int:
    quotes = load_daily_quotes()
    epoch_day = (day - UNIX_EPOCH_DATE).days
    return (epoch_day + day_offset) % len(quotes)


def quote_for_date(day: date, day_offset: int = 0) -> DailyQuote:
    quotes = load_daily_quotes()
    return quotes[quote_index_for_date(day, day_offset)]


def quote_window_for_date(
    day: date,
    day_offset: int = 0,
    *,
    previous: int = 3,
    following: int = 5,
) -> tuple[ScheduledQuote, ...]:
    quotes = load_daily_quotes()
    current_index = quote_index_for_date(day, day_offset)
    return tuple(
        ScheduledQuote(
            relative_day=relative_day,
            collection_index=(current_index + relative_day) % len(quotes),
            quote=quotes[(current_index + relative_day) % len(quotes)],
        )
        for relative_day in range(-previous, following + 1)
    )


def quote_display_parts(display_quote: str) -> tuple[QuoteDisplayPart, ...]:
    parts = []
    cursor = 0
    for match in _KET_PATTERN.finditer(display_quote):
        if match.start() > cursor:
            parts.append(QuoteDisplayPart(display_quote[cursor : match.start()]))
        parts.append(QuoteDisplayPart(text=match.group(), is_ket=True))
        cursor = match.end()
    if cursor < len(display_quote):
        parts.append(QuoteDisplayPart(display_quote[cursor:]))
    return tuple(parts) or (QuoteDisplayPart(""),)


def _parse_quote(item, index: int) -> DailyQuote:
    if not isinstance(item, dict):
        raise DailyQuoteDataError(f"Quote {index} must be an object.")

    values = {}
    for field in ("quote_original", "quote_display", "speaker", "source_url"):
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise DailyQuoteDataError(f"Quote {index} has an invalid {field}.")
        values[field] = value.strip()

    speaker_kind = item.get("speaker_kind")
    if speaker_kind not in {"character", "person"}:
        raise DailyQuoteDataError(f"Quote {index} has an invalid speaker_kind.")

    work = item.get("work")
    if work is not None and (not isinstance(work, str) or not work.strip()):
        raise DailyQuoteDataError(f"Quote {index} has an invalid work.")

    year = item.get("year")
    if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
        raise DailyQuoteDataError(f"Quote {index} has an invalid year.")

    parsed_source = urlparse(values["source_url"])
    if parsed_source.scheme not in {"http", "https"} or not parsed_source.netloc:
        raise DailyQuoteDataError(f"Quote {index} has an invalid source_url.")

    return DailyQuote(
        speaker_kind=speaker_kind,
        work=work.strip() if work else None,
        year=year,
        **values,
    )
