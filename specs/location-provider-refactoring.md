# Location Provider Refactoring Specification

## Документ информации

| Атрибут | Вредност |
|---------|----------|
| **Верзија** | 1.0 |
| **Датум** | 2024-12-07 |
| **Автор** | ЕСКОН-ИНЖЕНЕРИНГ |
| **Статус** | Draft |
| **Модули** | eskon_reverse, esfsm_stock |

---

## 1. Преглед на проблемот

### 1.1 Тековна состојба

Двата модула `eskon_reverse` и `esfsm_stock` имаат преклопувачка функционалност за креирање stock локации, што создава несогласувања и конфузија.

#### eskon_reverse (v18.0.1.3.0)
- **Цел**: Општо позајмување на опрема (Реверс)
- **Зависности**: stock, base, mail, hr
- **Креира локации за**: Вработени (автоматски при create)
- **Parent локации**: `Вработени` (view), `Партнери` (view)
- **Picking types**: `Реверс`, `Враќање на Реверс`

#### esfsm_stock (v18.0.1.1.0)
- **Цел**: FSM материјали и fleet интеграција
- **Зависности**: esfsm, stock, fleet, eskon_reverse
- **Креира локации за**: Возила (автоматски при create)
- **Parent локации**: `Возила` (internal), `Терени техничари` (internal)
- **Picking types**: Користи од eskon_reverse

### 1.2 Идентификувани проблеми

| # | Проблем | Влијание |
|---|---------|----------|
| 1 | Вработен добива локација од eskon_reverse, но esfsm_stock ја игнорира | Материјалите не се следат правилно |
| 2 | Возило добива локација од esfsm_stock, eskon_reverse не знае за неа | Реверс не може да се издаде на возило |
| 3 | Различна хиерархија (view vs internal parent) | Конфузија во inventory reports |
| 4 | Нема конфигурација за однесување | Корисникот не може да прилагоди |
| 5 | Дупликат логика за креирање локации | Тешко одржување |

### 1.3 Конкретни сценарија на проблем

**Сценарио А: Вработен без возило**
```
1. Креирај вработен "Иван"
2. eskon_reverse креира: Physical Locations/Вработени/Вработен - Иван
3. Додели FSM работа на Иван
4. esfsm_stock бара локација: employee.vehicle_id.stock_location_id → None
5. Fallback на warehouse → Материјалите не се следат кај Иван!
```

**Сценарио Б: Вработен со возило**
```
1. Креирај возило "СТ-1234"
2. esfsm_stock креира: WH/Stock/Возила/Возило - СТ-1234
3. Додели возило на Иван
4. Сега Иван има ДВЕ локации:
   - Physical Locations/Вработени/Вработен - Иван (од eskon_reverse)
   - WH/Stock/Возила/Возило - СТ-1234 (од esfsm_stock)
5. Кој е "правилен"? Зависи од контекст!
```

---

## 2. Предложено решение

### 2.1 Архитектурен принцип

**"eskon_reverse = Location Provider"**

eskon_reverse станува единствен одговорен модул за креирање и управување со локации за ресурси (вработени, возила, тимови, партнери).

