# -*- coding: utf-8 -*-


def _post_init_hook(env):
    """
    Called after module installation (NOT upgrade — upgrades run the
    migrations/ scripts instead).
    1. Creates/fixes the Реверс picking types for all warehouses
    2. Syncs stock locations for existing employees
    3. Establishes resource→location identity (H4): splits any name-collision,
       backfills partner links, and creates the partial-unique indexes — so a
       FRESH install gets the same guards an upgrade gets from the migration.
    """
    setup_model = env['eskon_reverse.setup']
    setup_model._create_reverse_picking_type()
    setup_model._sync_employee_locations()
    setup_model._migrate_resource_location_identity()
