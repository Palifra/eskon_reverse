# -*- coding: utf-8 -*-
from odoo import api, models


class ReverseSetup(models.AbstractModel):
    _name = 'eskon_reverse.setup'
    _description = 'Setup for Reverse (Equipment Borrowing)'

    @api.model
    def _create_reverse_picking_type(self):
        """
        Creates Реверс picking type for each warehouse.
        Called during module installation.
        """
        Warehouse = self.env['stock.warehouse']
        PickingType = self.env['stock.picking.type']
        Sequence = self.env['ir.sequence']
        Location = self.env['stock.location']

        # Get the employees parent location
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
                continue  # Already created

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

            # Determine destination location
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
