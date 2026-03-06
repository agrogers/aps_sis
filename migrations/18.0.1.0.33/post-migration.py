from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Populate the new `level` field for all existing aps.resources records.

    The level represents the depth in the resource hierarchy:
      - Level 0: root resources (no parents)
      - Level N: min(parent.level) + 1 for all parents

    Processing is done layer by layer (BFS) so parents are always assigned
    before their children.  Any records that remain after the BFS (e.g. due
    to cycles) are set to level 0 as a safe fallback.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    all_resources = env['aps.resources'].search([])

    if not all_resources:
        return

    # Build parent map from the full relationship table (no filtering needed since
    # we process all resources).
    cr.execute("SELECT child_id, parent_id FROM aps_resources_rel")
    parent_map = {}
    for child_id, parent_id in cr.fetchall():
        parent_map.setdefault(child_id, set()).add(parent_id)

    assigned = {}  # resource_id -> level

    # Seed: root resources (no parents)
    queue = []
    for rec in all_resources:
        parents = parent_map.get(rec.id, set())
        if not parents:
            assigned[rec.id] = 0
        else:
            queue.append(rec)

    # BFS layer processing
    max_iterations = len(queue) + 1
    iteration = 0
    while queue and iteration < max_iterations:
        iteration += 1
        still_pending = []
        for rec in queue:
            parents = parent_map.get(rec.id, set())
            if all(pid in assigned for pid in parents):
                assigned[rec.id] = min(assigned[pid] for pid in parents) + 1
            else:
                still_pending.append(rec)
        queue = still_pending

    # Cycle fallback: any remaining records get level 0
    for rec in queue:
        if rec.id not in assigned:
            assigned[rec.id] = 0

    # Write levels in bulk
    for resource_id, level_value in assigned.items():
        cr.execute(
            "UPDATE aps_resources SET level = %s WHERE id = %s",
            (level_value, resource_id),
        )
