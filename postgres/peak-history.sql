BEGIN;

-- 首次採集決定時效；重抓只更新 last_captured_at，不改變分母或原始資格。
CREATE OR REPLACE VIEW station_history AS
SELECT station_id, source_at, station_name, district,
       available_bikes, available_docks, is_active,
       first_captured_at, last_captured_at,
       is_active
           AND first_captured_at >= source_at
           AND first_captured_at <= source_at + interval '30 minutes' AS valid_sample,
       CASE
           WHEN NOT is_active THEN '停用（不計入比例）'
           WHEN first_captured_at < source_at THEN '來源時間晚於採集（不計入比例）'
           WHEN first_captured_at > source_at + interval '30 minutes' THEN '來源超過30分鐘（不計入比例）'
           ELSE '有效'
       END AS sample_status,
       CASE
           WHEN extract(isodow FROM source_at AT TIME ZONE 'Asia/Taipei') BETWEEN 1 AND 5 THEN
               CASE
                   WHEN (source_at AT TIME ZONE 'Asia/Taipei')::time >= time '07:00'
                    AND (source_at AT TIME ZONE 'Asia/Taipei')::time < time '09:00' THEN '早尖峰'
                   WHEN (source_at AT TIME ZONE 'Asia/Taipei')::time >= time '17:00'
                    AND (source_at AT TIME ZONE 'Asia/Taipei')::time < time '19:00' THEN '晚尖峰'
               END
       END AS peak
FROM station_observations;

GRANT SELECT ON station_history TO youbike_reader;

COMMIT;
