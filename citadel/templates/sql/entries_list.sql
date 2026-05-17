SELECT id, title, summary, tags, status, updated_on
FROM entries
WHERE room = ? AND status = ?
ORDER BY updated_on DESC
LIMIT ? OFFSET ?