```
┌─────────────────────────────────────────────────────────────────┐
│                      eskon_reverse                            │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │              stock.location.provider                       │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐         │ │
│  │  │Employee │ │ Vehicle │ │  Team   │ │ Partner │         │ │
│  │  │ Location│ │ Location│ │ Location│ │ Location│         │ │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘         │ │
│  │       │           │           │           │               │ │
│  │       └───────────┴───────────┴───────────┘               │ │
│  │                        │                                   │ │
│  │              get_or_create_location()                      │ │
│  │              get_fsm_location(job)                         │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │              res.config.settings                           │ │
│  │  • auto_create_employee_location                          │ │
│  │  • auto_create_vehicle_location                           │ │
│  │  • auto_create_team_location                              │ │
│  │  • fsm_location_priority                                  │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ depends
                              │
┌─────────────────────────────────────────────────────────────────┐
│                        esfsm_stock                              │
│  • FSM материјали workflow (wizards)                           │
│  • Користи provider.get_fsm_location(job)                      │
│  • НЕМА сопствена логика за локации                            │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Нова хиерархија на локации

```
Physical Locations/
│
├── Ресурси/ (view) ─────────────────────── НОВА PARENT ЛОКАЦИЈА
│   │
│   ├── Вработени/ (view)
│   │   ├── Вработен - Иван Петров
│   │   ├── Вработен - Марко Стојанов
│   │   └── ...
│   │
│   ├── Возила/ (view) ──────────────────── ПРЕМЕСТЕНО ОД esfsm_stock
│   │   ├── Возило - СТ-1234-АА
│   │   ├── Возило - СТ-5678-ББ
│   │   └── ...
│   │
│   └── Тимови/ (view) ──────────────────── НОВО (опционално)
│       ├── Тим - Сервис
│       ├── Тим - Монтажа
│       └── ...
│
├── Партнери/ (view)
│   ├── Клиент АБЦ ДООЕЛ
│   ├── Клиент XYZ
│   └── ...
│
└── Тест лабораторија/ (internal) ────────── ПОСТОЕЧКА
```

### 2.3 Конфигурациски параметри

| Параметар | Тип | Default | Опис |
|-----------|-----|---------|------|
| `eskon_reverse.auto_create_employee_location` | Boolean | True | Автоматски креирај локација при нов вработен |
| `eskon_reverse.auto_create_vehicle_location` | Boolean | True | Автоматски креирај локација при ново возило |
| `eskon_reverse.auto_create_team_location` | Boolean | False | Автоматски креирај локација при нов тим |
| `eskon_reverse.auto_create_partner_location` | Boolean | False | Автоматски креирај локација при нов партнер |
| `eskon_reverse.fsm_location_priority` | Selection | 'vehicle' | Приоритет при избор на FSM локација |

**FSM Location Priority опции:**
- `vehicle` - Возило → Вработен → Магацин
- `employee` - Вработен → Возило → Магацин
- `team` - Тим → Возило → Вработен → Магацин

---

## 3. Технички дизајн

### 3.1 Нови модели

#### 3.1.1 stock.location.provider (Abstract Model)

```python
class StockLocationProvider(models.AbstractModel):
    """
    Централизиран сервис за креирање и управување со локации.
    """
    _name = 'stock.location.provider'
    _description = 'Stock Location Provider Service'

    # ─────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────

    def get_or_create_location(self, resource_type, resource_record):
        """
        Универзален метод за добивање/креирање локација.

        Args:
            resource_type (str): 'employee', 'vehicle', 'team', 'partner'
            resource_record: Recordset (hr.employee, fleet.vehicle, etc.)

        Returns:
            stock.location: Location record or False
        """
        pass

    def get_fsm_location(self, job):
        """
        Добиј соодветна локација за FSM работа според конфигуриран приоритет.

        Args:
            job: esfsm.job record

        Returns:
            stock.location: Most appropriate location for the job
        """
        pass

    def sync_location_name(self, resource_type, resource_record):
        """
        Синхронизирај име на локација со ресурсот.

        Args:
            resource_type (str): 'employee', 'vehicle', 'team', 'partner'
            resource_record: Recordset
        """
        pass

    # ─────────────────────────────────────────────────────────────
    # PRIVATE METHODS
    # ─────────────────────────────────────────────────────────────

    def _is_auto_create_enabled(self, resource_type):
        """Check if auto-create is enabled for resource type."""
        pass

    def _get_parent_location(self, resource_type):
        """Get parent location for resource type."""
        pass

    def _generate_location_name(self, resource_type, resource_record):
        """Generate location name based on resource."""
        pass

    def _get_fsm_priority(self):
        """Get configured FSM location priority."""
        pass
