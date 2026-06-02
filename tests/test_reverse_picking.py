# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError
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

    def test_09_partner_onchange_routes_through_provider(self):
        """The partner onchange must resolve location_dest_id through the central
        Location Provider (sudo'd, company-scoped, gated) — not a hand-rolled
        Location.create. The dest lands under the Партнери parent and inherits
        the parent's company (L3/L6 — the old onchange path set no company_id)."""
        if not self.partners_location:
            self.skipTest("Partners location not found")
        self.env['ir.config_parameter'].sudo().set_param(
            'eskon_reverse.auto_create_partner_location', 'True')

        new_partner = self.env['res.partner'].create({'name': 'Onchange Partner'})
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'borrower_type': 'partner',
            'partner_id': new_partner.id,
        })
        picking._onchange_borrower_partner()

        loc = picking.location_dest_id
        self.assertTrue(loc, "onchange must set a partner destination location")
        self.assertEqual(loc.name, 'Onchange Partner')
        self.assertEqual(loc.location_id, self.partners_location)
        self.assertEqual(loc.usage, 'internal')
        self.assertEqual(
            loc.company_id, self.partners_location.company_id,
            "provider must stamp company from the parent location (L3/L6)")

    def test_09b_partner_onchange_respects_disabled_gate(self):
        """L2: with auto_create_partner_location disabled, the onchange must NOT
        create a partner location (the old hand-rolled path ignored the gate and
        always created, littering the Партнери hierarchy)."""
        if not self.partners_location:
            self.skipTest("Partners location not found")
        self.env['ir.config_parameter'].sudo().set_param(
            'eskon_reverse.auto_create_partner_location', 'False')

        gated_partner = self.env['res.partner'].create({'name': 'Gated Partner'})
        domain = [
            ('name', '=', 'Gated Partner'),
            ('location_id', '=', self.partners_location.id),
        ]
        before = self.env['stock.location'].search_count(domain)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'borrower_type': 'partner',
            'partner_id': gated_partner.id,
        })
        picking._onchange_borrower_partner()

        after = self.env['stock.location'].search_count(domain)
        self.assertEqual(
            before, after,
            "a disabled gate must prevent partner-location creation in the onchange")

    def test_09c_partner_onchange_works_for_non_admin(self):
        """M12: the partner onchange routes through the sudo'd provider, so a
        normal stock USER (create=False on stock.location) editing a Реверс
        picking no longer crashes with AccessError on location create. The old
        hand-rolled Location.create (no sudo, no try/except) raised for any
        non-manager — see the analytic-account/viber sudo lessons."""
        if not self.partners_location:
            self.skipTest("Partners location not found")
        self.env['ir.config_parameter'].sudo().set_param(
            'eskon_reverse.auto_create_partner_location', 'True')

        stock_user = self.env['res.users'].create({
            'name': 'ZZ Реверс Picking Stock User',
            'login': 'zz_rev_pick_stock_user',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('stock.group_stock_user').id,
            ])],
        })
        self.assertFalse(
            stock_user.has_group('stock.group_stock_manager'),
            "Test user must NOT be a stock manager (else the sudo guard is vacuous)")

        nonadmin_partner = self.env['res.partner'].create({'name': 'NonAdmin Onchange Partner'})
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'borrower_type': 'partner',
            'partner_id': nonadmin_partner.id,
        })
        picking_as_user = picking.with_user(stock_user)
        # OLD code raises AccessError inside the onchange here; NEW code sudo's
        # the location create through the provider.
        picking_as_user._onchange_borrower_partner()
        self.assertTrue(
            picking_as_user.location_dest_id,
            "a non-admin stock user must get the partner dest via the sudo'd provider")

    def test_10_partner_onchange_reuses_existing_location(self):
        """Idempotency: calling the onchange twice for the same partner reuses
        the same location (the provider dedups), never a duplicate."""
        if not self.partners_location:
            self.skipTest("Partners location not found")
        self.env['ir.config_parameter'].sudo().set_param(
            'eskon_reverse.auto_create_partner_location', 'True')

        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'borrower_type': 'partner',
            'partner_id': self.partner.id,
        })
        picking._onchange_borrower_partner()
        loc1 = picking.location_dest_id
        picking._onchange_borrower_partner()
        loc2 = picking.location_dest_id

        self.assertTrue(loc1)
        self.assertEqual(loc1, loc2)

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


