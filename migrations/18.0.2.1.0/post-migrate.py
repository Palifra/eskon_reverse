# -*- coding: utf-8 -*-
"""H4 — switch resource→location identity from display-name to a stable
per-resource link. Splits the one pre-existing prod collision (the empty
loc-108 shared by two vehicles), backfills partner links, and adds the
partial-unique indexes that prevent recurrence. Idempotent / safe to re-run."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['eskon_reverse.setup']._migrate_resource_location_identity()
