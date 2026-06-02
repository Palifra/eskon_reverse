# -*- coding: utf-8 -*-
{
    'name': 'Реверс - Позајмување на опрема',
    'version': '18.0.2.2.0',
    'category': 'Inventory/Inventory',
    'summary': 'Управување со привремено издавање на опрема (Реверс) со Location Provider',
    'description': """
Реверс - Позајмување на опрема
===============================

Модул за управување со привремено издавање на опрема во Одоо.

Функционалности:
-----------------
* **Location Provider** - Централизиран сервис за креирање локации
* Автоматски креира локации за вработени, возила, тимови и партнери
* Конфигурабилно однесување преку Settings
* Додава нов тип на операција "Реверс" (Equipment Borrowing)
* Автоматско нумерирање: ESGM/REV/00001
* Следење на кој вработен/партнер/возило има која опрема
* Рок за враќање со автоматски потсетувања
* Преглед на задоцнети враќања
* FSM интеграција - приоритет на локации за теренски работи

Работен тек:
------------
1. ИЗДАВАЊЕ: Креирај Реверс (WH/Stock → Ресурси/Вработени/Име)
2. СЛЕДЕЊЕ: Inventory Report по локации + рокови за враќање
3. ПОТСЕТУВАЊЕ: Автоматско потсетување 3 дена пред рок
4. ВРАЌАЊЕ: Internal Transfer (Ресурси/... → WH/Stock)

Нова хиерархија на локации:
---------------------------
Physical Locations/
├── Ресурси/
│   ├── Вработени/
│   ├── Возила/
│   └── Тимови/
└── Партнери/

Автор: ЕСКОН-ИНЖЕНЕРИНГ ДООЕЛ Струмица
Website: https://www.eskon.com.mk
    """,
    'author': 'ЕСКОН-ИНЖЕНЕРИНГ ДООЕЛ Струмица',
    'website': 'https://www.eskon.com.mk',
    'license': 'LGPL-3',
    'depends': [
        'stock',
        'base',
        'mail',
        'hr',
        'fleet',  # For vehicle location support
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/stock_location_data.xml',
        'data/stock_picking_type_data.xml',
        'data/ir_cron_data.xml',
        'wizards/reverse_wizard_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_picking_form_view.xml',
        'views/res_config_settings_views.xml',
        'views/hr_employee_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': '_post_init_hook',
}
