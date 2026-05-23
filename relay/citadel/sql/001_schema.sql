---
name: init_schema
description: Creates the Citadel tables and FTS index if they do not exist.
run_on_startup: true
---
CREATE TABLE IF NOT EXISTS rooms (
    name       TEXT PRIMARY KEY,
    tags       TEXT NOT NULL DEFAULT '[]',
    aliases    TEXT NOT NULL DEFAULT '[]',
    created_on TEXT NOT NULL,
    updated_on TEXT NOT NULL
)
---
CREATE TABLE IF NOT EXISTS entries (
    id         TEXT PRIMARY KEY,
    room       TEXT NOT NULL REFERENCES rooms(name),
    title      TEXT NOT NULL,
    summary    TEXT NOT NULL,
    detail     TEXT NOT NULL,
    tags       TEXT NOT NULL DEFAULT '[]',
    status     TEXT NOT NULL DEFAULT 'active',
    created_on TEXT NOT NULL,
    updated_on TEXT NOT NULL
)
---
CREATE TABLE IF NOT EXISTS todos (
    id           INTEGER PRIMARY KEY,
    room         TEXT NOT NULL REFERENCES rooms(name),
    title        TEXT NOT NULL,
    detail       TEXT,
    priority     INTEGER NOT NULL DEFAULT 3,
    due_date     TEXT,
    status       TEXT NOT NULL DEFAULT 'open',
    entry_id     TEXT REFERENCES entries(id),
    completed_on TEXT,
    created_on   TEXT NOT NULL,
    updated_on   TEXT NOT NULL
)
---
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(title, summary, detail, content=entries, content_rowid=rowid)
---
CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, title, summary, detail)
    VALUES (new.rowid, new.title, new.summary, new.detail);
END
---
CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, summary, detail)
    VALUES ('delete', old.rowid, old.title, old.summary, old.detail);
END
---
CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, summary, detail)
    VALUES ('delete', old.rowid, old.title, old.summary, old.detail);
    INSERT INTO entries_fts(rowid, title, summary, detail)
    VALUES (new.rowid, new.title, new.summary, new.detail);
END
