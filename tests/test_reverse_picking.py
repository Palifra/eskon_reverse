# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged
from odoo import fields
from datetime import timedelta, date


@tagged('post_install', '-at_install', 'eskon_reverse')
class TestReversePicking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super(TestReversePicking, cls).setUpClass()

        # Create test partner
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Partner',
            'email': 'test@partner.com',
        })

        # Get warehouse and stock location
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

        # Get or create reverse picking type
        cls.picking_type = cls.env['stock.picking.type'].search([
            ('name', '=', 'Реверс')
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

        # Get Partners parent location
        cls.partners_location = cls.env.ref(
            'eskon_reverse.stock_location_partners',
            raise_if_not_found=False
        )

    def test_01_return_date_future(self):
        """Test days_until_return calculation for future date"""
        return_date = fields.Date.today() + timedelta(days=5)

        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'return_date': return_date,
        })

        self.assertEqual(picking.days_until_return, 5)
        self.assertFalse(picking.is_overdue)

    def test_02_return_date_today(self):
        """Test days_until_return for today's date"""
        return_date = fields.Date.today()

        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'return_date': return_date,
        })

        self.assertEqual(picking.days_until_return, 0)
        self.assertFalse(picking.is_overdue)

    def test_03_return_date_past_overdue(self):
        """Test is_overdue flag for past date"""
        return_date = fields.Date.today() - timedelta(days=3)

        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'return_date': return_date,
        })

        self.assertEqual(picking.days_until_return, -3)
        self.assertTrue(picking.is_overdue)

    def test_04_no_return_date(self):
        """Test when no return date is set"""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
        })

        self.assertEqual(picking.days_until_return, 0)
        self.assertFalse(picking.is_overdue)

    def test_05_borrower_type_default(self):
        """Test default borrower type is employee"""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
        })

        self.assertEqual(picking.borrower_type, 'employee')

    def test_06_borrower_type_partner(self):
        """Test setting borrower type to partner"""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'borrower_type': 'partner',
            'partner_id': self.partner.id,
        })

        self.assertEqual(picking.borrower_type, 'partner')
        self.assertEqual(picking.partner_id, self.partner)

    def test_07_reminder_sent_default(self):
        """Test reminder_sent defaults to False"""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
        })

        self.assertFalse(picking.reminder_sent)

    def test_08_reminder_sent_not_copied(self):
        """Test reminder_sent is not copied when duplicating picking"""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'reminder_sent': True,
        })

        copied_picking = picking.copy()
        self.assertFalse(copied_picking.reminder_sent)

    def test_09_partner_location_creation(self):
        """Test automatic creation of partner location"""
        if not self.partners_location:
            self.skipTest("Partners location not found")

        new_partner = self.env['res.partner'].create({
            'name': 'New Test Partner',
        })

        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
        })

        partner_loc = picking._get_or_create_partner_location(new_partner)

        self.assertTrue(partner_loc)
        self.assertEqual(partner_loc.name, 'New Test Partner')
        self.assertEqual(partner_loc.location_id, self.partners_location)
        self.assertEqual(partner_loc.usage, 'internal')

    def test_10_partner_location_reuse(self):
        """Test that existing partner location is reused"""
        if not self.partners_location:
            self.skipTest("Partners location not found")

        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
        })

        # Create first time
        loc1 = picking._get_or_create_partner_location(self.partner)
        # Call again - should return same location
        loc2 = picking._get_or_create_partner_location(self.partner)

        self.assertEqual(loc1, loc2)
        self.assertEqual(loc1.id, loc2.id)

    def test_11_cron_sends_reminders(self):
        """Test cron job creates activities for upcoming returns"""
        # Ensure picking type has correct name
        self.picking_type.write({'name': 'Реверс'})

        # Set return date to 3 days from now (when reminder should be sent)
        return_date = fields.Date.today() + timedelta(days=3)

        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'partner_id': self.partner.id,
            'return_date': return_date,
        })
        # Force state to done (bypassing normal workflow for test)
        picking.write({'state': 'done'})

        # Run cron
        self.env['stock.picking']._cron_send_return_reminders()

        # Reload picking to get updated values
        picking.invalidate_recordset()

        # Check reminder was sent
        self.assertTrue(picking.reminder_sent)

        # Check activity was created
        activity = self.env['mail.activity'].search([
            ('res_model', '=', 'stock.picking'),
            ('res_id', '=', picking.id),
            ('summary', 'ilike', 'враќање'),
        ])
        self.assertTrue(activity)

    def test_12_cron_skips_already_reminded(self):
        """Test cron skips pickings already reminded"""
        # Ensure picking type has correct name
        self.picking_type.write({'name': 'Реверс'})

        return_date = fields.Date.today() + timedelta(days=3)

        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'partner_id': self.partner.id,
            'return_date': return_date,
            'reminder_sent': True,  # Already sent
        })
        picking.write({'state': 'done'})

        initial_activities = self.env['mail.activity'].search_count([
            ('res_model', '=', 'stock.picking'),
            ('res_id', '=', picking.id),
        ])

        # Run cron
        self.env['stock.picking']._cron_send_return_reminders()

        final_activities = self.env['mail.activity'].search_count([
            ('res_model', '=', 'stock.picking'),
            ('res_id', '=', picking.id),
        ])

        # No new activity should be created
        self.assertEqual(initial_activities, final_activities)

    def test_13_cron_creates_overdue_activity(self):
        """Test cron creates urgent activity for overdue pickings"""
        # Ensure picking type has correct name
        self.picking_type.write({'name': 'Реверс'})

        return_date = fields.Date.today() - timedelta(days=5)

        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'return_date': return_date,
        })
        picking.write({'state': 'done'})

        # Run cron
        self.env['stock.picking']._cron_send_return_reminders()

        # Check overdue activity was created
        activity = self.env['mail.activity'].search([
            ('res_model', '=', 'stock.picking'),
            ('res_id', '=', picking.id),
            ('summary', 'ilike', 'ЗАДОЦНЕТО'),
        ])
        self.assertTrue(activity)

    def test_14_cron_returns_true(self):
        """Test cron method returns True"""
        result = self.env['stock.picking']._cron_send_return_reminders()
        self.assertTrue(result)

    def test_15_multiple_pickings_computation(self):
        """Test computed fields work correctly for multiple pickings"""
        dates = [
            fields.Date.today() + timedelta(days=10),
            fields.Date.today() - timedelta(days=2),
            fields.Date.today(),
        ]

        pickings = self.env['stock.picking']
        for return_date in dates:
            pickings |= self.env['stock.picking'].create({
                'picking_type_id': self.picking_type.id,
                'location_id': self.stock_location.id,
                'location_dest_id': self.stock_location.id,
                'return_date': return_date,
            })

        self.assertEqual(pickings[0].days_until_return, 10)
        self.assertFalse(pickings[0].is_overdue)

        self.assertEqual(pickings[1].days_until_return, -2)
        self.assertTrue(pickings[1].is_overdue)

        self.assertEqual(pickings[2].days_until_return, 0)
        self.assertFalse(pickings[2].is_overdue)
