SELECT e.id, e.room, e.title, e.summary, e.tags, e.status, e.updated_on
FROM entries_fts
JOIN entries e ON entries_fts.rowid = e.rowid
WHERE entries_fts MATCH ?
{% if status %}AND e.status = ?
{% endif %}{% if room %}AND e.room = ?
{% endif %}ORDER BY rank
LIMIT ?
