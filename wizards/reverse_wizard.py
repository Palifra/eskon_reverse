# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)


class ReverseWizard(models.TransientModel):
    _name = 'eskon_reverse.wizard'
    _description = 'Wizard за креирање реверс'

    # ─────────────────────────────────────────────────────────────────────────
    # RECIPIENT FIELDS
    # ─────────────────────────────────────────────────────────────────────────

    borrower_type = fields.Selection([
        ('employee', 'На вработен'),
        ('partner', 'На партнер/клиент'),
    ], string='Тип на примател', default='employee', required=True)

    employee_id = fields.Many2one(
        'hr.employee',
        string='Вработен',
    )

    partner_id = fields.Many2one(
        'res.partner',
        string='Партнер/Клиент',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # DETAIL FIELDS
    # ─────────────────────────────────────────────────────────────────────────

    return_date = fields.Date(
        string='Рок за враќање',
        required=True,
        default=lambda self: self._default_return_date(),
    )

    origin = fields.Char(
        string='Референца',
        help='Референца на нарачка, проект или друг документ',
    )

    note = fields.Text(
        string='Белешка',
    )

    line_ids = fields.One2many(
        'eskon_reverse.wizard.line',
        'wizard_id',
        string='Производи',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # COMPUTED / HELPER FIELDS
    # ─────────────────────────────────────────────────────────────────────────

    company_id = fields.Many2one(
        'res.company',
        string='Компанија',
        default=lambda self: self.env.company,
    )

    source_location_id = fields.Many2one(
        'stock.location',
        string='Изворна локација',
        compute='_compute_source_location',
    )

    dest_location_id = fields.Many2one(
        'stock.location',
        string='Дестинација',
        compute='_compute_dest_location',
    )

    recipient_selected = fields.Boolean(
        compute='_compute_recipient_selected',
    )

    dest_location_name = fields.Char(
        compute='_compute_dest_location',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # DISPLAY NAME
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_display_name(self):
        for wizard in self:
            wizard.display_name = _('Нов Реверс')

    # ─────────────────────────────────────────────────────────────────────────
    # DEFAULTS
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def _default_return_date(self):
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'eskon_reverse.default_return_days', '7'
        ))
        return fields.Date.today() + timedelta(days=days)

    # ─────────────────────────────────────────────────────────────────────────
    # COMPUTE METHODS
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends('employee_id', 'partner_id', 'borrower_type')
    def _compute_recipient_selected(self):
        for wizard in self:
            if wizard.borrower_type == 'employee':
                wizard.recipient_selected = bool(wizard.employee_id)
            else:
                wizard.recipient_selected = bool(wizard.partner_id)

    @api.depends('company_id')
    def _compute_source_location(self):
        for wizard in self:
            warehouse = self.env['stock.warehouse'].search([
                ('company_id', '=', wizard.company_id.id),
            ], limit=1)
            wizard.source_location_id = warehouse.lot_stock_id if warehouse else False

    @api.depends('borrower_type', 'employee_id', 'partner_id')
    def _compute_dest_location(self):
        provider = self.env['stock.location.provider']
        for wizard in self:
            location = False
            if wizard.borrower_type == 'employee' and wizard.employee_id:
                location = provider.get_or_create_location('employee', wizard.employee_id)
            elif wizard.borrower_type == 'partner' and wizard.partner_id:
                location = provider.get_or_create_location('partner', wizard.partner_id)
            wizard.dest_location_id = location
            wizard.dest_location_name = location.complete_name if location else ''

    # ─────────────────────────────────────────────────────────────────────────
    # ONCHANGE
    # ─────────────────────────────────────────────────────────────────────────

    @api.onchange('borrower_type')
    def _onchange_borrower_type(self):
        self.employee_id = False
        self.partner_id = False

    # ─────────────────────────────────────────────────────────────────────────
    # ACTIONS
    # ─────────────────────────────────────────────────────────────────────────

    def action_confirm(self):
        """Create stock.picking in draft/ready state (confirmed + assigned)."""
        self.ensure_one()
        self._validate_wizard()

        picking = self._create_picking()

        # Confirm and check availability (state: assigned / waiting)
        picking.action_confirm()
        picking.action_assign()

        return self._action_open_picking(picking)

    def action_confirm_and_validate(self):
        """Create stock.picking and immediately validate (state: done)."""
        self.ensure_one()
        self._validate_wizard()

        picking = self._create_picking()

        # Confirm → Assign → Validate
        picking.action_confirm()
        picking.action_assign()

        # Set quantities done on move lines
        for move in picking.move_ids:
            if move.move_line_ids:
                for ml in move.move_line_ids:
                    ml.quantity = ml.reserved_uom_qty or move.product_uom_qty
            else:
                move.quantity = move.product_uom_qty

        picking.button_validate()

        return self._action_open_picking(picking)

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE METHODS
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_wizard(self):
        """Validate wizard data before creating picking."""
        self.ensure_one()

        if self.borrower_type == 'employee' and not self.employee_id:
            raise ValidationError(_('Одберете вработен.'))
        if self.borrower_type == 'partner' and not self.partner_id:
            raise ValidationError(_('Одберете партнер/клиент.'))
        if not self.line_ids:
            raise ValidationError(_('Додајте барем еден производ.'))
        if not self.source_location_id:
            raise ValidationError(_('Не е пронајден магацин за тековната компанија.'))
        if not self.dest_location_id:
            raise ValidationError(_('Не е пронајдена дестинациска локација за примателот.'))

        for line in self.line_ids:
            if line.qty <= 0:
                raise ValidationError(
                    _('Количината за "%s" мора да биде поголема од 0.') % line.product_id.name
                )
            if line.product_tracking != 'none' and not line.lot_id:
                raise ValidationError(
                    _('Производот "%s" бара лот/сериски број.') % line.product_id.name
                )

    def _create_picking(self):
        """Create stock.picking with move lines from wizard data."""
        self.ensure_one()

        # Find the Реверс picking type
        picking_type = self.env['stock.picking.type'].search([
            ('name', '=', 'Реверс'),
            ('warehouse_id.company_id', '=', self.company_id.id),
        ], limit=1)

        if not picking_type:
            raise ValidationError(
                _('Не е пронајден тип на операција "Реверс". '
                  'Проверете дали модулот е правилно инсталиран.')
            )

        # Determine partner_id for the picking
        partner = False
        if self.borrower_type == 'partner':
            partner = self.partner_id
        elif self.borrower_type == 'employee' and self.employee_id.work_contact_id:
            partner = self.employee_id.work_contact_id

        picking_vals = {
            'picking_type_id': picking_type.id,
            'location_id': self.source_location_id.id,
            'location_dest_id': self.dest_location_id.id,
            'partner_id': partner.id if partner else False,
            'origin': self.origin or '',
            'return_date': self.return_date,
            'borrower_type': self.borrower_type,
            'note': self.note or '',
            'move_ids': [],
        }

        # Add stock moves from wizard lines
        for line in self.line_ids:
            move_vals = {
                'name': line.product_id.display_name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'product_uom': line.product_uom_id.id,
                'location_id': self.source_location_id.id,
                'location_dest_id': self.dest_location_id.id,
            }
            picking_vals['move_ids'].append((0, 0, move_vals))

        picking = self.env['stock.picking'].create(picking_vals)

        # Set lot on move lines if specified
        assigned_move_ids = set()
        for line in self.line_ids.filtered(lambda l: l.lot_id):
            move = picking.move_ids.filtered(
                lambda m, pid=line.product_id.id: m.product_id.id == pid and m.id not in assigned_move_ids
            )
            if not move:
                continue
            assigned_move_ids.add(move[0].id)
            if move[0].move_line_ids:
                move[0].move_line_ids[0].lot_id = line.lot_id
            else:
                self.env['stock.move.line'].create({
                    'move_id': move[0].id,
                    'picking_id': picking.id,
                    'product_id': line.product_id.id,
                    'product_uom_id': line.product_uom_id.id,
                    'lot_id': line.lot_id.id,
                    'location_id': self.source_location_id.id,
                    'location_dest_id': self.dest_location_id.id,
                })

        return picking

    def _action_open_picking(self, picking):
        """Return action to open the created picking."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': picking.id,
            'target': 'current',
        }


class ReverseWizardLine(models.TransientModel):
    _name = 'eskon_reverse.wizard.line'
    _description = 'Линија на wizard за реверс'

    wizard_id = fields.Many2one(
        'eskon_reverse.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )

    product_id = fields.Many2one(
        'product.product',
        string='Производ',
        required=True,
        domain="[('type', '=', 'consu')]",
    )

    qty = fields.Float(
        string='Количина',
        required=True,
        default=1.0,
    )

    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Единица мерка',
        required=True,
    )

    lot_id = fields.Many2one(
        'stock.lot',
        string='Лот/Сериски бр.',
        domain="[('product_id', '=', product_id)]",
    )

    product_tracking = fields.Selection(
        related='product_id.tracking',
        string='Следење',
    )

    available_qty = fields.Float(
        string='Достапно',
        compute='_compute_available_qty',
    )

    status = fields.Selection([
        ('ok', 'Достапно'),
        ('partial', 'Делумно'),
        ('no_stock', 'Нема залиха'),
    ], string='Статус', compute='_compute_available_qty')

    # ─────────────────────────────────────────────────────────────────────────
    # COMPUTE
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends('product_id', 'qty', 'wizard_id.source_location_id')
    def _compute_available_qty(self):
        for line in self:
            if line.product_id and line.wizard_id.source_location_id:
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', line.wizard_id.source_location_id.id),
                ])
                line.available_qty = sum(q.quantity - q.reserved_quantity for q in quants)
                if line.available_qty <= 0:
                    line.status = 'no_stock'
                elif line.available_qty < line.qty:
                    line.status = 'partial'
                else:
                    line.status = 'ok'
            else:
                line.available_qty = 0.0
                line.status = 'no_stock'

    # ─────────────────────────────────────────────────────────────────────────
    # ONCHANGE
    # ─────────────────────────────────────────────────────────────────────────

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id
            self.lot_id = False
