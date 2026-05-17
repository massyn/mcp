SELECT id, room, title, detail, priority, due_date, status, entry_id, created_on, updated_on
FROM todos
WHERE id = ?
