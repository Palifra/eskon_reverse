# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from datetime import timedelta

from .stock_picking_type import REVERSE_CODE


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    return_date = fields.Date(
        string='Рок за враќање',
        help='Датум до кој опремата треба да биде вратена',
        tracking=True,
    )

    borrower_type = fields.Selection([
        ('employee', 'Вработен'),
        ('partner', 'Партнер/Клиент'),
    ], string='Тип на примател', default='employee')

    reminder_sent = fields.Boolean(
        string='Потсетување испратено',
        default=False,
        copy=False,
    )

    days_until_return = fields.Integer(
        string='Денови до враќање',
        compute='_compute_days_until_return',
        store=False,
    )

    is_overdue = fields.Boolean(
        string='Задоцнето',
        compute='_compute_days_until_return',
        store=False,
    )

    is_returned = fields.Boolean(
        string='Вратено',
        compute='_compute_is_returned',
        store=False,
    )

    is_reverse_picking = fields.Boolean(
        string='Е реверс',
        compute='_compute_is_reverse_picking',
        store=False,
    )

    @api.depends('picking_type_id', 'picking_type_id.sequence_code')
    def _compute_is_reverse_picking(self):
        for picking in self:
            picking.is_reverse_picking = (
                picking.picking_type_id.sequence_code == REVERSE_CODE
            )

    @api.depends('return_ids')
    def _compute_is_returned(self):
        for picking in self:
            # Check if this reverse has any completed returns
            if picking.picking_type_id.sequence_code == REVERSE_CODE:
                picking.is_returned = bool(picking.return_ids.filtered(lambda r: r.state == 'done'))
            else:
                picking.is_returned = False

    @api.depends('return_date')
    def _compute_days_until_return(self):
        today = fields.Date.today()
        for picking in self:
            if picking.return_date:
                delta = picking.return_date - today
                picking.days_until_return = delta.days
                picking.is_overdue = delta.days < 0
            else:
                picking.days_until_return = 0
                picking.is_overdue = False

    @api.model
    def _cron_send_return_reminders(self):
        """
        Scheduled action to send reminders for equipment returns.
        Sends reminder 3 days before return date.
        """
        reminder_date = fields.Date.today() + timedelta(days=3)

        # Find reverse pickings with return date approaching
        pickings_to_remind = self.search([
            ('picking_type_id.sequence_code', '=', REVERSE_CODE),
            ('state', '=', 'done'),
            ('return_date', '=', reminder_date),
            ('reminder_sent', '=', False),
        ])

        for picking in pickings_to_remind:
            # Send reminder (create activity)
            picking.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=picking.return_date,
                summary=_('Потсетување за враќање на опрема'),
                note=_('Реверс %s има рок за враќање на %s. '
                       'Ве молиме обезбедете враќање на опремата.') % (
                    picking.name, picking.return_date),
            )
            picking.reminder_sent = True

            # Also check if partner has email and send
            if picking.partner_id and picking.partner_id.email:
                # Log a note on the picking
                picking.message_post(
                    body=_('Испратено потсетување за враќање до %s') % picking.partner_id.name,
                    message_type='notification',
                )

        # Also find overdue pickings
        overdue_pickings = self.search([
            ('picking_type_id.sequence_code', '=', REVERSE_CODE),
            ('state', '=', 'done'),
            ('return_date', '<', fields.Date.today()),
        ])

        for picking in overdue_pickings:
            # Create urgent activity for overdue items
            existing_activity = self.env['mail.activity'].search([
                ('res_model', '=', 'stock.picking'),
                ('res_id', '=', picking.id),
                ('summary', 'ilike', 'Задоцнето враќање'),
            ], limit=1)

            if not existing_activity:
                picking.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=fields.Date.today(),
                    summary=_('ЗАДОЦНЕТО враќање на опрема!'),
                    note=_('Реверс %s требаше да биде вратен на %s. '
                           'Рокот е поминат за %d денови!') % (
                        picking.name,
                        picking.return_date,
                        abs(picking.days_until_return)),
                )

        return True

    @api.onchange('borrower_type', 'partner_id')
    def _onchange_borrower_partner(self):
        """Resolve the partner's destination location through the central
        Location Provider when a partner is selected on a Реверс picking.

        Routing through ``stock.location.provider`` — instead of a hand-rolled
        ``Location.create`` here — gives one consistent path shared with the
        issue wizard and esfsm_stock:
          * the create is ``sudo``'d, so a normal ``stock.group_stock_user``
            editing the picking does not hit AccessError on stock.location
            create (was M12);
          * the ``auto_create_partner_location`` setting is honoured, so a
            disabled gate no longer litters the Партнери hierarchy (was L2);
          * the location inherits the parent's company (was L3/L6) and dedups
            exactly as the wizard does (was M7).
        """
        if (self.borrower_type == 'partner' and self.partner_id
                and self.picking_type_id.sequence_code == REVERSE_CODE):
            partner_location = self.env['stock.location.provider'].get_or_create_location(
                'partner', self.partner_id)
            if partner_location:
                self.location_dest_id = partner_location
