# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eskon_reverse')
class TestResourceLocationIdentity(TransactionCase):
    """H4 — resource→location identity must be keyed on a stable per-resource
    link (`stock_location_id` for employee/vehicle, `reverse_location_id` for
    partner), NOT the display name. So same-named resources never share a
    location, and a rename can never merge two equipment ledgers (also M10)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env['stock.location.provider']
        # employee/vehicle auto-create default True; enable partner explicitly.
        cls.env['ir.config_parameter'].sudo().set_param(
            'eskon_reverse.auto_create_partner_location', 'True')
        cls.partners_parent = cls.env.ref(
            'eskon_reverse.stock_location_partners', raise_if_not_found=False)

    def test_01_same_named_partners_get_distinct_locations(self):
        """The H4 core: two partners with identical names must resolve to
        DISTINCT internal locations (name-keying merged them into one)."""
        if not self.partners_parent:
            self.skipTest("Partners parent location not found")
        p1 = self.env['res.partner'].create({'name': 'Дупликат Ресурс H4'})
        p2 = self.env['res.partner'].create({'name': 'Дупликат Ресурс H4'})
        loc1 = self.provider.get_or_create_location('partner', p1)
        loc2 = self.provider.get_or_create_location('partner', p2)
        self.assertTrue(loc1 and loc2)
        self.assertNotEqual(
            loc1, loc2,
            "same-named partners must get distinct locations (keyed on id, not name)")

    def test_02_same_partner_idempotent(self):
        """Resolving the same partner twice returns the same location."""
        if not self.partners_parent:
            self.skipTest("Partners parent location not found")
        p = self.env['res.partner'].create({'name': 'Идемпотент Партнер H4'})
        loc1 = self.provider.get_or_create_location('partner', p)
        loc2 = self.provider.get_or_create_location('partner', p)
        self.assertTrue(loc1)
        self.assertEqual(loc1, loc2)

    def test_03_partner_rename_keeps_same_location(self):
        """Renaming a partner must NOT orphan its location / create a second one
        (M10): resolution after a rename returns the original location."""
        if not self.partners_parent:
            self.skipTest("Partners parent location not found")
        p = self.env['res.partner'].create({'name': 'Старо Име H4'})
        loc1 = self.provider.get_or_create_location('partner', p)
        p.write({'name': 'Ново Име H4'})
        loc2 = self.provider.get_or_create_location('partner', p)
        self.assertEqual(
            loc1, loc2,
            "a rename must not create a second location for the same partner")

    def test_04_partner_link_is_authoritative_over_name(self):
        """The stored link wins over the display name: even if the location's
        name no longer matches the partner, resolution returns the linked one."""
        if not self.partners_parent:
            self.skipTest("Partners parent location not found")
        p = self.env['res.partner'].create({'name': 'Авторитет Партнер H4'})
        loc = self.provider.get_or_create_location('partner', p)
        self.assertEqual(p.reverse_location_id, loc)
        loc.sudo().name = 'COMPLETELY DIFFERENT NAME H4'
        again = self.provider.get_or_create_location('partner', p)
        self.assertEqual(again, loc, "resolution must follow the link, not the name")

    def test_05_two_same_named_employees_distinct_locations(self):
        """Employees auto-create a location on create; two same-named employees
        must NOT share one (the real H4 collision via the create path)."""
        e1 = self.env['hr.employee'].create({'name': 'Иван Иванов H4'})
        e2 = self.env['hr.employee'].create({'name': 'Иван Иванов H4'})
        self.assertTrue(e1.stock_location_id and e2.stock_location_id)
        self.assertNotEqual(
            e1.stock_location_id, e2.stock_location_id,
            "two employees with the same name must get distinct locations")

    def test_06_migration_splits_shared_location(self):
        """The one-time migration re-homes resources that share one location
        onto distinct locations (the prod loc-108 vehicle collision), then
        (re)creates the partial-unique index that prevents recurrence."""
        # Start from a clean index slate (rolled back at test end) so the
        # forced collision below can be seeded even after a real deploy.
        self.env.cr.execute(
            "DROP INDEX IF EXISTS eskon_reverse_uniq_emp_location")
        e1 = self.env['hr.employee'].create({'name': 'Колизија А H4'})
        e2 = self.env['hr.employee'].create({'name': 'Колизија Б H4'})
        shared = e1.stock_location_id
        self.assertTrue(shared)
        e2.sudo().write({'stock_location_id': shared.id})  # force the collision
        self.assertEqual(e1.stock_location_id, e2.stock_location_id)

        self.env['eskon_reverse.setup']._migrate_resource_location_identity()

        self.assertTrue(e1.stock_location_id and e2.stock_location_id)
        self.assertNotEqual(
            e1.stock_location_id, e2.stock_location_id,
            "migration must split a shared location into distinct ones")
        # the teeth: the partial-unique index now exists
        self.env.cr.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = 'eskon_reverse_uniq_emp_location'")
        self.assertTrue(
            self.env.cr.fetchone(),
            "migration must (re)create the partial-unique index on the location link")

    def test_07_copy_resource_does_not_violate_index(self):
        """`stock_location_id` is copy=False, so duplicating an employee gives
        the copy a FRESH distinct location instead of crashing on the partial-
        unique index (which would reject the inherited link)."""
        # The index must be present for this guard to be meaningful.
        self.env['eskon_reverse.setup']._create_link_unique_indexes()
        original = self.env['hr.employee'].create({'name': 'Копирање Тест H4'})
        self.assertTrue(original.stock_location_id)
        copy = original.copy()  # would raise UniqueViolation without copy=False
        self.assertTrue(copy.stock_location_id)
        self.assertNotEqual(
            copy.stock_location_id, original.stock_location_id,
            "a duplicated employee must get its own distinct location")

    def test_08_migration_skips_nonempty_shared_location(self):
        """The split must NOT re-home a resource off a shared location that
        still holds stock (quant guard); the unique index is then skipped
        (defensive) rather than aborting the upgrade."""
        self.env.cr.execute(
            "DROP INDEX IF EXISTS eskon_reverse_uniq_emp_location")
        e1 = self.env['hr.employee'].create({'name': 'Непразна А H4'})
        e2 = self.env['hr.employee'].create({'name': 'Непразна Б H4'})
        shared = e1.stock_location_id
        self.assertTrue(shared)
        e2.sudo().write({'stock_location_id': shared.id})  # force the collision
        # Put stock on the shared location so the split must skip it.
        product = self.env['product.product'].create({
            'name': 'H4 Quant Product', 'type': 'consu', 'is_storable': True})
        self.env['stock.quant'].create({
            'product_id': product.id, 'location_id': shared.id, 'quantity': 5})

        self.env['eskon_reverse.setup']._migrate_resource_location_identity()

        # Non-empty → NOT split: both still on the shared location...
        self.assertEqual(
            e1.stock_location_id, e2.stock_location_id,
            "a shared location holding stock must be left for manual handling")
        # ...and the index is skipped (a duplicate still exists), not created.
        self.env.cr.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = 'eskon_reverse_uniq_emp_location'")
        self.assertFalse(
            self.env.cr.fetchone(),
            "the unique index must be skipped while a duplicate link survives")
