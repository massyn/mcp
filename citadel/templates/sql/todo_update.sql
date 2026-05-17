UPDATE todos
SET {{ fields | join(', ') }}, updated_on = ?
WHERE id = ?
