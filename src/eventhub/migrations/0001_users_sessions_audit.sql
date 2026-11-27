CREATE TABLE users (
    id                   BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
    username             VARCHAR(64)       NOT NULL,
    password_hash        VARCHAR(255)      NOT NULL,
    role                 ENUM('admin', 'ingest', 'reporter') NOT NULL,
    is_active            TINYINT(1)        NOT NULL DEFAULT 1,
    must_change_password TINYINT(1)        NOT NULL DEFAULT 1,
    failed_logins        SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    locked_until         DATETIME          NULL,
    created_at           TIMESTAMP         NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP         NOT NULL DEFAULT CURRENT_TIMESTAMP
                                           ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_username (username),
    KEY idx_users_role_active (role, is_active)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
-- split
CREATE TABLE sessions (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id    BIGINT UNSIGNED NOT NULL,
    token_hash BINARY(32)      NOT NULL,
    created_at TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME        NOT NULL,
    revoked_at DATETIME        NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_sessions_token_hash (token_hash),
    KEY idx_sessions_user (user_id),
    KEY idx_sessions_expires (expires_at),
    CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
-- split
CREATE TABLE audit_log (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    occurred_at   TIMESTAMP(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    actor_user_id BIGINT UNSIGNED NULL,
    action        VARCHAR(64)     NOT NULL,
    target        VARCHAR(128)    NULL,
    detail        VARCHAR(500)    NULL,
    client_ip     VARCHAR(45)     NULL,
    PRIMARY KEY (id),
    KEY idx_audit_time (occurred_at),
    KEY idx_audit_actor (actor_user_id, occurred_at),
    CONSTRAINT fk_audit_actor FOREIGN KEY (actor_user_id) REFERENCES users (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
