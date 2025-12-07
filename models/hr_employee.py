# -*- coding: utf-8 -*-
from odoo import api, models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    stock_location_id = fields.Many2one(
        'stock.location',
        string='Локација на залихи',
        readonly=True,
        help='Автоматски креирана интерна локација за следење на опрема/материјали'
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-create stock location when employee is created."""
        employees = super().create(vals_list)

        provider = self.env['stock.location.provider']
        for employee in employees:
            if not employee.stock_location_id:
                location = provider.get_or_create_location('employee', employee)
                if location:
                    employee.stock_location_id = location.id

        return employees

    def write(self, vals):
        """Update location name if employee name changes."""
        res = super().write(vals)

        if 'name' in vals:
            provider = self.env['stock.location.provider']
            for employee in self:
                provider.sync_location_name('employee', employee)

        return res