```

#### 3.1.2 res.config.settings Extension

```python
class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ─────────────────────────────────────────────────────────────
    # LOCATION AUTO-CREATE SETTINGS
    # ─────────────────────────────────────────────────────────────

    reverse_auto_create_employee_location = fields.Boolean(
        string='Автоматски креирај локација за вработени',
        config_parameter='eskon_reverse.auto_create_employee_location',
        default=True,
        help='При креирање на нов вработен, автоматски креирај stock локација'
    )

    reverse_auto_create_vehicle_location = fields.Boolean(
        string='Автоматски креирај локација за возила',
        config_parameter='eskon_reverse.auto_create_vehicle_location',
        default=True,
        help='При креирање на ново возило, автоматски креирај stock локација'
    )

    reverse_auto_create_team_location = fields.Boolean(
        string='Автоматски креирај локација за тимови',
        config_parameter='eskon_reverse.auto_create_team_location',
        default=False,
        help='При креирање на нов FSM тим, автоматски креирај stock локација'
    )

    # ─────────────────────────────────────────────────────────────
    # FSM INTEGRATION SETTINGS
    # ─────────────────────────────────────────────────────────────

    reverse_fsm_location_priority = fields.Selection([
        ('vehicle', 'Возило → Вработен → Магацин'),
        ('employee', 'Вработен → Возило → Магацин'),
        ('team', 'Тим → Возило → Вработен → Магацин'),
    ],
        string='FSM приоритет на локации',
        config_parameter='eskon_reverse.fsm_location_priority',
        default='vehicle',
        help='Одреди кој ресурс има приоритет при избор на локација за FSM работа'
    )
```

### 3.2 Модификации на постоечки модели

#### 3.2.1 hr.employee (eskon_reverse)

```python
class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    stock_location_id = fields.Many2one(
        'stock.location',
        string='Локација на залихи',
        readonly=True,
        help='Автоматски креирана интерна локација'
    )

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)

        provider = self.env['stock.location.provider']
        for employee in employees:
            if not employee.stock_location_id:
                location = provider.get_or_create_location('employee', employee)
                if location:
                    employee.stock_location_id = location.id

        return employees

    def write(self, vals):
        res = super().write(vals)

        if 'name' in vals:
            provider = self.env['stock.location.provider']
            for employee in self:
                provider.sync_location_name('employee', employee)

        return res
```

#### 3.2.2 fleet.vehicle (eskon_reverse - НОВО)

```python
class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    stock_location_id = fields.Many2one(
        'stock.location',
        string='Локација на залихи',
        readonly=True,
        help='Автоматски креирана интерна локација за возилото'
    )

    @api.model_create_multi
    def create(self, vals_list):
        vehicles = super().create(vals_list)

        provider = self.env['stock.location.provider']
        for vehicle in vehicles:
            if not vehicle.stock_location_id:
                location = provider.get_or_create_location('vehicle', vehicle)
                if location:
                    vehicle.stock_location_id = location.id

        return vehicles

    def write(self, vals):
        res = super().write(vals)

        if 'name' in vals or 'license_plate' in vals:
            provider = self.env['stock.location.provider']
            for vehicle in self:
                provider.sync_location_name('vehicle', vehicle)

        return res
```

#### 3.2.3 esfsm.job (esfsm_stock - МОДИФИКАЦИЈА)

```python
class EsfsmJob(models.Model):
    _inherit = 'esfsm.job'

    def _get_source_location(self):
        """
        Get source location for materials using the provider service.

        Returns:
            stock.location: Appropriate location based on configuration
        """
        self.ensure_one()

        provider = self.env['stock.location.provider']
        return provider.get_fsm_location(self)
