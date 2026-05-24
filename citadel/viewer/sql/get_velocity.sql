---
name: get_velocity
description: Returns completed todo counts grouped by ISO week and room for velocity charts.
transaction: false
parameters:
  room:
    type: string
    required: false
    description: Limit to a specific room (omit for all rooms)
---
SELECT strftime('%Y-W%W', completed_on) AS week, room, COUNT(*) AS n
FROM todos
WHERE status = 'done' AND completed_on IS NOT NULL
{% if room is not none %}
AND room = '{{ room }}'
{% endif %}
GROUP BY week, room ORDER BY week, room
