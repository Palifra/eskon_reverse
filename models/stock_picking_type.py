# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import UserError

# Stable, non-translatable sequence_code identity for the Реверс/Повратница
# picking types. The display name ('Реверс'/'Повратница') is translatable and
# was the historical match key — a single translation pass would silently flip
# the whole feature off. Match on sequence_code instead.
REVERSE_CODE = 'REV'        # реверс (issue) — warehouse → technician/vehicle
RETURN_CODE = 'REV-RET'     # повратница (return) — technician/vehicle → warehouse


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    @api.model
    def _eskon_reverse_type(self, role, warehouse, company=None):
        """Resolve THE реверс/повратница picking type for a warehouse.

        Identity is the non-translatable ``sequence_code`` ('REV' / 'REV-RET'),
        scoped to the given ``warehouse`` (the per-warehouse split is already on
        ``warehouse_id``). Raises a clear error if missing — NO silent fallback
        and NO auto-create. A mis-configured environment must fail loudly at
        issue time, never silently create a wrong-typed picking.

        Args:
            role: 'reverse' (issue) or 'return' (повратница).
            warehouse: stock.warehouse record whose type to resolve.
            company: optional res.company to further scope the search.

        Returns:
            stock.picking.type: the matching type (limit=1).

        Raises:
            UserError: if no matching type exists for the warehouse/company.
        """
        if not warehouse:
            raise UserError(_(
                "Не е пронајден магацин за резолуција на тип на операција „%s“. "
                "Проверете дали компанијата има магацин."
            ) % role)
        code_by_role = {'reverse': REVERSE_CODE, 'return': RETURN_CODE}
        if role not in code_by_role:
            raise UserError(_("Непознат role „%s“ за резолуција на тип на операција.") % role)
        code = code_by_role[role]
        domain = [
            ('sequence_code', '=', code),
            ('warehouse_id', '=', warehouse.id),
        ]
        if company:
            domain.append(('company_id', '=', company.id))
        picking_type = self.search(domain, limit=1)
        if not picking_type:
            raise UserError(_(
                "Не е пронајден тип на операција за „%s“ (sequence_code „%s“) "
                "за магацин „%s“. Проверете го модулот Реверс."
            ) % (role, code, warehouse.display_name))
        return picking_type
