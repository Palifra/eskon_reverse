# -*- coding: utf-8 -*-
import base64
from odoo.tests import TransactionCase, tagged
from odoo import fields


@tagged('post_install', '-at_install', 'eskon_reverse')
class TestReverseDocument(TransactionCase):
    """M2 — the реверс as a signed legal handover document: an explicit issuer,
    dual acceptance signatures (Издал/Примил) with auto-stamped dates, and a
    printable QWeb report."""

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
        cls.partner = cls.env['res.partner'].create({
            'name': 'Док Тест Партнер', 'is_company': False})
        cls.product = cls.env['product.product'].create({
            'name': 'Док Опрема', 'type': 'consu', 'is_storable': True})

    def _reverse_picking(self):
        p = self.env['stock.picking'].create({
            'picking_type_id': self.rev_type.id,
            'location_id': self.stock_loc.id,
            'location_dest_id': self.stock_loc.id,
            'borrower_type': 'partner',
            'partner_id': self.partner.id,
            'return_date': fields.Date.today(),
        })
        self.env['stock.move'].create({
            'name': self.product.display_name, 'picking_id': p.id,
            'product_id': self.product.id, 'product_uom_qty': 2,
            'product_uom': self.product.uom_id.id,
            'location_id': self.stock_loc.id, 'location_dest_id': self.stock_loc.id})
        return p

    def test_01_issuer_defaults_to_current_user(self):
        p = self._reverse_picking()
        self.assertEqual(p.issuer_id, self.env.user)

    def test_02_borrower_signature_date_stamped_on_capture(self):
        p = self._reverse_picking()
        self.assertFalse(p.borrower_signature_date)
        p.write({'borrower_signature': base64.b64encode(b'borrower-sig')})
        self.assertTrue(
            p.borrower_signature_date, "capturing a signature must stamp its date")
        # clearing the signature clears the date
        p.write({'borrower_signature': False})
        self.assertFalse(p.borrower_signature_date)

    def test_03_issuer_signature_date_stamped(self):
        p = self._reverse_picking()
        self.assertFalse(p.issuer_signature_date)
        p.write({'issuer_signature': base64.b64encode(b'issuer-sig')})
        self.assertTrue(p.issuer_signature_date)

    def test_04_qweb_report_renders_with_key_data(self):
        p = self._reverse_picking()
        html, rtype = self.env['ir.actions.report']._render_qweb_html(
            'eskon_reverse.action_report_reverse', p.ids)
        content = html.decode() if isinstance(html, bytes) else html
        self.assertEqual(rtype, 'html')
        self.assertIn('РЕВЕРС', content)
        self.assertIn(self.partner.name, content, "borrower must appear on the document")
        self.assertIn(self.product.display_name, content, "equipment must be listed")
        self.assertIn('ИЗДАЛ', content)
        self.assertIn('ПРИМИЛ', content)

    def test_05_signature_image_renders_in_report(self):
        """A captured signature must render as an inline image in the report
        (exercises the image_data_uri branch)."""
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (4, 2), (0, 0, 0)).save(buf, format='PNG')
        png_b64 = base64.b64encode(buf.getvalue())
        p = self._reverse_picking()
        p.write({'borrower_signature': png_b64})
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'eskon_reverse.action_report_reverse', p.ids)
        content = html.decode() if isinstance(html, bytes) else html
        self.assertIn('<img', content, "a captured signature must render as an image")
        self.assertIn('data:image', content, "signature must be an inline data-URI image")
