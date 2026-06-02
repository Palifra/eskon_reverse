# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    reverse_location_id = fields.Many2one(
        'stock.location',
        string='Реверс локација',
        readonly=True,
        copy=False,
        help='Интерна локација за следење на опрема позајмена на овој партнер '
             '(автоматски креирана при издавање реверс). Стабилен идентитет — '
             'не зависи од името, па двајца со исто име не делат локација.',
    )
