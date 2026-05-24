---
name: get_open_heatmap
description: Returns open/in-progress/blocked todo counts by room and priority for heatmap display.
transaction: false
parameters:
  room:
    type: string
    required: false
    description: Limit to a specific room (omit for all rooms)
---
SELECT room, priority, COUNT(*) AS n
FROM todos
WHERE status IN ('open','in_progress','blocked')
{% if room is not none %}
AND room = '{{ room }}'
{% endif %}
GROUP BY room, priority ORDER BY room, priority
