SELECT r.name, r.aliases, r.tags, r.updated_on, COUNT(e.id) AS entry_count
FROM rooms r
LEFT JOIN entries e ON e.room = r.name
GROUP BY r.name
ORDER BY r.updated_on DESC
