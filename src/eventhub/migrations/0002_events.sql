CREATE TABLE events (
    id          BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
    occurred_at DATETIME(3)      NOT NULL,
    source      VARCHAR(64)      NOT NULL,
    event_id    BINARY(16)       NOT NULL,
    severity    TINYINT UNSIGNED NOT NULL,
    message     VARCHAR(1000)    NOT NULL,
    ingested_by BIGINT UNSIGNED  NULL,
    PRIMARY KEY (id, occurred_at),
    UNIQUE KEY uq_events_dedupe (source, event_id, occurred_at),
    KEY idx_events_source_time (source, occurred_at),
    CONSTRAINT chk_events_severity CHECK (severity <= 7)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
PARTITION BY RANGE COLUMNS (occurred_at) (
    PARTITION p2026_11 VALUES LESS THAN ('2026-12-01'),
    PARTITION p2026_12 VALUES LESS THAN ('2027-01-01'),
    PARTITION p2027_01 VALUES LESS THAN ('2027-02-01'),
    PARTITION pmax     VALUES LESS THAN (MAXVALUE)
)
