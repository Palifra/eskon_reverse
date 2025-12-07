# ESKON Reverse - Позајмување на опрема

Модул за управување со привремено издавање на опрема во Одоо 18. Вклучува централизиран Location Provider сервис за управување со локации на ресурси.

## Главни функционалности

### Location Provider (Централен сервис за локации)
- Автоматско креирање на stock локации за вработени, возила, тимови и партнери
- Конфигурабилен FSM приоритет за теренска работа
- Единствена точка за управување со ресурсни локации

### Реверс (Позајмување на опрема)
- Нов тип на операција за издавање опрема
- Автоматско нумерирање: `ESGM/REV/00001`
- Рок за враќање со автоматски потсетувања
- Враќање на реверс со посебен picking type

## Инсталација

### Преку Docker (препорачано)
```bash
docker exec -i odoo_server odoo shell -d eskon --no-http << 'EOF'
env['ir.module.module'].update_list()
module = env['ir.module.module'].search([('name', '=', 'eskon_reverse')])
module.button_immediate_install()
env.cr.commit()
EOF
```

### Рачна инсталација
```bash
./odoo-bin -d database -i eskon_reverse
```

## Хиерархија на локации

По инсталација, модулот креира:

```
Physical Locations/
├── Ресурси/
│   ├── Вработени/
│   │   ├── Вработен - Име Презиме (автоматски)
│   │   ├── Сервисен тим
│   │   └── Тест лабораторија
│   ├── Возила/
│   │   └── Возило - SR-XXXX-XX (автоматски)
│   └── Тимови/
│       └── (FSM тимови)
└── Партнери/
    └── Партнер - Име (автоматски)
```

## Конфигурација

### Settings (Inventory → Configuration → Settings)

| Поставка | Опис | Default |
|----------|------|---------|
| Автоматски за вработени | Креирај локација при нов вработен | ✓ |
| Автоматски за возила | Креирај локација при ново возило | ✓ |
| Автоматски за тимови | Креирај локација при нов тим | ✗ |
| Автоматски за партнери | Креирај локација при нов партнер | ✗ |
| FSM приоритет | Приоритет при избор на локација | Возило |

### FSM приоритет опции

| Опција | Приоритет на локации |
|--------|---------------------|
| Возило | Возило → Вработен → Магацин |
| Вработен | Вработен → Возило → Магацин |
| Тим | Тим → Возило → Вработен → Магацин |

## Location Provider API

### Добивање или креирање локација
```python
provider = env['stock.location.provider']

# За вработен
location = provider.get_or_create_location('employee', employee_record)

# За возило
location = provider.get_or_create_location('vehicle', vehicle_record)

# За тим
location = provider.get_or_create_location('team', team_record)

# За партнер
location = provider.get_or_create_location('partner', partner_record)
```

### FSM локација за работа
```python
# Добива соодветна локација според конфигурираниот приоритет
location = provider.get_fsm_location(job_record)
```

### Проверка на автоматско креирање
```python
# Дали е вклучено автоматско креирање за даден тип
is_enabled = provider.is_auto_create_enabled('employee')  # True/False
```

## Работен тек за Реверс

### 1. Издавање на опрема

```
Inventory → Операции → Реверси → New

Пополни:
- Partner: Вработен или партнер
- Тип на примател: Вработен / Партнер
- Рок за враќање: Датум
- Destination Location: Автоматски или рачно

Додади производи → Validate

Резултат: ESGM/REV/00001
```

### 2. Следење

```
Inventory → Reporting → Locations
Филтрирај по: Ресурси или Партнери

Ќе видиш:
- Кој има која опрема
- Количини по локација
```

### 3. Потсетувања

- **3 дена пред рок**: Автоматско потсетување
- **Поминат рок**: Црвен датум во листата
- **Chatter**: Логирање на сите активности

### 4. Враќање

```
Inventory → Операции → Реверси → Враќања → New

From: Вработени/Име или Партнери/Име
To: WH/Stock
Product + Quantity

Validate
```

## Picking Types

| Тип | Код | Опис |
|-----|-----|------|
| Реверс | REV | Издавање на опрема |
| Враќање на Реверс | REV-RET | Враќање на опрема |

## Зависности

- `stock` - Inventory Management
- `base` - Base Module
- `mail` - Email & Notifications
- `hr` - Human Resources
- `fleet` - Fleet Management

## Зависни модули

Следните модули зависат од `eskon_reverse`:

| Модул | Опис |
|-------|------|
| `esfsm_stock` | FSM материјали и возила |
| `l10n_mk_stock_reports` | Магацински извештаи |

## Config Parameters

| Клуч | Тип | Default | Опис |
|------|-----|---------|------|
| `eskon_reverse.auto_create_employee_location` | Boolean | True | Авто-локација за вработени |
| `eskon_reverse.auto_create_vehicle_location` | Boolean | True | Авто-локација за возила |
| `eskon_reverse.auto_create_team_location` | Boolean | False | Авто-локација за тимови |
| `eskon_reverse.auto_create_partner_location` | Boolean | False | Авто-локација за партнери |
| `eskon_reverse.fsm_location_priority` | Selection | 'vehicle' | FSM приоритет |

## Техничка документација

### Модели

| Модел | Опис |
|-------|------|
| `stock.location.provider` | Централен сервис (AbstractModel) |
| `eskon_reverse.setup` | Иницијализација на picking types |
| `hr.employee` | Extends со `stock_location_id` |
| `fleet.vehicle` | Extends со `stock_location_id` |
| `stock.picking` | Extends со реверс функционалност |
| `res.config.settings` | Settings UI |

### XML IDs

```
eskon_reverse.stock_location_resources    # Ресурси (view)
eskon_reverse.stock_location_employees    # Вработени (view)
eskon_reverse.stock_location_vehicles     # Возила (view)
eskon_reverse.stock_location_teams        # Тимови (view)
eskon_reverse.stock_location_partners     # Партнери (view)
```

## Changelog

### 18.0.2.0.0 (2024-12-07)
- Преименуван модул од `l10n_mk_reverse` во `eskon_reverse`
- Додаден Location Provider сервис
- Додадена поддршка за возила и тимови
- Додаден Settings UI за конфигурација
- Додаден FSM приоритет за теренска работа

### 18.0.1.3.0
- Првична верзија со Реверс функционалност
- Автоматски локации за вработени
- Потсетувања за враќање

## Автор

**ЕСКОН-ИНЖЕНЕРИНГ ДООЕЛ Струмица**

- Email: info@eskon.com.mk
- Website: https://www.eskon.com.mk
- GitHub: https://github.com/Palifra/eskon_reverse

## Лиценца

LGPL-3
