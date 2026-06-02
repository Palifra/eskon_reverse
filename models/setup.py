# -*- coding: utf-8 -*-
from odoo import api, models
import logging

_logger = logging.getLogger(__name__)


class ReverseSetup(models.AbstractModel):
    _name = 'eskon_reverse.setup'
    _description = 'Setup for Reverse (Equipment Borrowing)'

    @api.model
    def _create_reverse_picking_type(self):
        """
        Creates Реверс picking type for each warehouse.
        Called during module installation.
        Also fixes existing picking types that point to wrong locations.
        """
        Warehouse = self.env['stock.warehouse']
        PickingType = self.env['stock.picking.type']
        Sequence = self.env['ir.sequence']
        Location = self.env['stock.location']

        # Get the employees parent location (view — container only)
        employees_location = self.env.ref(
            'eskon_reverse.stock_location_employees',
            raise_if_not_found=False
        )

        if not employees_location:
            # Fallback - create it
            physical_locations = Location.search([
                ('name', '=', 'Physical Locations'),
                ('usage', '=', 'view')
            ], limit=1)

            if physical_locations:
                employees_location = Location.create({
                    'name': 'Вработени',
                    'usage': 'view',
                    'location_id': physical_locations.id,
                })

        # Create picking type for each warehouse
        for warehouse in Warehouse.search([]):
            # Check if already exists
            existing = PickingType.search([
                ('name', '=', 'Реверс'),
                ('warehouse_id', '=', warehouse.id),
            ], limit=1)

            if existing:
                # Fix existing picking type if it points to wrong location
                self._fix_picking_type_locations(existing, employees_location, warehouse)
                continue

            # Create sequence for this warehouse
            sequence = Sequence.create({
                'name': f'{warehouse.name} Секвенца Реверс',
                'prefix': f'{warehouse.code}/REV/',
                'padding': 5,
                'number_next': 1,
                'company_id': warehouse.company_id.id,
            })

            # Create return sequence
            return_sequence = Sequence.create({
                'name': f'{warehouse.name} Секвенца Повратница',
                'prefix': f'{warehouse.code}/REV-RET/',
                'padding': 5,
                'number_next': 1,
                'company_id': warehouse.company_id.id,
            })

            # Destination is the Вработени view location (container)
            dest_location = employees_location or warehouse.lot_stock_id

            # Create the picking type
            reverse_picking_type = PickingType.create({
                'name': 'Реверс',
                'code': 'internal',
                'sequence_code': 'REV',
                'sequence_id': sequence.id,
                'warehouse_id': warehouse.id,
                'default_location_src_id': warehouse.lot_stock_id.id,
                'default_location_dest_id': dest_location.id,
                'company_id': warehouse.company_id.id,
            })

            # Create return picking type
            return_picking_type = PickingType.create({
                'name': 'Повратница',
                'code': 'internal',
                'sequence_code': 'REV-RET',
                'sequence_id': return_sequence.id,
                'warehouse_id': warehouse.id,
                'default_location_src_id': dest_location.id,
                'default_location_dest_id': warehouse.lot_stock_id.id,
                'company_id': warehouse.company_id.id,
                'return_picking_type_id': reverse_picking_type.id,
            })

            # Link reverse to return
            reverse_picking_type.write({
                'return_picking_type_id': return_picking_type.id,
            })

        return True

    @api.model
    def _fix_picking_type_locations(self, picking_type, employees_location, warehouse):
        """
        Fix picking type that points to wrong/archived/non-existent location.
        Ensures default_location_dest_id points to 'Вработени' (eskon_reverse).
        """
        if not employees_location:
            return

        dest = picking_type.default_location_dest_id
        needs_fix = False

        # Fix if dest is archived
        if dest and not dest.active:
            needs_fix = True
        # Fix if dest is not under our hierarchy (Ресурси/)
        elif dest and dest.id != employees_location.id:
            resources_location = self.env.ref(
                'eskon_reverse.stock_location_resources',
                raise_if_not_found=False
            )
            if resources_location and dest.location_id != resources_location:
                # Not under Ресурси — probably old Employees or Залиха
                needs_fix = True

        if needs_fix:
            picking_type.write({'default_location_dest_id': employees_location.id})
            _logger.info(
                "Fixed Реверс picking type '%s': default_dest → %s",
                picking_type.display_name, employees_location.complete_name
            )

        # Also fix the linked Повратница source
        return_pt = self.env['stock.picking.type'].search([
            ('name', '=', 'Повратница'),
            ('warehouse_id', '=', warehouse.id),
        ], limit=1)
        if return_pt and return_pt.default_location_src_id != employees_location:
            return_pt.write({'default_location_src_id': employees_location.id})
            _logger.info(
                "Fixed Повратница picking type '%s': default_src → %s",
                return_pt.display_name, employees_location.complete_name
            )

    @api.model
    def _sync_employee_locations(self):
        """
        Ensure all existing employees have a stock_location_id.
        Creates missing locations via stock.location.provider.
        Called on module install/upgrade.
        """
        provider = self.env['stock.location.provider']
        employees = self.env['hr.employee'].search([
            ('stock_location_id', '=', False),
        ])

        synced = 0
        for employee in employees:
            location = provider.get_or_create_location('employee', employee)
            if location:
                employee.write({'stock_location_id': location.id})
                synced += 1

        if synced:
            _logger.info("Synced stock locations for %d employees", synced)

        return True

    # ─────────────────────────────────────────────────────────────────────────
    # H4 — resource→location identity migration
    # ─────────────────────────────────────────────────────────────────────────

    # Partial-unique indexes keep one location per resource — the "teeth" that
    # stop a collision recurring. Created only AFTER existing collisions are
    # resolved, so creation cannot fail on a pre-existing duplicate.
    _LINK_INDEXES = [
        ('hr_employee', 'stock_location_id', 'eskon_reverse_uniq_emp_location'),
        ('fleet_vehicle', 'stock_location_id', 'eskon_reverse_uniq_veh_location'),
        ('res_partner', 'reverse_location_id', 'eskon_reverse_uniq_partner_location'),
    ]

    @api.model
    def _migrate_resource_location_identity(self):
        """One-time, idempotent H4 migration. Safe to re-run.

        1. Split any internal location shared by >1 resource onto fresh
           locations (keep the first holder; re-home the rest). A shared
           location that still holds stock is left for manual handling (logged).
        2. Backfill ``res.partner.reverse_location_id`` from the existing
           Партнери children by 1:1 name match.
        3. Create partial-unique indexes on the link columns so the collision
           cannot recur at the DB level.
        """
        # Flush first so the raw-SQL collision scan below sees any pending ORM
        # writes (e.g. a caller that just re-pointed a resource) — not stale
        # committed rows. Without this the scan can miss an unflushed collision.
        self.env.flush_all()
        self._split_shared_resource_locations()
        self._backfill_partner_location_links()
        self._create_link_unique_indexes()
        return True

    @api.model
    def _split_shared_resource_locations(self):
        provider = self.env['stock.location.provider']
        Quant = self.env['stock.quant']
        for model, field, rtype in (
            ('hr.employee', 'stock_location_id', 'employee'),
            ('fleet.vehicle', 'stock_location_id', 'vehicle'),
        ):
            Model = self.env[model].with_context(active_test=False)
            self.env.cr.execute(
                "SELECT %s FROM %s WHERE %s IS NOT NULL "
                "GROUP BY %s HAVING count(*) > 1" % (
                    field, Model._table, field, field))
            shared_loc_ids = [row[0] for row in self.env.cr.fetchall()]
            for loc_id in shared_loc_ids:
                # Keep the lowest-id holder; re-home the rest. active_test=False
                # so an archived holder is re-homed too (else it lingers on the
                # shared location and blocks the unique index).
                holders = Model.search([(field, '=', loc_id)], order='id')
                if Quant.search_count([('location_id', '=', loc_id),
                                       ('quantity', '!=', 0)]):
                    _logger.warning(
                        "H4 migration: location id %s shared by %d %s and NON-EMPTY "
                        "— leaving for manual split", loc_id, len(holders), model)
                    continue
                for extra in holders[1:]:
                    extra.sudo().write({field: False})
                    new_loc = provider.get_or_create_location(rtype, extra)
                    _logger.info(
                        "H4 migration: re-homed %s off shared location %s → %s",
                        extra.display_name, loc_id,
                        new_loc.display_name if new_loc else '∅')

    @api.model
    def _backfill_partner_location_links(self):
        partners_parent = self.env.ref(
            'eskon_reverse.stock_location_partners', raise_if_not_found=False)
        if not partners_parent:
            return
        Partner = self.env['res.partner']
        for loc in self.env['stock.location'].search(
                [('location_id', '=', partners_parent.id)]):
            partners = Partner.search([('name', '=', loc.name)])
            if len(partners) == 1 and not partners.reverse_location_id:
                partners.sudo().write({'reverse_location_id': loc.id})
                _logger.info("H4 migration: linked partner '%s' → location %s",
                             partners.name, loc.id)
            elif len(partners) > 1:
                _logger.warning(
                    "H4 migration: %d partners named '%s' — skipping link (ambiguous)",
                    len(partners), loc.name)

    @api.model
    def _create_link_unique_indexes(self):
        # Flush pending ORM writes (the re-home + partner backfill) so the raw
        # index DDL below sees the post-split table state, not stale pre-write
        # rows still buffered in the ORM (the cache-vs-raw-SQL flush trap).
        self.env.flush_all()
        for table, field, name in self._LINK_INDEXES:
            self.env.cr.execute(
                "SELECT 1 FROM pg_indexes WHERE indexname = %s", (name,))
            if self.env.cr.fetchone():
                continue
            # Defensive: never abort the whole upgrade if a duplicate survives
            # (e.g. a shared location that still holds stock, left for manual
            # split). Skip+warn so the rest of the migration/upgrade proceeds.
            self.env.cr.execute(
                "SELECT %s FROM %s WHERE %s IS NOT NULL "
                "GROUP BY %s HAVING count(*) > 1 LIMIT 1" % (
                    field, table, field, field))
            if self.env.cr.fetchone():
                _logger.warning(
                    "H4 migration: %s still has a duplicate location link — "
                    "skipping unique index %s. Resolve the shared location "
                    "manually, then re-run the migration.", table, name)
                continue
            self.env.cr.execute(
                "CREATE UNIQUE INDEX %s ON %s (%s) WHERE %s IS NOT NULL" % (
                    name, table, field, field))
            _logger.info("H4 migration: created unique index %s", name)