```

### 3.3 Data файлови

#### 3.3.1 stock_location_data.xml (eskon_reverse)

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="0">

        <!-- Parent: Resources -->
        <record id="stock_location_resources" model="stock.location">
            <field name="name">Ресурси</field>
            <field name="usage">view</field>
            <field name="location_id" ref="stock.stock_location_locations"/>
            <field name="comment">Локации за ресурси (вработени, возила, тимови)</field>
        </record>

        <!-- Employees Parent -->
        <record id="stock_location_employees" model="stock.location">
            <field name="name">Вработени</field>
            <field name="usage">view</field>
            <field name="location_id" ref="stock_location_resources"/>
            <field name="comment">Локации за следење на опрема кај вработени</field>
        </record>

        <!-- Vehicles Parent -->
        <record id="stock_location_vehicles" model="stock.location">
            <field name="name">Возила</field>
            <field name="usage">view</field>
            <field name="location_id" ref="stock_location_resources"/>
            <field name="comment">Локации за следење на материјали во возила</field>
        </record>

        <!-- Teams Parent (for FSM) -->
        <record id="stock_location_teams" model="stock.location">
            <field name="name">Тимови</field>
            <field name="usage">view</field>
            <field name="location_id" ref="stock_location_resources"/>
            <field name="comment">Локации за FSM тимови</field>
        </record>

        <!-- Partners Parent -->
        <record id="stock_location_partners" model="stock.location">
            <field name="name">Партнери</field>
            <field name="usage">view</field>
            <field name="location_id" ref="stock.stock_location_locations"/>
            <field name="comment">Локации за опрема кај надворешни партнери</field>
        </record>

        <!-- Testing Lab (existing) -->
        <record id="stock_location_testing_lab" model="stock.location">
            <field name="name">Тест лабораторија</field>
            <field name="usage">internal</field>
            <field name="location_id" ref="stock_location_employees"/>
            <field name="comment">Општа локација за тестирање</field>
        </record>

    </data>
</odoo>
```

---

## 4. Имплементациски план

### 4.1 Фаза 1: eskon_reverse рефакторирање

| # | Задача | Фајл | Комплексност |
|---|--------|------|--------------|
| 1.1 | Додај `fleet` како опционална зависност | `__manifest__.py` | Low |
| 1.2 | Креирај Location Provider сервис | `models/stock_location_provider.py` | High |
| 1.3 | Ажурирај hr.employee да користи provider | `models/hr_employee.py` | Medium |
| 1.4 | Додај fleet.vehicle со provider | `models/fleet_vehicle.py` | Medium |
| 1.5 | Додај res.config.settings | `models/res_config_settings.py` | Medium |
| 1.6 | Ажурирај data XML | `data/stock_location_data.xml` | Low |
| 1.7 | Додај settings view | `views/res_config_settings_views.xml` | Low |
| 1.8 | Ажурирај __init__.py и manifest | Various | Low |

**Проценка: 4-6 часа**

### 4.2 Фаза 2: esfsm_stock поедноставување

| # | Задача | Фајл | Комплексност |
|---|--------|------|--------------|
| 2.1 | Отстрани fleet_vehicle.py | `models/fleet_vehicle.py` | Low |
| 2.2 | Отстрани stock_location_data.xml | `data/stock_location_data.xml` | Low |
| 2.3 | Ажурирај esfsm_job._get_source_location() | `models/esfsm_job.py` | Medium |
| 2.4 | Ажурирај manifest (отстрани data) | `__manifest__.py` | Low |
| 2.5 | Ажурирај __init__.py | `models/__init__.py` | Low |

**Проценка: 1-2 часа**

### 4.3 Фаза 3: Миграција на податоци

| # | Задача | Опис | Комплексност |
|---|--------|------|--------------|
| 3.1 | Скрипта за миграција | Премести постоечки локации во нова хиерархија | Medium |
| 3.2 | Ажурирај references | Поправи stock.picking location references | Medium |
| 3.3 | Валидација | Провери интегритет на податоци | Low |

**Проценка: 2-3 часа**

### 4.4 Фаза 4: Тестирање

| # | Тест сценарио | Опис |
|---|---------------|------|
| 4.1 | Креирај вработен | Провери дали се креира локација |
| 4.2 | Креирај возило | Провери дали се креира локација |
| 4.3 | FSM работа без возило | Провери fallback на вработен |
| 4.4 | FSM работа со возило | Провери приоритет |
| 4.5 | Промени config | Провери дали се почитува |
| 4.6 | Реверс на вработен | Провери дали работи |
| 4.7 | Реверс на возило | Провери дали работи |

