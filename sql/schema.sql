-- ============================================================
-- MCP Azure System — Database Schema
-- Azure SQL Database: pm-history
-- Run once during initial setup (Step 5 of Production Path)
-- ============================================================

-- ── Users / Roles ────────────────────────────────────────────
CREATE TABLE app_users (
    user_id       NVARCHAR(128)  NOT NULL PRIMARY KEY,   -- Azure AD OID
    email         NVARCHAR(256)  NOT NULL UNIQUE,
    display_name  NVARCHAR(256)  NOT NULL,
    role          NVARCHAR(64)   NOT NULL DEFAULT 'Technician',
    is_active     BIT            NOT NULL DEFAULT 1,
    created_at    DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
    last_login    DATETIME2      NULL,
    CONSTRAINT chk_role CHECK (role IN ('Technician','Engineer','Manager','Admin'))
);

-- ── Machines ─────────────────────────────────────────────────
CREATE TABLE machines (
    machine_id    NVARCHAR(64)   NOT NULL PRIMARY KEY,
    name          NVARCHAR(256)  NOT NULL,
    location      NVARCHAR(256)  NOT NULL,
    asset_tag     NVARCHAR(64)   NULL,
    status        NVARCHAR(32)   NOT NULL DEFAULT 'active',
    last_pm_date  DATETIME2      NULL,
    next_pm_date  DATETIME2      NULL,
    created_at    DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT chk_machine_status CHECK (status IN ('active','inactive','decommissioned'))
);

-- ── PM Records ───────────────────────────────────────────────
-- Records are INSERT-only — no DELETE permission granted to app role
CREATE TABLE pm_records (
    id             INT            NOT NULL IDENTITY(1,1) PRIMARY KEY,
    machine_id     NVARCHAR(64)   NOT NULL REFERENCES machines(machine_id),
    work_order     NVARCHAR(64)   NOT NULL UNIQUE,
    technician_id  NVARCHAR(128)  NOT NULL REFERENCES app_users(user_id),
    description    NVARCHAR(MAX)  NOT NULL,
    status         NVARCHAR(32)   NOT NULL DEFAULT 'open',
    scheduled_date DATETIME2      NOT NULL,
    completed_date DATETIME2      NULL,
    notes          NVARCHAR(MAX)  NULL,
    created_by     NVARCHAR(256)  NOT NULL,
    created_at     DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at     DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT chk_pm_status CHECK (status IN ('open','in_progress','completed','overdue'))
);

CREATE INDEX idx_pm_machine   ON pm_records(machine_id);
CREATE INDEX idx_pm_status    ON pm_records(status);
CREATE INDEX idx_pm_scheduled ON pm_records(scheduled_date);

-- ── Audit Logs — immutable, INSERT-only ──────────────────────
CREATE TABLE audit_logs (
    audit_id       NVARCHAR(36)   NOT NULL PRIMARY KEY,   -- UUID
    correlation_id NVARCHAR(36)   NOT NULL,
    who            NVARCHAR(256)  NOT NULL,
    event_time     NVARCHAR(32)   NOT NULL,               -- ISO 8601
    what           NVARCHAR(512)  NOT NULL,
    status_code    INT            NOT NULL,
    latency_ms     FLOAT          NOT NULL,
    ip_address     NVARCHAR(64)   NOT NULL,
    user_agent     NVARCHAR(512)  NULL
);

CREATE INDEX idx_audit_who  ON audit_logs(who);
CREATE INDEX idx_audit_time ON audit_logs(event_time);

-- ── Seed data — dev user (matches DEV_BYPASS_AUTH mock user) ────
INSERT INTO app_users (user_id, email, display_name, role)
VALUES ('00000000-0000-0000-0000-000000000001', 'dev@local', 'Local Dev User', 'Engineer');

-- ── Seed data — example machines ─────────────────────────────
INSERT INTO machines (machine_id, name, location, asset_tag, status)
VALUES
    ('M001', 'Compressor Unit A',   'Building 1 - Floor 1', 'AT-0001', 'active'),
    ('M002', 'Hydraulic Press #3',  'Building 2 - Floor 2', 'AT-0002', 'active'),
    ('M003', 'CNC Lathe 5-Axis',    'Workshop C',           'AT-0003', 'active'),
    ('M004', 'Cooling Tower B',     'Rooftop',              'AT-0004', 'active');

-- ── App DB user — minimum required permissions ────────────────
-- Run as DBO after schema creation:
-- CREATE USER [pm-app-user] WITH PASSWORD = '<from Key Vault>';
-- GRANT SELECT, INSERT, UPDATE ON pm_records   TO [pm-app-user];
-- GRANT SELECT, INSERT         ON audit_logs   TO [pm-app-user];   -- NO DELETE
-- GRANT SELECT                 ON machines     TO [pm-app-user];
-- GRANT SELECT                 ON app_users    TO [pm-app-user];
