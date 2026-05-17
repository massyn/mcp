SELECT * FROM entries
WHERE id = ?
{% if with_room %}AND room = ?{% endif %}
