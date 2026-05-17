SELECT id, room, title, detail, priority, due_date, status, entry_id, created_on, updated_on
FROM todos
WHERE 1=1
{% if room %}AND room = ?
{% endif %}{% if statuses %}AND status IN ({% for _ in statuses %}?{% if not loop.last %}, {% endif %}{% endfor %})
{% endif %}{% if priority_max %}AND priority <= ?
{% endif %}{% if due_before %}AND due_date <= ?
{% endif %}ORDER BY priority ASC, due_date ASC NULLS LAST, created_on ASC
LIMIT ?
