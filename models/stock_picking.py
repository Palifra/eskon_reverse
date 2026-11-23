# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
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

    overdue_notified = fields.Boolean(
        string='Известено за задоцнување',
        default=False,
        copy=False,
        help='Дали е креирана активност за задоцнето враќање — спречува '
             'секојдневно повторно креирање откако ќе се означи како завршена.',
    )

    outstanding_qty = fields.Float(
        string='Невратена количина',
        compute='_compute_outstanding_qty',
        store=False,
        help='Количина од издадената опрема сè уште на дестинациската локација '
             '(не е вратена по ниту еден пат). 0 = целосно затворен реверс.',
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

    # ── M2: signed legal handover document (Издал / Примил) ──────────────────
    issuer_id = fields.Many2one(
        'res.users',
        string='Издал',
        default=lambda self: self.env.user,
        copy=False,
        help='Одговорно лице кое ја издало опремата (реверс).',
    )
    issuer_signature = fields.Binary(
        string='Потпис (Издал)', copy=False, attachment=True)
    issuer_signature_date = fields.Datetime(
        string='Датум на потпис (Издал)', readonly=True, copy=False)
    borrower_signature = fields.Binary(
        string='Потпис (Примил)', copy=False, attachment=True)
    borrower_signature_date = fields.Datetime(
        string='Датум на потпис (Примил)', readonly=True, copy=False)

    def write(self, vals):
        # Auto-stamp the capture date when a signature is set, and clear it when
        # the signature is removed — so the date always reflects the signature.
        # Runs for ALL pickings, but the signature keys are реверс-only, so for
        # every other write both `in` checks are False and this is a pass-through.
        # (A multi-record write of one signature stamps the same instant on all —
        # the intended "batch captured at one time" semantics.)
        now = fields.Datetime.now()
        if 'issuer_signature' in vals and 'issuer_signature_date' not in vals:
            vals['issuer_signature_date'] = now if vals.get('issuer_signature') else False
        if 'borrower_signature' in vals and 'borrower_signature_date' not in vals:
            vals['borrower_signature_date'] = now if vals.get('borrower_signature') else False
        return super().write(vals)

    @api.depends('picking_type_id', 'picking_type_id.sequence_code')
    def _compute_is_reverse_picking(self):
        for picking in self:
            picking.is_reverse_picking = (
                picking.picking_type_id.sequence_code == REVERSE_CODE
            )

    def _reverse_outstanding_qty(self):
        """Quantity of the equipment THIS реверс issued that is still on-hand at
        its destination (resource) location — i.e. not yet returned by ANY path
        (native return, Повратница, esfsm return, manual move). 0 ⇒ settled.

        Live signal (reads current quants), capped at what this реверс issued.
        Commingling caveat: two реверс issuing the same product to the same
        location read each other's stock as outstanding — acceptable for
        equipment borrowing (distinct items) and strictly better than the old
        "outstanding forever" behaviour.
        """
        self.ensure_one()
        dest = self.location_dest_id
        if not dest:
            return 0.0
        issued = {}
        for ml in self.move_line_ids.filtered(lambda m: m.state == 'done'):
            # quantity_product_uom: the move line's qty converted to the
            # product's own UoM, so it is comparable with quant.quantity (also
            # in product UoM). Summing ml.quantity directly would mis-read a
            # реверс issued in a non-default UoM (e.g. a dozen vs units).
            issued[ml.product_id] = issued.get(ml.product_id, 0.0) + ml.quantity_product_uom
        Quant = self.env['stock.quant']
        outstanding = 0.0
        for product, qty in issued.items():
            # child_of: the picking's destination may be a parent/view location
            # while the stock physically sits in an internal child — count those
            # too, else a view-dest реверс would always read 0 (falsely settled).
            on_hand = sum(Quant.search([
                ('location_id', 'child_of', dest.id),
                ('product_id', '=', product.id),
            ]).mapped('quantity'))
            outstanding += min(qty, max(on_hand, 0.0))
        return outstanding

    @api.depends('state', 'move_line_ids.quantity', 'move_line_ids.state', 'location_dest_id')
    def _compute_outstanding_qty(self):
        for picking in self:
            if picking.picking_type_id.sequence_code == REVERSE_CODE \
                    and picking.state == 'done':
                picking.outstanding_qty = picking._reverse_outstanding_qty()
            else:
                picking.outstanding_qty = 0.0

    @api.depends('return_ids', 'return_ids.state', 'outstanding_qty', 'state',
                 'move_line_ids.state')
    def _compute_is_returned(self):
        for picking in self:
            if picking.picking_type_id.sequence_code != REVERSE_CODE:
                picking.is_returned = False
                continue
            # Returned by the native Return wizard (back-compat) OR physically
            # settled — the issued equipment is no longer at the destination.
            # "settled" requires that the реверс actually ISSUED something (has
            # done move lines): a реверс with no issue record can't be claimed
            # returned just because its (empty) outstanding is zero.
            native = bool(picking.return_ids.filtered(lambda r: r.state == 'done'))
            issued = bool(picking.move_line_ids.filtered(lambda m: m.state == 'done'))
            settled = (picking.state == 'done' and issued
                       and picking.outstanding_qty < 0.001)
            picking.is_returned = native or settled

    @api.depends('return_date', 'is_returned')
    def _compute_days_until_return(self):
        today = fields.Date.today()
        for picking in self:
            if picking.return_date:
                delta = picking.return_date - today
                picking.days_until_return = delta.days
                # A returned реверс is never overdue (M4 — kills false alarms).
                picking.is_overdue = delta.days < 0 and not picking.is_returned
            else:
                picking.days_until_return = 0
                picking.is_overdue = False

    @api.model
    def _cron_send_return_reminders(self):
        """Scheduled action for equipment-return reminders.

        A реверс that is already settled (equipment physically back — see
        ``is_returned``) is skipped in BOTH passes, so returned gear is never
        reminded nor flagged overdue (H2/M4).
        """
        today = fields.Date.today()

        # 1) Reminder — due within the next 3 days. Threshold window, NOT exact
        #    date (M5): a реверс created only 1–2 days before its deadline is
        #    still reminded, and a missed cron day no longer skips it forever.
        horizon = today + timedelta(days=3)
        pickings_to_remind = self.search([
            ('picking_type_id.sequence_code', '=', REVERSE_CODE),
            ('state', '=', 'done'),
            ('return_date', '>=', today),
            ('return_date', '<=', horizon),
            ('reminder_sent', '=', False),
        ])
        for picking in pickings_to_remind:
            if picking.is_returned:
                continue
            picking.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=picking.return_date,
                summary=_('Потсетување за враќање на опрема'),
                note=_('Реверс %s има рок за враќање на %s. '
                       'Ве молиме обезбедете враќање на опремата.') % (
                    picking.name, picking.return_date),
            )
            picking.reminder_sent = True

            if picking.partner_id and picking.partner_id.email:
                picking.message_post(
                    body=_('Испратено потсетување за враќање до %s') % picking.partner_id.name,
                    message_type='notification',
                )

        # 2) Overdue — past due and not yet notified. The persistent
        #    ``overdue_notified`` flag (mirroring reminder_sent) replaces probing
        #    for an open mail.activity, so marking the to-do Done no longer makes
        #    the cron re-spawn a fresh activity every day (M6).
        overdue_pickings = self.search([
            ('picking_type_id.sequence_code', '=', REVERSE_CODE),
            ('state', '=', 'done'),
            ('return_date', '<', today),
            ('overdue_notified', '=', False),
        ])
        for picking in overdue_pickings:
            if picking.is_returned:
                continue
            picking.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=today,
                summary=_('ЗАДОЦНЕТО враќање на опрема!'),
                note=_('Реверс %s требаше да биде вратен на %s. '
                       'Рокот е поминат за %d денови!') % (
                    picking.name,
                    picking.return_date,
                    abs(picking.days_until_return)),
            )
            picking.overdue_notified = True

        return True

    # ── Примател ↔ дестинација: изведи, не претпоставувај ───────────────
    # Рачно направен Реверс има три независни податоци (partner_id,
    # borrower_type, location_dest_id на линијата) кои Odoo не ги споредува.
    # Во прод тоа даде 10 реверси со примател X а залиха книжена кај првиот
    # вработен од падачката листа. Овде секоја страна се ИЗВЕДУВА од другата,
    # а валидацијата го одбива несовпаѓањето.
    # Дизајн: docs/plans/2026-10-21-reverse-borrower-location-consistency-design.md

    def _reverse_employees_for_partner(self, partner):
        if not partner:
            return self.env['hr.employee']
        return self.env['hr.employee'].sudo().with_context(active_test=False).search(
            [('work_contact_id', '=', partner.id)], limit=2)

    def _reverse_employees_for_location(self, location):
        if not location:
            return self.env['hr.employee']
        return self.env['hr.employee'].sudo().with_context(active_test=False).search(
            [('stock_location_id', '=', location.id)], limit=2)

    def _reverse_partners_for_location(self, location):
        if not location:
            return self.env['res.partner']
        return self.env['res.partner'].sudo().with_context(active_test=False).search(
            [('reverse_location_id', '=', location.id)], limit=2)

    @api.onchange('borrower_type', 'partner_id')
    def _onchange_borrower_partner(self):
        """Derive the destination location from the selected Примател.

        * ``partner`` type: the partner's own location through the central
          Location Provider (sudo'd create, ``auto_create_partner_location``
          honoured, company inherited, dedup by record id — M12/L2/L3/L6/M7).
        * ``employee`` type: the employee whose ``work_contact_id`` is the
          partner; their ``stock_location_id`` becomes the destination so the
          move lines inherit it and nobody picks a name from a dropdown.
          A contact that is not exactly one employee leaves the destination
          untouched and warns — nothing is assumed.
        """
        if (self.picking_type_id.sequence_code != REVERSE_CODE
                or not self.partner_id):
            return
        provider = self.env['stock.location.provider']
        if self.borrower_type == 'partner':
            partner_location = provider.get_or_create_location(
                'partner', self.partner_id)
            if partner_location:
                self.location_dest_id = partner_location
            return
        if self.borrower_type == 'employee':
            employees = self._reverse_employees_for_partner(self.partner_id)
            if len(employees) != 1:
                return {'warning': {
                    'title': _('Контактот не е вработен'),
                    'message': _(
                        '„%(partner)s“ не одговара на точно еден вработен. '
                        'Избери вработен за примател или смени го типот на '
                        'примател на „Партнер/Клиент“. Дестинацијата не е '
                        'променета.', partner=self.partner_id.display_name),
                }}
            location = provider.get_or_create_location('employee', employees)
            if location:
                self.location_dest_id = location

    @api.onchange('location_dest_id')
    def _onchange_borrower_dest_location(self):
        """Fill an empty Примател from a destination that belongs to exactly
        one employee (or one partner). Never overwrites a set partner — the
        validation step decides on a conflict, with both names."""
        if (self.picking_type_id.sequence_code != REVERSE_CODE
                or self.partner_id or not self.location_dest_id):
            return
        employees = self._reverse_employees_for_location(self.location_dest_id)
        if len(employees) == 1 and employees.work_contact_id:
            self.borrower_type = 'employee'
            self.partner_id = employees.work_contact_id
            return
        partners = self._reverse_partners_for_location(self.location_dest_id)
        if len(partners) == 1:
            self.borrower_type = 'partner'
            self.partner_id = partners

    def _reverse_expected_partner(self, location):
        """(expected res.partner, owner label) for a destination that is an
        employee's or a partner's реверс location; (empty, '') otherwise."""
        employees = self._reverse_employees_for_location(location)
        if len(employees) == 1 and employees.work_contact_id:
            return employees.work_contact_id, employees.name
        partners = self._reverse_partners_for_location(location)
        if len(partners) == 1:
            return partners, partners.display_name
        return self.env['res.partner'], ''

    def _check_reverse_borrower_consistency(self):
        """Server-side guard: every line destination that is a person's
        location must belong to the Примател. Empty Примател is filled from
        the destination; a different one is refused with both names."""
        for picking in self.filtered(
                lambda p: p.picking_type_id.sequence_code == REVERSE_CODE):
            lines = picking.move_line_ids or picking.move_ids
            for location in lines.mapped('location_dest_id'):
                expected, owner = picking._reverse_expected_partner(location)
                if not expected:
                    continue
                if picking.partner_id and picking.partner_id != expected:
                    raise UserError(_(
                        'Реверс %(name)s: примател е „%(partner)s“, а материјалот '
                        'оди на локацијата на „%(owner)s“ (%(location)s). '
                        'Исправи го примателот или дестинацијата на линијата.',
                        name=picking.name, partner=picking.partner_id.display_name,
                        owner=owner, location=location.complete_name))
                if not picking.partner_id:
                    picking.partner_id = expected

    def _check_reverse_leaves_source(self):
        """Server-side guard: a Реверс must move the goods somewhere.

        A line whose destination equals its source changes nothing in stock —
        the material stays on the shelf in Odoo while physically it is gone.
        In prod this happened when an FSM job had no technician yet: the
        recipient became „Непознат“ and the destination fell back to the
        warehouse (125 such реверси, e.g. ESGM/REV/2026/00733 — 2.000 m
        cable for ЛТХ that never left ESGM/Залиха on paper).
        A sub-location (e.g. „Терени техничари“) is a real move and allowed.
        """
        for picking in self.filtered(
                lambda p: p.picking_type_id.sequence_code == REVERSE_CODE):
            for line in (picking.move_line_ids or picking.move_ids):
                if line.location_dest_id == line.location_id:
                    raise UserError(_(
                        'Реверс %(name)s: „%(product)s“ не излегува од '
                        '„%(location)s“ — изворот и дестинацијата се исти, '
                        'па материјалот на хартија би останал во магацинот. '
                        'Избери примател (вработен, возило или партнер) со '
                        'своја локација.',
                        name=picking.name,
                        product=line.product_id.display_name,
                        location=line.location_id.complete_name))

    def button_validate(self):
        self._check_reverse_leaves_source()
        self._check_reverse_borrower_consistency()
        return super().button_validate()
