# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError
from odoo import fields
from datetime import timedelta


@tagged('post_install', '-at_install', 'eskon_reverse')
class TestReverseWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super(TestReverseWizard, cls).setUpClass()

        # Create test employee
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Тест Вработен',
        })

        # Create test partner
        cls.partner = cls.env['res.partner'].create({
            'name': 'Тест Партнер',
            'email': 'test@partner.com',
        })

        # Get warehouse and locations
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

        # Get or create Реверс picking type
        cls.picking_type = cls.env['stock.picking.type'].search([
            ('name', '=', 'Реверс'),
        ], limit=1)
        if not cls.picking_type:
            cls.picking_type = cls.env['stock.picking.type'].create({
                'name': 'Реверс',
                'code': 'internal',
                'sequence_code': 'REV',
                'warehouse_id': cls.warehouse.id,
                'default_location_src_id': cls.stock_location.id,
                'default_location_dest_id': cls.stock_location.id,
            })

        # Create test product (storable goods — реверс requires is_storable)
        cls.product = cls.env['product.product'].create({
            'name': 'Тест Бормашина',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'none',
        })

        # Create test product with lot tracking
        cls.product_tracked = cls.env['product.product'].create({
            'name': 'Тест Мултиметар',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
        })

        # Create a lot for tracked product
        cls.lot = cls.env['stock.lot'].create({
            'name': 'LOT-TEST-001',
            'product_id': cls.product_tracked.id,
            'company_id': cls.warehouse.company_id.id,
        })

        # Set default return days parameter
        cls.env['ir.config_parameter'].sudo().set_param(
            'eskon_reverse.default_return_days', '7'
        )

    # ─────────────────────────────────────────────────────────────────────
    # DEFAULT VALUES
    # ─────────────────────────────────────────────────────────────────────

    def test_01_default_borrower_type(self):
        """Default borrower_type should be 'employee'."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'return_date': fields.Date.today() + timedelta(days=7),
        })
        self.assertEqual(wizard.borrower_type, 'employee')

    def test_02_default_return_date(self):
        """Default return_date should be today + configured days."""
        wizard = self.env['eskon_reverse.wizard'].create({})
        expected = fields.Date.today() + timedelta(days=7)
        self.assertEqual(wizard.return_date, expected)

    def test_03_default_return_date_custom(self):
        """Custom default_return_days from config parameter."""
        self.env['ir.config_parameter'].sudo().set_param(
            'eskon_reverse.default_return_days', '14'
        )
        wizard = self.env['eskon_reverse.wizard'].create({})
        expected = fields.Date.today() + timedelta(days=14)
        self.assertEqual(wizard.return_date, expected)

        # Reset
        self.env['ir.config_parameter'].sudo().set_param(
            'eskon_reverse.default_return_days', '7'
        )

    # ─────────────────────────────────────────────────────────────────────
    # COMPUTED FIELDS
    # ─────────────────────────────────────────────────────────────────────

    def test_04_recipient_selected_employee(self):
        """recipient_selected should be True when employee is set."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'employee_id': self.employee.id,
        })
        self.assertTrue(wizard.recipient_selected)

    def test_05_recipient_selected_partner(self):
        """recipient_selected should be True when partner is set."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'partner',
            'partner_id': self.partner.id,
        })
        self.assertTrue(wizard.recipient_selected)

    def test_06_recipient_not_selected(self):
        """recipient_selected should be False when no recipient."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
        })
        self.assertFalse(wizard.recipient_selected)

    def test_07_source_location_computed(self):
        """Source location should be the warehouse stock location."""
        wizard = self.env['eskon_reverse.wizard'].create({})
        self.assertEqual(wizard.source_location_id, self.stock_location)

    def test_08_dest_location_employee(self):
        """Dest location should be created for employee."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'employee_id': self.employee.id,
        })
        self.assertTrue(wizard.dest_location_id)

    def test_09_dest_location_partner(self):
        """Dest location should be created for partner."""
        # Enable partner auto-create
        self.env['ir.config_parameter'].sudo().set_param(
            'eskon_reverse.auto_create_partner_location', 'True'
        )
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'partner',
            'partner_id': self.partner.id,
        })
        self.assertTrue(wizard.dest_location_id)

    def test_09b_partner_location_created_for_non_admin(self):
        """M12 guard: a normal stock USER (not a stock manager) issuing a реверс
        must still get the partner location auto-created. stock.group_stock_user
        has create=False on stock.location, so the auto-create only works because
        the provider does it with sudo() — a framework-internal side effect, not
        gated behind stock-admin rights. Without the sudo this user hits
        AccessError, it's swallowed, and dest_location_id ends up empty."""
        self.env['ir.config_parameter'].sudo().set_param(
            'eskon_reverse.auto_create_partner_location', 'True'
        )
        stock_user = self.env['res.users'].create({
            'name': 'ZZ Реверс Stock User',
            'login': 'zz_rev_stock_user',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('stock.group_stock_user').id,
            ])],
        })
        self.assertFalse(
            stock_user.has_group('stock.group_stock_manager'),
            "Test user must NOT be a stock manager (else the sudo guard is vacuous)")

        wizard = self.env['eskon_reverse.wizard'].with_user(stock_user).create({
            'borrower_type': 'partner',
            'partner_id': self.partner.id,
        })
        self.assertTrue(
            wizard.dest_location_id,
            "A non-admin stock user must get the partner location auto-created "
            "(the provider's stock.location create must be sudo'd)")

    # ─────────────────────────────────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────────────────────────────────

    def test_10_validate_no_employee(self):
        """Should raise error if employee not selected."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'line_ids': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'product_uom_id': self.product.uom_id.id,
            })],
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm()

    def test_11_validate_no_partner(self):
        """Should raise error if partner not selected."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'partner',
            'line_ids': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'product_uom_id': self.product.uom_id.id,
            })],
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm()

    def test_12_validate_no_lines(self):
        """Should raise error if no product lines."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'employee_id': self.employee.id,
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm()

    def test_13_validate_zero_qty(self):
        """Should raise error if qty is 0."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'employee_id': self.employee.id,
            'line_ids': [(0, 0, {
                'product_id': self.product.id,
                'qty': 0.0,
                'product_uom_id': self.product.uom_id.id,
            })],
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm()

    def test_14_validate_tracked_no_lot(self):
        """Should raise error if tracked product has no lot."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'employee_id': self.employee.id,
            'line_ids': [(0, 0, {
                'product_id': self.product_tracked.id,
                'qty': 1.0,
                'product_uom_id': self.product_tracked.uom_id.id,
            })],
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm()

    # ─────────────────────────────────────────────────────────────────────
    # PICKING CREATION
    # ─────────────────────────────────────────────────────────────────────

    def test_15_create_picking_employee(self):
        """Should create a picking for employee reverse."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'employee_id': self.employee.id,
            'origin': 'TEST-001',
            'line_ids': [(0, 0, {
                'product_id': self.product.id,
                'qty': 2.0,
                'product_uom_id': self.product.uom_id.id,
            })],
        })

        result = wizard.action_confirm()

        # Should return an action pointing to the created picking
        self.assertEqual(result['res_model'], 'stock.picking')
        picking = self.env['stock.picking'].browse(result['res_id'])

        self.assertEqual(picking.picking_type_id.name, 'Реверс')
        self.assertEqual(picking.borrower_type, 'employee')
        self.assertEqual(picking.origin, 'TEST-001')
        self.assertEqual(picking.return_date, wizard.return_date)
        self.assertEqual(picking.location_id, self.stock_location)
        self.assertTrue(picking.location_dest_id)
        self.assertEqual(len(picking.move_ids), 1)
        self.assertEqual(picking.move_ids.product_id, self.product)
        self.assertEqual(picking.move_ids.product_uom_qty, 2.0)
        # Should be confirmed + assigned (not done)
        self.assertIn(picking.state, ('assigned', 'confirmed', 'waiting'))

    def test_16_create_picking_partner(self):
        """Should create a picking for partner reverse."""
        self.env['ir.config_parameter'].sudo().set_param(
            'eskon_reverse.auto_create_partner_location', 'True'
        )
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'partner',
            'partner_id': self.partner.id,
            'line_ids': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'product_uom_id': self.product.uom_id.id,
            })],
        })

        result = wizard.action_confirm()
        picking = self.env['stock.picking'].browse(result['res_id'])

        self.assertEqual(picking.borrower_type, 'partner')
        self.assertEqual(picking.partner_id, self.partner)

    def test_17_create_and_validate(self):
        """action_confirm_and_validate should create done picking."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'employee_id': self.employee.id,
            'line_ids': [(0, 0, {
                'product_id': self.product.id,
                'qty': 1.0,
                'product_uom_id': self.product.uom_id.id,
            })],
        })

        result = wizard.action_confirm_and_validate()
        picking = self.env['stock.picking'].browse(result['res_id'])

        self.assertEqual(picking.state, 'done')

    def test_18_multiple_lines(self):
        """Should handle multiple product lines."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'employee_id': self.employee.id,
            'line_ids': [
                (0, 0, {
                    'product_id': self.product.id,
                    'qty': 3.0,
                    'product_uom_id': self.product.uom_id.id,
                }),
                (0, 0, {
                    'product_id': self.product_tracked.id,
                    'qty': 1.0,
                    'product_uom_id': self.product_tracked.uom_id.id,
                    'lot_id': self.lot.id,
                }),
            ],
        })

        result = wizard.action_confirm()
        picking = self.env['stock.picking'].browse(result['res_id'])

        self.assertEqual(len(picking.move_ids), 2)

    # ─────────────────────────────────────────────────────────────────────
    # WIZARD LINE
    # ─────────────────────────────────────────────────────────────────────

    def test_19_line_available_qty(self):
        """Available qty should reflect stock at source location."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'employee_id': self.employee.id,
        })
        line = self.env['eskon_reverse.wizard.line'].create({
            'wizard_id': wizard.id,
            'product_id': self.product.id,
            'qty': 1.0,
            'product_uom_id': self.product.uom_id.id,
        })
        # available_qty is computed — it should return a float (>=0)
        self.assertIsInstance(line.available_qty, float)

    def test_20_line_status_no_stock(self):
        """Line status should be no_stock when available_qty is 0."""
        wizard = self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'employee_id': self.employee.id,
        })
        line = self.env['eskon_reverse.wizard.line'].create({
            'wizard_id': wizard.id,
            'product_id': self.product.id,
            'qty': 999999.0,
            'product_uom_id': self.product.uom_id.id,
        })
        # With no stock, status should be no_stock or partial
        self.assertIn(line.status, ('no_stock', 'partial'))

    # ─────────────────────────────────────────────────────────────────────
    # H1 — реверс requires STORABLE products (else no quant -> empty tracking)
    # ─────────────────────────────────────────────────────────────────────

    def _employee_wizard(self, product, qty=1.0):
        return self.env['eskon_reverse.wizard'].create({
            'borrower_type': 'employee',
            'employee_id': self.employee.id,
            'return_date': fields.Date.today() + timedelta(days=7),
            'line_ids': [(0, 0, {
                'product_id': product.id,
                'qty': qty,
                'product_uom_id': product.uom_id.id,
            })],
        })

    def test_30_non_storable_product_rejected(self):
        """A non-storable 'consu' product creates NO quant on validation, so the
        реверс would silently track nothing. _validate_wizard must reject it."""
        non_storable = self.env['product.product'].create({
            'name': 'Тест Нескладиштива', 'type': 'consu', 'is_storable': False,
        })
        wizard = self._employee_wizard(non_storable)
        with self.assertRaises(ValidationError):
            wizard.action_confirm()

    def test_31_storable_reverse_creates_destination_quant(self):
        """Positive postcondition: issuing a STORABLE product via реверс leaves a
        quant at the borrower's location — what the stat button / 'Опрема кај
        вработени' report actually read."""
        storable = self.env['product.product'].create({
            'name': 'Тест Складиштива Бормашина', 'type': 'consu', 'is_storable': True,
        })
        self.env['stock.quant']._update_available_quantity(
            storable, self.stock_location, 5.0)
        wizard = self._employee_wizard(storable, qty=2.0)
        dest = wizard.dest_location_id
        self.assertTrue(dest, "Borrower (employee) location must resolve")

        wizard.action_confirm_and_validate()

        quant = self.env['stock.quant'].search([
            ('product_id', '=', storable.id),
            ('location_id', '=', dest.id),
            ('quantity', '>', 0),
        ])
        self.assertTrue(
            quant, "A storable реверс must leave a quant at the borrower's location")
        self.assertEqual(sum(quant.mapped('quantity')), 2.0)
