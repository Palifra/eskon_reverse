# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def _post_init_hook(env):
    """
    Called after module installation.
    Creates the Реверс picking type for all warehouses.
    """
    setup_model = env['eskon_reverse.setup']
    setup_model._create_reverse_picking_type()
