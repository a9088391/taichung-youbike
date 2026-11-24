import argparse
import json
import logging
import math
import re
import signal
import sys
import time
from dataclasses import astuple, dataclass
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from urllib.error import URLError
from urllib.request import urlopen


SOURCE_URL = "https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=bf0fee92-9980-418c-a095-2eacf2eb49f6"
TAIWAN_TIME = timezone(timedelta(hours=8))
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024
LOGGER = logging.getLogger("collector")


class InvalidData(ValueError):
    pass


class FetchError(Exception):
    pass


class StorageError(Exception):
    pass


@dataclass(frozen=True)
class Observation:
    station_id: str
    source_at: datetime
    station_name: str
    district: str
    latitude: float
    longitude: float
    capacity: int
    available_bikes: int
    available_docks: int
    is_active: bool


def fetch_snapshot(source_url):
    try:
        with urlopen(source_url, timeout=30) as response:
            length_header = response.headers.get("Content-Length")
            expected_length = int(length_header) if length_header is not None else None
            payload = response.read(MAX_PAYLOAD_BYTES + 1)
    except (URLError, OSError, HTTPException, ValueError) as error:
        raise FetchError("source request failed") from error
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise InvalidData("payload too large")
    if expected_length is not None and len(payload) != expected_length:
        raise FetchError("incomplete source response")
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise InvalidData("invalid JSON") from error
    if not isinstance(data, list) or not data:
        raise InvalidData("expected nonempty station array")
    rows = []
    ids = set()
    for item in data:
        if not isinstance(item, dict):
            raise InvalidData("expected station object")
        fields = {}
        for key in ("sno", "sna", "sarea", "lat", "lng", "tot", "sbi", "bemp", "act", "mday"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise InvalidData("missing or invalid station field")
            try:
                value.encode("utf-8")
            except UnicodeError as error:
                raise InvalidData("invalid station text") from error
            fields[key] = value.strip()
        if fields["sno"] in ids:
            raise InvalidData("duplicate station id")
        ids.add(fields["sno"])
        try:
            latitude, longitude = float(fields["lat"]), float(fields["lng"])
            if not (math.isfinite(latitude) and -90 <= latitude <= 90
                    and math.isfinite(longitude) and -180 <= longitude <= 180):
                raise ValueError("invalid coordinates")
            counts = []
            for key in ("tot", "sbi", "bemp"):
                if not re.fullmatch(r"[0-9]{1,10}", fields[key]):
                    raise ValueError("invalid count")
                counts.append(int(fields[key]))
            capacity, bikes, docks = counts
            if capacity > 2147483647 or bikes > capacity or docks > capacity:
                raise ValueError("invalid capacity")
            if fields["act"] not in ("0", "1"):
                raise ValueError("invalid activity")
            if not re.fullmatch(r"[0-9]{14}", fields["mday"]):
                raise ValueError("invalid source timestamp")
            source_at = datetime.strptime(fields["mday"], "%Y%m%d%H%M%S").replace(tzinfo=TAIWAN_TIME)
        except ValueError as error:
            raise InvalidData("invalid station values") from error
        rows.append(Observation(fields["sno"], source_at, fields["sna"], fields["sarea"],
                                latitude, longitude, capacity, bikes, docks, fields["act"] == "1"))
    return rows


def _accept_attempt(cursor, attempt_at):
    cursor.execute("SELECT last_attempt_at FROM collection_status WHERE singleton = true FOR UPDATE")
    status = cursor.fetchone()
    if status is None:
        raise StorageError("collection status is not initialized")
    return status[0] is None or attempt_at > status[0]


def persist_success(rows, attempt_at, capture_at):
    import psycopg

    with psycopg.connect(connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            # 同一鎖涵蓋快照與狀態，避免較舊的延遲請求覆蓋新結果。
            if not _accept_attempt(cursor, attempt_at):
                return False
            cursor.executemany("""
                INSERT INTO station_observations (
                    station_id, source_at, station_name, district, latitude, longitude,
                    capacity, available_bikes, available_docks, is_active,
                    first_captured_at, last_captured_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (station_id, source_at) DO UPDATE SET
                    last_captured_at = EXCLUDED.last_captured_at
                """, [astuple(row) + (capture_at, capture_at) for row in rows])
            cursor.execute("""
                UPDATE collection_status
                SET last_attempt_at = %s, last_success_at = %s, error_kind = NULL
                WHERE singleton = true
                """, (attempt_at, capture_at))
    return True


def persist_failure(attempt_at, error_kind):
    import psycopg

    if error_kind not in ("fetch", "invalid-data", "storage"):
        raise ValueError("unsupported error kind")
    with psycopg.connect(connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            if not _accept_attempt(cursor, attempt_at):
                return False
            cursor.execute("""
                UPDATE collection_status SET last_attempt_at = %s, error_kind = %s
                WHERE singleton = true
                """, (attempt_at, error_kind))
    return True


def collect_once(source_url):
    import psycopg

    attempt_at = datetime.now(timezone.utc)
    try:
        rows = fetch_snapshot(source_url)
    except FetchError:
        error_kind = "fetch"
    except InvalidData:
        error_kind = "invalid-data"
    else:
        capture_at = datetime.now(timezone.utc)
        try:
            accepted = persist_success(rows, attempt_at, capture_at)
        except (psycopg.Error, StorageError):
            error_kind = "storage"
        else:
            if accepted:
                LOGGER.info("collection succeeded stations=%d", len(rows))
            else:
                LOGGER.warning("collection superseded")
            return accepted
    # 僅記錄固定分類，避免來源本文或資料庫連線資訊進入日誌。
    LOGGER.warning("collection failed kind=%s", error_kind)
    try:
        persist_failure(attempt_at, error_kind)
    except (psycopg.Error, StorageError):
        LOGGER.warning("collection status unavailable kind=storage")
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect Taichung YouBike station observations")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--source-url", help="isolated HTTP fixture URL; requires --once")
    args = parser.parse_args(argv)
    if args.source_url is not None and not args.once:
        parser.error("--source-url requires --once")
    source_url = args.source_url if args.source_url is not None else SOURCE_URL
    if args.once:
        return 0 if collect_once(source_url) else 1
    try:
        while True:
            collect_once(source_url)
            time.sleep(600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    sys.exit(main())
