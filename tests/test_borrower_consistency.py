# -*- coding: utf-8 -*-
"""Реверс: примател (partner_id) и дестинација на линијата мора да се истата личност.

Дизајн: docs/plans/2026-10-21-reverse-borrower-location-consistency-design.md
Пристап А — податокот се ИЗВЕДУВА од другата страна, никогаш не се претпоставува.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eskon_reverse')
class TestBorrowerConsistency(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        PT = cls.env['stock.picking.type']
        cls.rev_type = PT._eskon_reverse_type('reverse', cls.warehouse)
        cls.ret_type = PT._eskon_reverse_type('return', cls.warehouse)

        cls.emp_a = cls.env['hr.employee'].create({'name': 'Александар Тест БК'})
        cls.emp_b = cls.env['hr.employee'].create({'name': 'Ивица Тест БК'})
        assert cls.emp_a.stock_location_id and cls.emp_b.stock_location_id
        assert cls.emp_a.work_contact_id and cls.emp_b.work_contact_id

        cls.outsider = cls.env['res.partner'].create({'name': 'Надворешен Контакт БК'})
        cls.plain_location = cls.env['stock.location'].create({
            'name': 'Обична БК', 'usage': 'internal',
            'location_id': cls.stock_location.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Димер БК', 'type': 'consu', 'is_storable': True,
        })
        cls.env['stock.quant']._update_available_quantity(
            cls.product, cls.stock_location, 10.0)

    # ── helpers ──────────────────────────────────────────────────────────

    def _picking(self, ptype, src, dest, partner=False, borrower_type='employee', qty=1.0):
        pk = self.env['stock.picking'].create({
            'picking_type_id': ptype.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'partner_id': partner.id if partner else False,
            'borrower_type': borrower_type,
            'move_ids': [(0, 0, {
                'name': self.product.name,
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'product_uom': self.product.uom_id.id,
                'location_id': src.id,
                'location_dest_id': dest.id,
            })],
        })
        pk.action_confirm()
        pk.action_assign()
        pk.move_ids.picked = True
        return pk

    def _new_rev(self, **vals):
        base = {
            'picking_type_id': self.rev_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.rev_type.default_location_dest_id.id,
            'borrower_type': 'employee',
        }
        base.update(vals)
        return self.env['stock.picking'].new(base)

    # ── onchange: партнер → локација ────────────────────────────────────

    def test_onchange_employee_partner_sets_destination(self):
        pk = self._new_rev(partner_id=self.emp_b.work_contact_id.id)
        pk._onchange_borrower_partner()
        self.assertEqual(pk.location_dest_id, self.emp_b.stock_location_id)

    def test_onchange_non_employee_partner_warns_and_keeps_destination(self):
        dest_before = self.rev_type.default_location_dest_id
        pk = self._new_rev(partner_id=self.outsider.id)
        res = pk._onchange_borrower_partner()
        self.assertTrue(res and res.get('warning'), "очекувано предупредување „не е вработен“")
        self.assertEqual(pk.location_dest_id, dest_before)

    # ── onchange: локација → партнер ────────────────────────────────────

    def test_onchange_employee_destination_fills_empty_partner(self):
        pk = self._new_rev(location_dest_id=self.emp_a.stock_location_id.id)
        pk._onchange_borrower_dest_location()
        self.assertEqual(pk.partner_id, self.emp_a.work_contact_id)

    # ── validate: server-side ───────────────────────────────────────────

    def test_validate_mismatch_raises_with_both_names(self):
        pk = self._picking(self.rev_type, self.stock_location,
                           self.emp_a.stock_location_id,
                           partner=self.emp_b.work_contact_id)
        with self.assertRaises(UserError) as cm:
            pk.button_validate()
        msg = str(cm.exception)
        self.assertIn(self.emp_b.work_contact_id.name, msg)
        self.assertIn(self.emp_a.name, msg)
        self.assertNotEqual(pk.state, 'done')

    def test_validate_empty_partner_is_filled_from_destination(self):
        pk = self._picking(self.rev_type, self.stock_location,
                           self.emp_a.stock_location_id, partner=False)
        pk.button_validate()
        self.assertEqual(pk.state, 'done')
        self.assertEqual(pk.partner_id, self.emp_a.work_contact_id)

    def test_validate_matching_partner_passes(self):
        pk = self._picking(self.rev_type, self.stock_location,
                           self.emp_a.stock_location_id,
                           partner=self.emp_a.work_contact_id)
        pk.button_validate()
        self.assertEqual(pk.state, 'done')
        self.assertEqual(pk.partner_id, self.emp_a.work_contact_id)

    def test_validate_return_picking_is_untouched(self):
        # прво издај кај emp_a, потоа повратница со произволен примател
        issue = self._picking(self.rev_type, self.stock_location,
                              self.emp_a.stock_location_id,
                              partner=self.emp_a.work_contact_id)
        issue.button_validate()
        ret = self._picking(self.ret_type, self.emp_a.stock_location_id,
                            self.stock_location, partner=self.outsider)
        ret.button_validate()
        self.assertEqual(ret.state, 'done')
        self.assertEqual(ret.partner_id, self.outsider)

    def test_validate_non_employee_destination_is_untouched(self):
        pk = self._picking(self.rev_type, self.stock_location,
                           self.plain_location, partner=self.outsider)
        pk.button_validate()
        self.assertEqual(pk.state, 'done')
        self.assertEqual(pk.partner_id, self.outsider)
