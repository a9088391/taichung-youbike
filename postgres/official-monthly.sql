BEGIN;

-- 官方月報是獨立快照，不由站點觀測推算；月份固定以月初日期識別。
CREATE TABLE IF NOT EXISTS official_monthly_rentals (
    month date PRIMARY KEY CHECK (extract(day FROM month) = 1),
    rentals bigint NOT NULL CHECK (rentals >= 0),
    source_url text NOT NULL,
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    verified_on date NOT NULL
);

INSERT INTO official_monthly_rentals (month, rentals, source_url, source_sha256, verified_on)
VALUES
    ('2025-02-01', 1445084, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=f449e21f-b005-48bd-a5cc-d0207bf2dcc6', 'beb4bc8eda01969809a0b0e9a1f8184b27173bd5d8daca8e06873421f92782a1', '2026-11-24'),
    ('2025-03-01', 1696251, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=19c28bce-8a36-435c-9715-1bafa83c4a75', '19b7f212007d39d3231378864f2771b0289a0b54c31e33ae5d4b92c906c68578', '2026-11-24'),
    ('2025-04-01', 1787729, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=e953cc67-dab0-4d26-b5ea-4c78fc3dffab', '753e1e6903c5cdc81f8d8f11f554738b49e84087bf088a6746f8a69cadd00e0a', '2026-11-24'),
    ('2025-05-01', 1774931, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=9f96950e-53f2-4de7-a013-caf3a5ead927', 'aaf3ba6f2a50a2b80444fccf7bcf7bac999ddcc3b0c535b8efd5d77052b84ffa', '2026-11-24'),
    ('2025-06-01', 1677937, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=c94c3611-8edb-4c10-a227-d5be82083edc', 'ab9f4e1ae8a7efd1fe055547c1b41d70a5d3163529c54e41e5a0891a484ff0da', '2026-11-24'),
    ('2025-07-01', 1450558, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=81d1a780-6fa1-4df1-a2cb-fae5c50e22b9', '83bc9965c73738b9291e0ab3423c15635a09327cd8a1419f1f67fa3e67051cc2', '2026-11-24'),
    ('2025-08-01', 1646268, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=089413c7-ae0f-44dc-b22f-fba219cf05f8', '33605c46c1858f2a3c42a00a3235ab2b93ef6040e9c18eda69aff01d726f577c', '2026-11-24'),
    ('2025-09-01', 1743968, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=711f161b-4b5f-4375-b374-aa57dec966a3', '05d55c6bfef5c2ddba7344417ee76325c9fa742d997bfb7011b1bb07ac460301', '2026-11-24'),
    ('2025-11-01', 1842407, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=ee4f2f81-704b-43ac-979f-3fcddcde1064', '2abdce81c3fc50434bdfbc94990c8858752cb203c285397873c9ce74c0619509', '2026-11-24'),
    ('2025-12-01', 1974108, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=06d81eb2-0279-4c37-abad-d061e827543b', 'be1cc63e669b14e647c0ca59424231ede109a2757b541a92e626bc7dc0d94cf7', '2026-11-24'),
    ('2026-02-01', 1556657, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=57755b8a-7a85-4695-a1e3-36c7a562c5b4', '1112fabe5262bce4e907fe244c7de13136bffabf4c67c8b572eaa3e2f7473aa4', '2026-11-24'),
    ('2026-03-01', 2016946, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=1102a497-48bc-49d1-9dfb-ff8f1afff77c', '42368db2ffb69d9b0e4a4ded260d93c72d74f516111d87c20820b2eda4934875', '2026-11-24'),
    ('2026-04-01', 1950549, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=76e8cf3c-105c-498b-9ac0-4d09963cea6f', '037c99f643d1afbd20c9855f99ac2c10c6c241d90db63e61d6cb1f8fd9886b1b', '2026-11-24'),
    ('2026-05-01', 2184936, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=ffc42638-bdff-43b1-9273-41689414c6de', '67d7a35ad57ec77099def05ab48ecaf04a7b9ab4daa69d081f4cb2e62b80e86b', '2026-11-24'),
    ('2026-06-01', 1771488, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=a7c93be0-8479-4781-a07c-ad3bc506488d', '15078c877bbc2333243fbbb57c12755a6feca57d0f7ecc73652de1e08bf0224d', '2026-11-24'),
    ('2026-07-01', 1924488, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=d3be46ed-2132-4fa0-8e2d-18c78a1030c6', '2dd4217a6f161ec33994ccf3e2c5b0f08495a3fba77a40d6e419af7e031986cc', '2026-11-24'),
    ('2026-08-01', 1833849, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=9a786cbe-8ee0-4ead-ab69-425cc0e7d723', 'faec12721f304bb6f9e6832e3e7e56458d5dd7290a65fd5ab457f93293187d0f', '2026-11-24'),
    ('2026-09-01', 2091631, 'https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=bac0bb6f-6326-477f-a24c-d508b5f99775', '992b91203cee59afd32f1ac1b14d3bb7b80a0072322b6f97b2f7a49cd4c5162d', '2026-11-24')
ON CONFLICT (month) DO UPDATE SET
    rentals = EXCLUDED.rentals,
    source_url = EXCLUDED.source_url,
    source_sha256 = EXCLUDED.source_sha256,
    verified_on = EXCLUDED.verified_on;

GRANT SELECT ON official_monthly_rentals TO youbike_reader;

COMMIT;