@tagged('post_install', '-at_install', 'eskon_reverse')
class TestReverseTypeIdentity(TransactionCase):
    """H3 — Реверс/Повратница picking-type identity must be stable under
    translation/rename (matched on non-translatable ``sequence_code``,
    NOT the translatable display name)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.company = cls.warehouse.company_id
        cls.stock_location = cls.warehouse.lot_stock_id

        # Resolve (or create) the Реверс ('REV') type for the warehouse.
        cls.reverse_type = cls.env['stock.picking.type'].search([
            ('sequence_code', '=', 'REV'),
            ('warehouse_id', '=', cls.warehouse.id),
        ], limit=1)
        if not cls.reverse_type:
            cls.reverse_type = cls.env['stock.picking.type'].create({
                'name': 'Реверс',
                'code': 'internal',
                'sequence_code': 'REV',
                'warehouse_id': cls.warehouse.id,
                'default_location_src_id': cls.stock_location.id,
                'default_location_dest_id': cls.stock_location.id,
            })

        # Resolve (or create) the Повратница ('REV-RET') type for the warehouse.
        cls.return_type = cls.env['stock.picking.type'].search([
            ('sequence_code', '=', 'REV-RET'),
            ('warehouse_id', '=', cls.warehouse.id),
        ], limit=1)
        if not cls.return_type:
            cls.return_type = cls.env['stock.picking.type'].create({
                'name': 'Повратница',
                'code': 'internal',
                'sequence_code': 'REV-RET',
                'warehouse_id': cls.warehouse.id,
                'default_location_src_id': cls.stock_location.id,
                'default_location_dest_id': cls.stock_location.id,
            })

    # ──────────────────────────────────────────────────────────────────
    # 1. Translation-proof regression (the crown jewel)
    # ──────────────────────────────────────────────────────────────────

    def test_identity_survives_type_rename(self):
        """Renaming the picking type's display name (simulating a translation
        pass) must NOT break реверс identity: ``is_reverse_picking`` stays True,
        both crons still find it, and ``_eskon_reverse_type`` still resolves it."""
        return_date = fields.Date.today() + timedelta(days=3)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.reverse_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'partner_id': self.env['res.partner'].create({
                'name': 'Rename Test Partner',
                'email': 'rename@test.com',
            }).id,
            'return_date': return_date,
        })
        picking.write({'state': 'done'})

        # Sanity before the rename.
        self.assertTrue(picking.is_reverse_picking)

        # Simulate a translation/rename of the type's display name.
        self.reverse_type.write({'name': 'Borrowing (renamed)'})
        picking.invalidate_recordset()

        # 1a — the stored-flag compute still classifies it as реверс.
        self.assertTrue(
            picking.is_reverse_picking,
            "is_reverse_picking must survive a display-name rename "
            "(matched on sequence_code, not name)")

        # 1b — the reminder cron (3-days-out) still finds and reminds it.
        self.env['stock.picking']._cron_send_return_reminders()
        picking.invalidate_recordset()
        self.assertTrue(
            picking.reminder_sent,
            "reminder cron must still match the renamed type via sequence_code")

        # 1c — the overdue cron still flags an overdue реверс after rename.
        overdue = self.env['stock.picking'].create({
            'picking_type_id': self.reverse_type.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.stock_location.id,
            'return_date': fields.Date.today() - timedelta(days=5),
        })
        overdue.write({'state': 'done'})
        self.env['stock.picking']._cron_send_return_reminders()
        activity = self.env['mail.activity'].search([
            ('res_model', '=', 'stock.picking'),
            ('res_id', '=', overdue.id),
            ('summary', 'ilike', 'ЗАДОЦНЕТО'),
        ])
        self.assertTrue(
            activity,
            "overdue cron must still match the renamed type via sequence_code")

        # 1d — the resolver still resolves a fresh issue/return for the warehouse.
        resolved_rev = self.env['stock.picking.type']._eskon_reverse_type(
            'reverse', self.warehouse)
        self.assertEqual(resolved_rev, self.reverse_type)
        resolved_ret = self.env['stock.picking.type']._eskon_reverse_type(
            'return', self.warehouse)
        self.assertEqual(resolved_ret, self.return_type)

    # ──────────────────────────────────────────────────────────────────
    # 2. Raise-on-missing (no silent fallback, no auto-create)
    # ──────────────────────────────────────────────────────────────────

    def test_resolver_raises_when_reverse_type_missing(self):
        """A warehouse with no 'REV' type → resolver raises UserError."""
        bare_wh = self.env['stock.warehouse'].create({
            'name': 'H3 Bare WH No REV',
            'code': 'H3NB',
            'company_id': self.company.id,
        })
        # A freshly-created warehouse gets standard in/out/internal types but
        # NO Реверс/Повратница types — those are eskon_reverse-specific.
        self.env['stock.picking.type'].search([
            ('warehouse_id', '=', bare_wh.id),
            ('sequence_code', 'in', ('REV', 'REV-RET')),
        ]).unlink()
        with self.assertRaises(UserError):
            self.env['stock.picking.type']._eskon_reverse_type('reverse', bare_wh)

    def test_resolver_raises_when_return_type_missing(self):
        """A warehouse with no 'REV-RET' type → resolver raises UserError."""
        bare_wh = self.env['stock.warehouse'].create({
            'name': 'H3 Bare WH No REVRET',
            'code': 'H3NR',
            'company_id': self.company.id,
        })
        self.env['stock.picking.type'].search([
            ('warehouse_id', '=', bare_wh.id),
            ('sequence_code', 'in', ('REV', 'REV-RET')),
        ]).unlink()
        with self.assertRaises(UserError):
            self.env['stock.picking.type']._eskon_reverse_type('return', bare_wh)

    def test_resolver_raises_when_warehouse_empty(self):
        """An empty stock.warehouse recordset → resolver raises a clean
        UserError at the single choke point (rather than building a confusing
        ('warehouse_id', '=', False) domain with an empty display name)."""
        with self.assertRaises(UserError):
            self.env['stock.picking.type']._eskon_reverse_type(
                'reverse', self.env['stock.warehouse'])

    # ──────────────────────────────────────────────────────────────────
    # 3. Per-warehouse resolution (M-INT-3 duplicate-type selection)
    # ──────────────────────────────────────────────────────────────────

    def test_resolver_returns_requested_warehouse_type(self):
        """Two warehouses each with a 'REV' type → resolver returns the
        requested warehouse's type, never the other's."""
        other_wh = self.env['stock.warehouse'].create({
            'name': 'H3 Other WH',
            'code': 'H3OW',
            'company_id': self.company.id,
        })
        other_rev = self.env['stock.picking.type'].search([
            ('sequence_code', '=', 'REV'),
            ('warehouse_id', '=', other_wh.id),
        ], limit=1)
        if not other_rev:
            other_rev = self.env['stock.picking.type'].create({
                'name': 'Реверс',
                'code': 'internal',
                'sequence_code': 'REV',
                'warehouse_id': other_wh.id,
                'default_location_src_id': other_wh.lot_stock_id.id,
                'default_location_dest_id': other_wh.lot_stock_id.id,
            })

        resolved_here = self.env['stock.picking.type']._eskon_reverse_type(
            'reverse', self.warehouse)
        resolved_other = self.env['stock.picking.type']._eskon_reverse_type(
            'reverse', other_wh)

        self.assertEqual(resolved_here, self.reverse_type)
        self.assertEqual(resolved_other, other_rev)
        self.assertNotEqual(resolved_here, resolved_other)
