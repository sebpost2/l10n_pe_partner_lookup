import logging

import requests
from stdnum.pe import ruc

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

API_URL = "https://api.decolecta.com/v1"
TIMEOUT = 10


def _text(value):
    """SUNAT answers "-" for an empty address part."""
    value = (value or "").strip()
    return value if value not in ("", "-") else False


class ResPartner(models.Model):
    _inherit = "res.partner"

    pe_sunat_state = fields.Char(string="SUNAT Status", readonly=True)
    pe_sunat_condition = fields.Char(string="SUNAT Condition", readonly=True)
    pe_sunat_warning = fields.Boolean(compute="_compute_pe_sunat_warning")

    @api.depends("pe_sunat_state", "pe_sunat_condition")
    def _compute_pe_sunat_warning(self):
        for partner in self:
            partner.pe_sunat_warning = bool(partner.pe_sunat_state) and (
                partner.pe_sunat_state != "ACTIVO"
                or partner.pe_sunat_condition != "HABIDO"
            )

    @api.onchange("vat")
    def _onchange_vat_clear_sunat(self):
        # The status belongs to the number that was looked up, not the new one.
        self.pe_sunat_state = False
        self.pe_sunat_condition = False

    def action_pe_lookup(self):
        self.ensure_one()
        number = "".join(ch for ch in (self.vat or "") if ch.isdigit())
        if len(number) == 11:
            # Check digit and prefix (10, 15, 16, 17, 20) verified before spending an API call.
            if not ruc.is_valid(number):
                raise UserError(_("%s is not a valid RUC: the check digit does not match.", number))
            self.write(self._pe_ruc_values(self._pe_fetch("sunat/ruc", number)))
        elif len(number) == 8:
            self.write(self._pe_dni_values(self._pe_fetch("reniec/dni", number)))
        else:
            raise UserError(_("Enter an 11-digit RUC or an 8-digit DNI in the Tax ID field."))
        return True

    def _pe_fetch(self, path, number):
        token = self.env["ir.config_parameter"].sudo().get_param("l10n_pe_partner_lookup.token")
        if not token:
            raise UserError(_("Set the Decolecta API token in Settings > General Settings > Contacts."))
        try:
            response = requests.get(
                f"{API_URL}/{path}",
                params={"numero": number},
                headers={"Authorization": f"Bearer {token}"},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            _logger.warning("Decolecta lookup of %s failed: %s", number, exc)
            raise UserError(_("The lookup service is not responding. Try again in a moment.")) from exc
        if response.status_code in (401, 403):
            raise UserError(_("Decolecta rejected the API token. Check it in Settings."))
        if response.status_code in (400, 404, 422):
            raise UserError(_("No SUNAT/RENIEC record was found for %s.", number))
        if response.status_code != 200:
            raise UserError(_("The lookup service is not responding. Try again in a moment."))
        return response.json()

    def _pe_ruc_values(self, data):
        peru = self.env.ref("base.pe")
        ubigeo = _text(data.get("ubigeo")) or ""
        # Odoo's Peruvian departments are coded with the first two ubigeo digits.
        state = self.env["res.country.state"].search(
            [("country_id", "=", peru.id), ("code", "=", ubigeo[:2])], limit=1
        )
        return {
            "name": data["razon_social"],
            "is_company": True,
            "street": _text(data.get("direccion")),
            "city": _text(data.get("distrito")),
            "state_id": state.id,
            "zip": ubigeo or False,
            "country_id": peru.id,
            "pe_sunat_state": data.get("estado"),
            "pe_sunat_condition": data.get("condicion"),
        }

    def _pe_dni_values(self, data):
        parts = (data.get("first_name"), data.get("first_last_name"), data.get("second_last_name"))
        return {
            "name": " ".join(p for p in parts if p) or data["full_name"],
            "is_company": False,
            "country_id": self.env.ref("base.pe").id,
            "pe_sunat_state": False,
            "pe_sunat_condition": False,
        }
