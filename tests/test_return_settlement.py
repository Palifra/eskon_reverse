# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged
from odoo import fields
from datetime import timedelta


@tagged('post_install', '-at_install', 'eskon_reverse')
class TestReturnSettlement(TransactionCase):
    """H2/M3/M4/M5/M6 — a реверс closes when the equipment is physically back.
    Settlement = the issued products no longer on-hand at the destination
    (resource) location, by ANY return path. Drives is_returned/is_overdue and
    the reminder/overdue cron."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        cls.rev_type = cls.env['stock.picking.type'].search([
            ('sequence_code', '=', 'REV'),
            ('warehouse_id', '=', cls.warehouse.id),
        ], limit=1)
        if not cls.rev_type:
            cls.rev_type = cls.env['stock.picking.type'].create({
                'name': 'Реверс', 'code': 'internal', 'sequence_code': 'REV',
                'warehouse_id': cls.warehouse.id,
                'default_location_src_id': cls.stock_loc.id,
                'default_location_dest_id': cls.stock_loc.id,
            })
        # A destination resource location.
        cls.dest = cls.env['stock.location'].create({
            'name': 'H2 Resource Loc', 'usage': 'internal',
            'location_id': cls.stock_loc.location_id.id,
            'company_id': cls.warehouse.company_id.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'H2 Equipment', 'type': 'consu', 'is_storable': True})

    # ── helpers ──────────────────────────────────────────────────────────
    def _issue_reverse(self, qty, return_date=None):
        """Create + validate a реверс moving `qty` of product stock→dest."""
        self.env['stock.quant']._update_available_quantity(
            self.product, self.stock_loc, qty)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.rev_type.id,
            'location_id': self.stock_loc.id,
            'location_dest_id': self.dest.id,
            'return_date': return_date,
        })
        self.env['stock.move'].create({
            'name': 'H2 issue', 'picking_id': picking.id,
            'product_id': self.product.id, 'product_uom_qty': qty,
            'product_uom': self.product.uom_id.id,
            'location_id': self.stock_loc.id, 'location_dest_id': self.dest.id,
        })
        picking.action_confirm()
        picking.action_assign()
        for ml in picking.move_ids.move_line_ids:
            ml.quantity = qty
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        return picking

    def _return_qty(self, qty):
        """Simulate a return: move `qty` of product dest → warehouse stock."""
        self.env['stock.quant']._update_available_quantity(
            self.product, self.dest, -qty)
        self.env['stock.quant']._update_available_quantity(
            self.product, self.stock_loc, qty)

    def _overdue_activities(self, picking):
        return self.env['mail.activity'].search([
            ('res_model', '=', 'stock.picking'),
            ('res_id', '=', picking.id),
            ('summary', 'ilike', 'ЗАДОЦНЕТО'),
        ])

    # ── tests ────────────────────────────────────────────────────────────
    def test_01_issued_reverse_is_outstanding(self):
        p = self._issue_reverse(5)
        self.assertEqual(p.outstanding_qty, 5)
        self.assertFalse(p.is_returned)

    def test_02_full_return_settles_and_clears_overdue(self):
        p = self._issue_reverse(5, return_date=fields.Date.today() - timedelta(days=2))
        self.assertTrue(p.is_overdue, "past-due, not yet returned → overdue")
        self._return_qty(5)
        p.invalidate_recordset()
        self.assertEqual(p.outstanding_qty, 0)
        self.assertTrue(p.is_returned, "dest emptied → returned")
        self.assertFalse(p.is_overdue, "a settled реверс must not be overdue (M4)")

    def test_03_partial_return_stays_outstanding(self):
        p = self._issue_reverse(6)
        self._return_qty(4)
        p.invalidate_recordset()
        self.assertEqual(p.outstanding_qty, 2)
        self.assertFalse(p.is_returned)

    def test_04_overdue_cron_skips_settled(self):
        p = self._issue_reverse(3, return_date=fields.Date.today() - timedelta(days=5))
        self._return_qty(3)  # settled
        p.invalidate_recordset()
        self.env['stock.picking']._cron_send_return_reminders()
        self.assertFalse(
            self._overdue_activities(p),
            "no overdue activity for a settled (returned) реверс (the live H2 bug)")

    def test_05_overdue_cron_fires_once_no_respawn(self):
        p = self._issue_reverse(3, return_date=fields.Date.today() - timedelta(days=5))
        self.env['stock.picking']._cron_send_return_reminders()
        p.invalidate_recordset()
        self.assertTrue(p.overdue_notified)
        acts = self._overdue_activities(p)
        self.assertEqual(len(acts), 1)
        acts.action_done()  # user marks it Done → Odoo unlinks the activity
        self.env['stock.picking']._cron_send_return_reminders()
        self.assertEqual(
            len(self._overdue_activities(p)), 0,
            "overdue activity must NOT respawn after Done (M6 — stored flag)")

    def test_06_reminder_threshold_window(self):
        p_in = self._issue_reverse(2, return_date=fields.Date.today() + timedelta(days=2))
        p_out = self._issue_reverse(2, return_date=fields.Date.today() + timedelta(days=5))
        self.env['stock.picking']._cron_send_return_reminders()
        p_in.invalidate_recordset()
        p_out.invalidate_recordset()
        self.assertTrue(
            p_in.reminder_sent, "реверс due in 2 days must be reminded (threshold, M5)")
        self.assertFalse(
            p_out.reminder_sent, "реверс due in 5 days must NOT be reminded yet")

    def test_08_outstanding_counts_child_locations(self):
        """If the picking dest is a parent/view location but the stock sits in
        an internal child, outstanding must still see it (child_of, not =)."""
        parent = self.env['stock.location'].create({
            'name': 'H2 Parent Dest', 'usage': 'view',
            'location_id': self.stock_loc.location_id.id,
            'company_id': self.warehouse.company_id.id})
        child = self.env['stock.location'].create({
            'name': 'H2 Child Dest', 'usage': 'internal',
            'location_id': parent.id, 'company_id': self.warehouse.company_id.id})
        self.env['stock.quant']._update_available_quantity(
            self.product, self.stock_loc, 3)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.rev_type.id,
            'location_id': self.stock_loc.id,
            'location_dest_id': parent.id,  # header = the VIEW parent
        })
        self.env['stock.move'].create({
            'name': 'H2 child issue', 'picking_id': picking.id,
            'product_id': self.product.id, 'product_uom_qty': 3,
            'product_uom': self.product.uom_id.id,
            'location_id': self.stock_loc.id, 'location_dest_id': child.id})  # → child
        picking.action_confirm()
        picking.action_assign()
        for ml in picking.move_ids.move_line_ids:
            ml.quantity = 3
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(
            picking.outstanding_qty, 3,
            "outstanding must count quants in child locations of a view dest")
        self.assertFalse(picking.is_returned)

    def test_09_outstanding_respects_uom(self):
        """Outstanding compares the move-line qty in the PRODUCT uom, not the
        line uom — a реверс issued in dozens of a units-product reads 12, not 1."""
        uom_unit = self.env.ref('uom.product_uom_unit')
        uom_dozen = self.env.ref('uom.product_uom_dozen')
        prod = self.env['product.product'].create({
            'name': 'H2 UoM Equipment', 'type': 'consu', 'is_storable': True,
            'uom_id': uom_unit.id, 'uom_po_id': uom_unit.id})
        self.env['stock.quant']._update_available_quantity(prod, self.stock_loc, 24)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.rev_type.id,
            'location_id': self.stock_loc.id,
            'location_dest_id': self.dest.id,
        })
        self.env['stock.move'].create({
            'name': 'H2 dozen issue', 'picking_id': picking.id,
            'product_id': prod.id, 'product_uom_qty': 1, 'product_uom': uom_dozen.id,
            'location_id': self.stock_loc.id, 'location_dest_id': self.dest.id})
        picking.action_confirm()
        picking.action_assign()
        for ml in picking.move_ids.move_line_ids:
            ml.quantity = 1  # 1 dozen
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(
            picking.outstanding_qty, 12,
            "outstanding must use product-uom quantity (12), not the line uom (1)")

    def test_07_native_return_still_flips_is_returned(self):
        """Back-compat: a done native return marks is_returned even if the dest
        still holds stock (the 1 prod record that uses the native Return button)."""
        p = self._issue_reverse(4)
        self.assertFalse(p.is_returned)
        ret = self.env['stock.picking'].create({
            'picking_type_id': self.rev_type.id,
            'location_id': self.dest.id,
            'location_dest_id': self.stock_loc.id,
            'return_id': p.id,
        })
        ret.write({'state': 'done'})
        p.invalidate_recordset()
        self.assertTrue(
            p.is_returned, "a done native return must flip is_returned (back-compat)")
