# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.tools import config
import logging

_logger = logging.getLogger(__name__)


class StockLocationProvider(models.AbstractModel):
    """
    Централизиран сервис за креирање и управување со stock локации.

    Овој сервис е единствен одговорен за креирање локации за:
    - Вработени (hr.employee)
    - Возила (fleet.vehicle)
    - Тимови (esfsm.team)
    - Партнери (res.partner)

    Користен од eskon_reverse и esfsm_stock модулите.
    """
    _name = 'stock.location.provider'
    _description = 'Stock Location Provider Service'

    # ─────────────────────────────────────────────────────────────────────────
    # CONFIGURATION
    # ─────────────────────────────────────────────────────────────────────────

    # ``location_field`` is the STABLE per-resource link used to dedup a
    # location by record identity (never by display name). employee/vehicle
    # already carry ``stock_location_id``; partner gets ``reverse_location_id``.
    # A type without a ``location_field`` (team) keeps the legacy name-based
    # dedup — it is dead config (no caller, location is related to the vehicle).
    RESOURCE_CONFIG = {
        'employee': {
            'param': 'eskon_reverse.auto_create_employee_location',
            'parent_ref': 'eskon_reverse.stock_location_employees',
            'name_prefix': 'Вработен',
            'name_field': 'name',
            'location_field': 'stock_location_id',
        },
        'vehicle': {
            'param': 'eskon_reverse.auto_create_vehicle_location',
            'parent_ref': 'eskon_reverse.stock_location_vehicles',
            'name_prefix': 'Возило',
            'name_field': 'license_plate',  # fallback to name
            'location_field': 'stock_location_id',
        },
        'team': {
            'param': 'eskon_reverse.auto_create_team_location',
            'parent_ref': 'eskon_reverse.stock_location_teams',
            'name_prefix': 'Тим',
            'name_field': 'name',
        },
        'partner': {
            'param': 'eskon_reverse.auto_create_partner_location',
            'parent_ref': 'eskon_reverse.stock_location_partners',
            'name_prefix': '',  # No prefix for partners
            'name_field': 'name',
            'location_field': 'reverse_location_id',
        },
    }

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def get_or_create_location(self, resource_type, resource_record):
        """
        Универзален метод за добивање/креирање локација.

        Args:
            resource_type (str): 'employee', 'vehicle', 'team', 'partner'
            resource_record: Recordset (hr.employee, fleet.vehicle, etc.)

        Returns:
            stock.location: Location record or False if disabled/error
        """
        if not resource_record:
            return False

        if resource_type not in self.RESOURCE_CONFIG:
            _logger.warning(f"Unknown resource type: {resource_type}")
            return False

        config = self.RESOURCE_CONFIG[resource_type]
        location_field = config.get('location_field')

        # STABLE IDENTITY (H4): if the resource already has a linked location,
        # that IS its location — return it. Dedup is by record id, never by
        # display name, so two same-named resources never share one location
        # and a rename can never merge two equipment ledgers (also fixes M10).
        if location_field and location_field in resource_record._fields:
            existing_link = resource_record[location_field]
            if existing_link:
                return existing_link

        # Check if auto-create is enabled
        if not self._is_auto_create_enabled(resource_type):
            _logger.debug(f"Auto-create disabled for {resource_type}")
            return False

        # Get parent location
        parent_location = self._get_parent_location(resource_type)
        if not parent_location:
            _logger.warning(f"Parent location not found for {resource_type}")
            return False

        # Generate location name (display label only — NOT an identity key)
        location_name = self._generate_location_name(resource_type, resource_record)
        if not location_name:
            _logger.warning(f"Could not generate location name for {resource_type}")
            return False

        Location = self.env['stock.location']

        # Legacy fallback for a type with NO stable link field (team): keep the
        # old name-based dedup so its behaviour is unchanged.
        if not location_field:
            existing = Location.search([
                ('name', '=', location_name),
                ('location_id', '=', parent_location.id),
            ], limit=1)
            if existing:
                return existing

        # Create a FRESH location (no name search → no collision).
        # sudo(): creating an internal stock.location is a framework-internal
        # side effect of issuing a реверс — a normal FSM/stock user who triggers
        # it must not need stock-admin rights (M12/M13).
        # company_id: inherit the PARENT's company, not the resource's (a
        # res.partner often has company_id=False, while the parent hierarchy is
        # per-company → a mismatched child failed _check_company).
        try:
            location = Location.sudo().create({
                'name': location_name,
                'usage': 'internal',
                'location_id': parent_location.id,
                'company_id': parent_location.company_id.id,
            })
        except Exception as e:
            _logger.error(f"Failed to create location for {resource_type}: {e}")
            return False

        # Write the link back so the location is owned by exactly one resource
        # and future lookups dedup by id. Skip related/computed link fields.
        if location_field and location_field in resource_record._fields \
                and not resource_record._fields[location_field].related:
            try:
                resource_record.sudo().write({location_field: location.id})
            except Exception as e:
                _logger.error(f"Failed to link location to {resource_type}: {e}")

        _logger.info(f"Created location '{location_name}' for {resource_type}")
        return location

    @api.model
    def get_fsm_location(self, job):
        """
        Добиј соодветна локација за FSM работа според конфигуриран приоритет.

        Priority options:
        - 'vehicle': Vehicle → Employee → Warehouse
        - 'employee': Employee → Vehicle → Warehouse
        - 'team': Team → Vehicle → Employee → Warehouse

        Args:
            job: esfsm.job record

        Returns:
            stock.location: Most appropriate location for the job
        """
        if not job:
            return self._get_warehouse_default(job)

        priority = self._get_fsm_priority()

        if priority == 'team':
            location = self._get_team_location(job)
            if location:
                return location

        if priority in ('vehicle', 'team'):
            location = self._get_vehicle_location(job)
            if location:
                return location

        if priority in ('employee', 'vehicle', 'team'):
            location = self._get_employee_location(job)
            if location:
                return location

        # Fallback to warehouse
        return self._get_warehouse_default(job)

    @api.model
    def sync_location_name(self, resource_type, resource_record):
        """
        Синхронизирај име на локација со ресурсот.

        Args:
            resource_type (str): 'employee', 'vehicle', 'team', 'partner'
            resource_record: Recordset with stock_location_id field
        """
        if not resource_record or not hasattr(resource_record, 'stock_location_id'):
            return

        if not resource_record.stock_location_id:
            return

        new_name = self._generate_location_name(resource_type, resource_record)
        if new_name and resource_record.stock_location_id.name != new_name:
            resource_record.stock_location_id.name = new_name
            _logger.info(f"Updated location name to '{new_name}'")

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE METHODS - Configuration
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def _is_auto_create_enabled(self, resource_type):
        """Check if auto-create is enabled for resource type."""
        config = self.RESOURCE_CONFIG.get(resource_type, {})
        param_name = config.get('param')
        if not param_name:
            return False

        # Get parameter value, default to True for employee/vehicle
        default = 'True' if resource_type in ('employee', 'vehicle') else 'False'
        value = self.env['ir.config_parameter'].sudo().get_param(param_name, default)
        return value == 'True'

    @api.model
    def _get_parent_location(self, resource_type):
        """Get parent location for resource type."""
        config = self.RESOURCE_CONFIG.get(resource_type, {})
        parent_ref = config.get('parent_ref')
        if not parent_ref:
            return False

        return self.env.ref(parent_ref, raise_if_not_found=False)

    @api.model
    def _generate_location_name(self, resource_type, resource_record):
        """Generate location name based on resource."""
        config = self.RESOURCE_CONFIG.get(resource_type, {})
        prefix = config.get('name_prefix', '')
        name_field = config.get('name_field', 'name')

        # Get name from record
        name = ''
        if hasattr(resource_record, name_field):
            name = getattr(resource_record, name_field) or ''

        # Fallback to 'name' field for vehicles if license_plate is empty
        if not name and resource_type == 'vehicle' and hasattr(resource_record, 'name'):
            name = resource_record.name or ''

        if not name:
            return False

        if prefix:
            return f"{prefix} - {name}"
        return name

    @api.model
    def _get_fsm_priority(self):
        """Get configured FSM location priority."""
        return self.env['ir.config_parameter'].sudo().get_param(
            'eskon_reverse.fsm_location_priority', 'vehicle'
        )

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE METHODS - FSM Location Resolution
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def _get_team_location(self, job):
        """Get location from team (if FSM team has location)."""
        if not hasattr(job, 'team_id') or not job.team_id:
            return False

        # Team might have direct stock_location_id or via vehicle
        if hasattr(job.team_id, 'stock_location_id') and job.team_id.stock_location_id:
            return job.team_id.stock_location_id

        # Or team might have a vehicle with location
        if hasattr(job.team_id, 'vehicle_id') and job.team_id.vehicle_id:
            if job.team_id.vehicle_id.stock_location_id:
                return job.team_id.vehicle_id.stock_location_id

        return False

    @api.model
    def _get_vehicle_location(self, job):
        """Get location from assigned vehicle."""
        # Check team vehicle first
        if hasattr(job, 'team_id') and job.team_id:
            if hasattr(job.team_id, 'vehicle_id') and job.team_id.vehicle_id:
                if job.team_id.vehicle_id.stock_location_id:
                    return job.team_id.vehicle_id.stock_location_id

        # Check employee_ids vehicles (Many2many - no employee_id on esfsm.job)
        if hasattr(job, 'employee_ids') and job.employee_ids:
            for employee in job.employee_ids:
                if hasattr(employee, 'vehicle_id') and employee.vehicle_id:
                    if employee.vehicle_id.stock_location_id:
                        return employee.vehicle_id.stock_location_id

        # Check material_responsible_id vehicle
        if hasattr(job, 'material_responsible_id') and job.material_responsible_id:
            if hasattr(job.material_responsible_id, 'vehicle_id') and job.material_responsible_id.vehicle_id:
                if job.material_responsible_id.vehicle_id.stock_location_id:
                    return job.material_responsible_id.vehicle_id.stock_location_id

        return False

    @api.model
    def _get_employee_location(self, job):
        """Get location from assigned employee."""
        # Material responsible first (most specific - designated for materials)
        if hasattr(job, 'material_responsible_id') and job.material_responsible_id:
            if job.material_responsible_id.stock_location_id:
                return job.material_responsible_id.stock_location_id

        # Multiple employees - take first with location (Many2many)
        if hasattr(job, 'employee_ids') and job.employee_ids:
            for employee in job.employee_ids:
                if employee.stock_location_id:
                    return employee.stock_location_id

        return False

    @api.model
    def _get_warehouse_default(self, job):
        """Get default warehouse location as fallback."""
        company_id = job.company_id.id if job and hasattr(job, 'company_id') and job.company_id else self.env.company.id

        warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', company_id)
        ], limit=1)

        if warehouse:
            return warehouse.lot_stock_id

        # Ultimate fallback
        return self.env.ref('stock.stock_location_stock', raise_if_not_found=False)
