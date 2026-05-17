INSERT INTO rooms (name, aliases, tags, created_on, updated_on)
SELECT ?, ?, ?, created_on, ?
FROM rooms
WHERE name = ?
