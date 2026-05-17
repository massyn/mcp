UPDATE entries
SET {{ fields | join(', ') }}, updated_on = ?
WHERE id = ? AND room = ?
