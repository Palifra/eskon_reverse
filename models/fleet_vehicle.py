# -*- coding: utf-8 -*-
from odoo import api, models, fields
import logging

_logger = logging.getLogger(__name__)


class FleetVehicle(models.Model):
    """
    Extend fleet.vehicle to add stock location for material tracking.

    This model is only loaded if fleet module is installed.
    The location is created automatically via stock.location.provider.
    """
    _inherit = 'fleet.vehicle'

    stock_location_id = fields.Many2one(
        'stock.location',
        string='Локација на залихи',
        readonly=True,
        help='Автоматски креирана интерна локација за следење на материјали во возилото'
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-create stock location when vehicle is created."""
        vehicles = super().create(vals_list)

        provider = self.env['stock.location.provider']
        for vehicle in vehicles:
            if not vehicle.stock_location_id:
                location = provider.get_or_create_location('vehicle', vehicle)
                if location:
                    vehicle.stock_location_id = location.id

        return vehicles

    def write(self, vals):
        """Update location name if vehicle name/license changes."""
        res = super().write(vals)

        if 'name' in vals or 'license_plate' in vals:
            provider = self.env['stock.location.provider']
            for vehicle in self:
                provider.sync_location_name('vehicle', vehicle)

        return res
