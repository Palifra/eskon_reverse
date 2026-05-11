# -*- coding: utf-8 -*-


def _post_init_hook(env):
    """
    Called after module installation/upgrade.
    1. Creates/fixes the Реверс picking types for all warehouses
    2. Syncs stock locations for existing employees
    """
    setup_model = env['eskon_reverse.setup']
    setup_model._create_reverse_picking_type()
    setup_model._sync_employee_locations()
