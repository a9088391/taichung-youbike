\getenv collector_password YOUBIKE_COLLECTOR_PASSWORD
\getenv reader_password YOUBIKE_READER_PASSWORD

BEGIN;

CREATE ROLE youbike_collector LOGIN PASSWORD :'collector_password';
CREATE ROLE youbike_reader LOGIN PASSWORD :'reader_password';

REVOKE CONNECT, TEMPORARY ON DATABASE youbike FROM PUBLIC;
GRANT CONNECT ON DATABASE youbike TO youbike_collector, youbike_reader;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE TABLE station_observations (
    station_id text NOT NULL,
    source_at timestamptz NOT NULL,
    station_name text NOT NULL,
    district text NOT NULL,
    latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    capacity integer NOT NULL CHECK (capacity >= 0),
    available_bikes integer NOT NULL CHECK (available_bikes BETWEEN 0 AND capacity),
    available_docks integer NOT NULL CHECK (available_docks BETWEEN 0 AND capacity),
    is_active boolean NOT NULL,
    first_captured_at timestamptz NOT NULL,
    last_captured_at timestamptz NOT NULL CHECK (last_captured_at >= first_captured_at),
    PRIMARY KEY (station_id, source_at)
);

CREATE INDEX station_observations_last_capture_idx ON station_observations (last_captured_at);

CREATE TABLE collection_status (
    singleton boolean PRIMARY KEY CHECK (singleton),
    last_attempt_at timestamptz,
    last_success_at timestamptz,
    error_kind text CHECK (error_kind IN ('fetch', 'invalid-data', 'storage'))
);

INSERT INTO collection_status (singleton) VALUES (true);

-- 這個時間戳與同一批站點在一筆交易內更新，讀者只會看到一份完整快照。
CREATE VIEW current_stations AS
SELECT observations.station_id, observations.station_name, observations.district,
       observations.latitude, observations.longitude, observations.capacity,
       observations.available_bikes, observations.available_docks,
       observations.is_active, observations.source_at
FROM station_observations AS observations
JOIN collection_status AS status
    ON status.last_success_at = observations.last_captured_at;

GRANT SELECT, INSERT, UPDATE (last_captured_at) ON station_observations TO youbike_collector;
GRANT SELECT, UPDATE (last_attempt_at, last_success_at, error_kind) ON collection_status TO youbike_collector;
GRANT SELECT ON current_stations, collection_status TO youbike_reader;

COMMIT;