**Проценка: 2 часа**

---

## 5. Миграциска скрипта

```python
# scripts/migrate_locations.py
"""
Скрипта за миграција на постоечки локации во нова хиерархија.
Извршување: docker exec -i odoo_server odoo shell -d eskon --no-http < migrate_locations.py
"""

def migrate_locations(env):
    """Main migration function."""
    Location = env['stock.location']

    # 1. Најди ги новите parent локации
    resources_loc = env.ref('eskon_reverse.stock_location_resources', raise_if_not_found=False)
    employees_loc = env.ref('eskon_reverse.stock_location_employees', raise_if_not_found=False)
    vehicles_loc = env.ref('eskon_reverse.stock_location_vehicles', raise_if_not_found=False)

    if not all([resources_loc, employees_loc, vehicles_loc]):
        print("ERROR: Parent locations not found. Run module upgrade first.")
        return False

    # 2. Најди стари vehicle локации од esfsm_stock
    old_vehicles_parent = Location.search([
        ('name', '=', 'Возила'),
        ('usage', '=', 'internal'),  # Old was internal, new is view
    ], limit=1)

    if old_vehicles_parent:
        # Премести child локации во нова parent
        old_vehicle_locs = Location.search([
            ('location_id', '=', old_vehicles_parent.id)
        ])

        for loc in old_vehicle_locs:
            print(f"Moving vehicle location: {loc.name}")
            loc.location_id = vehicles_loc.id

        # Архивирај стара parent
        old_vehicles_parent.active = False
        print(f"Archived old parent: {old_vehicles_parent.name}")

    # 3. Премести Терени техничари ако постои
    field_tech_loc = Location.search([
        ('name', '=', 'Терени техничари'),
    ], limit=1)

    if field_tech_loc:
        field_tech_loc.location_id = employees_loc.id
        print(f"Moved: {field_tech_loc.name} to Employees")

    # 4. Commit
    env.cr.commit()
    print("Migration completed successfully!")

    return True

# Execute
migrate_locations(env)
```

---

## 6. Rollback план

Во случај на проблеми:

1. **Врати manifest** - отстрани fleet зависност од eskon_reverse
2. **Врати fleet_vehicle.py** - во esfsm_stock од git
3. **Врати stock_location_data.xml** - во esfsm_stock од git
4. **Деактивирај нови локации** - set active=False
5. **Реактивирај стари локации** - set active=True

```bash
# Git rollback commands
cd /home/eskon/odoo/addons/eskon_reverse
git checkout HEAD~1 -- models/ data/ __manifest__.py

cd /home/eskon/odoo/addons/esfsm_stock
git checkout HEAD~1 -- models/fleet_vehicle.py data/
```

---

## 7. Проценка на ризици

| Ризик | Веројатност | Влијание | Митигација |
|-------|-------------|----------|------------|
| Губење на постоечки локации | Low | High | Backup пред миграција |
| Pickings со wrong locations | Medium | Medium | Валидациска скрипта |
| Config parameters не се читаат | Low | Low | Unit тестови |
| fleet модул не е инсталиран | Low | Low | Optional dependency |

---

## 8. Acceptance Criteria

- [ ] Нов вработен добива локација автоматски (ако е вклучено)
- [ ] Ново возило добива локација автоматски (ако е вклучено)
- [ ] FSM работа користи правилна локација според приоритет
- [ ] Реверс работи за вработени и возила
- [ ] Settings се зачувуваат и применуваат
- [ ] Постоечки податоци се мигрирани
- [ ] Нема грешки во логови по upgrade

---

## 9. Референци

- [Odoo 18 Stock Documentation](https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory.html)
- [esfsm_stock Specification](../esfsm/specs/001-esfsm-field-service-management/spec.md)
- [eskon_reverse README](../eskon_reverse/README.md)

---

## Changelog

| Верзија | Датум | Автор | Промени |
|---------|-------|-------|---------|
| 1.0 | 2024-12-07 | ЕСКОН | Иницијален документ |
