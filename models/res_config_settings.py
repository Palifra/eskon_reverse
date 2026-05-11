# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ─────────────────────────────────────────────────────────────────────────
    # LOCATION AUTO-CREATE SETTINGS
    # ─────────────────────────────────────────────────────────────────────────

    reverse_auto_create_employee_location = fields.Boolean(
        string='Автоматски креирај локација за вработени',
        config_parameter='eskon_reverse.auto_create_employee_location',
        default=True,
        help='При креирање на нов вработен, автоматски креирај stock локација за следење на опрема'
    )

    reverse_auto_create_vehicle_location = fields.Boolean(
        string='Автоматски креирај локација за возила',
        config_parameter='eskon_reverse.auto_create_vehicle_location',
        default=True,
        help='При креирање на ново возило, автоматски креирај stock локација за следење на материјали'
    )

    reverse_auto_create_team_location = fields.Boolean(
        string='Автоматски креирај локација за тимови',
        config_parameter='eskon_reverse.auto_create_team_location',
        default=False,
        help='При креирање на нов FSM тим, автоматски креирај stock локација'
    )

    reverse_auto_create_partner_location = fields.Boolean(
        string='Автоматски креирај локација за партнери',
        config_parameter='eskon_reverse.auto_create_partner_location',
        default=False,
        help='При креирање на нов партнер/клиент, автоматски креирај stock локација'
    )

    # ─────────────────────────────────────────────────────────────────────────
    # WIZARD SETTINGS
    # ─────────────────────────────────────────────────────────────────────────

    reverse_default_return_days = fields.Integer(
        string='Стандарден рок за враќање (денови)',
        config_parameter='eskon_reverse.default_return_days',
        default=7,
        help='Стандарден број на денови за рок на враќање при креирање реверс преку wizard',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # FSM INTEGRATION SETTINGS
    # ─────────────────────────────────────────────────────────────────────────

    reverse_fsm_location_priority = fields.Selection([
        ('vehicle', 'Возило → Вработен → Магацин'),
        ('employee', 'Вработен → Возило → Магацин'),
        ('team', 'Тим → Возило → Вработен → Магацин'),
    ],
        string='FSM приоритет на локации',
        config_parameter='eskon_reverse.fsm_location_priority',
        default='vehicle',
        help='Одреди кој ресурс има приоритет при избор на локација за FSM работа. '
             'Ова влијае само кога esfsm_stock модулот е инсталиран.'
    )
