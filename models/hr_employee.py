# -*- coding: utf-8 -*-
from odoo import api, models, fields, _
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    stock_location_id = fields.Many2one(
        'stock.location',
        string='Локација на залихи',
        readonly=True,
        copy=False,  # one location per employee — a copy must NOT inherit the
                     # link (the partial-unique index would reject it); the
                     # create-override re-creates a fresh one for the copy.
        help='Автоматски креирана интерна локација за следење на опрема/материјали'
    )

    stock_equipment_count = fields.Integer(
        string='Залиха опрема',
        compute='_compute_stock_equipment_info',
    )

    stock_equipment_qty = fields.Float(
        string='Вкупно парчиња залиха опрема',
        compute='_compute_stock_equipment_info',
    )

    def _get_equipment_quants(self):
        """Return stock.quant records with positive quantity at employee location."""
        self.ensure_one()
        if not self.stock_location_id:
            return self.env['stock.quant']
        return self.env['stock.quant'].search([
            ('location_id', '=', self.stock_location_id.id),
            ('quantity', '>', 0),
        ])

    @api.depends('stock_location_id')
    def _compute_stock_equipment_info(self):
        Quant = self.env['stock.quant']
        for employee in self:
            if employee.stock_location_id:
                domain = [
                    ('location_id', '=', employee.stock_location_id.id),
                    ('quantity', '>', 0),
                ]
                employee.stock_equipment_count = Quant.search_count(domain)
                quants = Quant.search(domain)
                employee.stock_equipment_qty = sum(quants.mapped('quantity'))
            else:
                employee.stock_equipment_count = 0
                employee.stock_equipment_qty = 0

    def toggle_active(self):
        """Guard: block archiving if employee has unreturned equipment."""
        # Only check employees being ARCHIVED (active → inactive)
        employees_to_archive = self.filtered(lambda e: e.active)

        for employee in employees_to_archive:
            quants = employee._get_equipment_quants()
            if quants:
                items = '\n'.join(
                    f'  • {q.product_id.name}: {q.quantity} {q.product_uom_id.name}'
                    for q in quants
                )
                raise ValidationError(_(
                    'Вработениот „%(name)s" има невратена опрема:\n\n'
                    '%(items)s\n\n'
                    'Направете повратница (REV-RET) пред да го архивирате.',
                    name=employee.name,
                    items=items,
                ))

        # Call standard toggle (opens departure wizard for archiving)
        res = super().toggle_active()

        # After archiving — archive empty stock locations
        archived = self.filtered(lambda e: not e.active and e.stock_location_id)
        for employee in archived:
            if not employee._get_equipment_quants():
                employee.stock_location_id.active = False

        # After un-archiving — reactivate stock locations
        unarchived = self.filtered(lambda e: e.active and e.stock_location_id)
        for employee in unarchived:
            if not employee.stock_location_id.active:
                employee.stock_location_id.active = True

        return res

    def action_view_equipment(self):
        """Open list of equipment assigned to this employee."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Опрема - %s') % self.name,
            'res_model': 'stock.quant',
            'view_mode': 'list,form',
            'domain': [
                ('location_id', '=', self.stock_location_id.id),
                ('quantity', '>', 0),
            ],
            'context': {'no_at_date': True},
        }

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
