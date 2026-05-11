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
