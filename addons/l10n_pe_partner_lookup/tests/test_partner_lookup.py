from unittest.mock import Mock, patch

import requests

from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged

GET = "odoo.addons.l10n_pe_partner_lookup.models.res_partner.requests.get"

# Shape of a real Decolecta /v1/sunat/ruc answer (public example from its docs).
RUC_DATA = {
    "razon_social": "REXTIE S.A.C.",
    "numero_documento": "20601030013",
    "estado": "ACTIVO",
    "condicion": "HABIDO",
    "direccion": "AV. JOSE GALVEZ BARRENECHEA NRO 566 INT. 101 URB. CORPAC ",
    "ubigeo": "150131",
    "distrito": "SAN ISIDRO",
    "provincia": "LIMA",
    "departamento": "LIMA",
}
DNI_DATA = {
    "first_name": "ROXANA KARINA",
    "first_last_name": "DELGADO",
    "second_last_name": "HUAMANI",
    "full_name": "DELGADO HUAMANI ROXANA KARINA",
    "document_number": "46027897",
}


def _response(status, data=None):
    return Mock(status_code=status, json=Mock(return_value=data))


@tagged("post_install", "-at_install")
class TestPartnerLookup(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("l10n_pe_partner_lookup.token", "test-token")
        cls.partner = cls.env["res.partner"].create({"name": "New contact"})

    def _lookup(self, vat, response):
        self.partner.vat = vat
        with patch(GET, return_value=response) as get:
            self.partner.action_pe_lookup()
        return get

    # --- local validation: no API call is spent on a number that can't exist

    def test_ruc_with_wrong_check_digit_is_rejected_without_calling_the_api(self):
        self.partner.vat = "20601030014"
        with patch(GET) as get, self.assertRaisesRegex(UserError, "check digit"):
            self.partner.action_pe_lookup()
        get.assert_not_called()

    def test_ruc_with_unknown_prefix_is_rejected(self):
        # 11 digits, but 30 is not a RUC prefix (10, 15, 16, 17, 20).
        self.partner.vat = "30601030013"
        with patch(GET) as get, self.assertRaises(UserError):
            self.partner.action_pe_lookup()
        get.assert_not_called()

    def test_messages_are_in_spanish_for_a_peruvian_user(self):
        # es_PE reads the module's es.po (Odoo falls back es_PE -> es / es_419).
        self.env["res.lang"]._activate_lang("es_PE")
        self.partner.vat = "20601030014"
        with patch(GET) as get, self.assertRaisesRegex(UserError, "el dígito verificador no coincide"):
            self.partner.with_context(lang="es_PE").action_pe_lookup()
        get.assert_not_called()

    def test_number_of_the_wrong_length_is_rejected(self):
        self.partner.vat = "123456789"
        with patch(GET) as get, self.assertRaisesRegex(UserError, "11-digit RUC or an 8-digit DNI"):
            self.partner.action_pe_lookup()
        get.assert_not_called()

    def test_missing_token_points_to_settings(self):
        self.env["ir.config_parameter"].sudo().set_param("l10n_pe_partner_lookup.token", False)
        self.partner.vat = "20601030013"
        with patch(GET) as get, self.assertRaisesRegex(UserError, "Settings"):
            self.partner.action_pe_lookup()
        get.assert_not_called()

    # --- RUC

    def test_ruc_lookup_calls_sunat_endpoint_with_bearer_token(self):
        get = self._lookup("20601030013", _response(200, RUC_DATA))
        get.assert_called_once_with(
            "https://api.decolecta.com/v1/sunat/ruc",
            params={"numero": "20601030013"},
            headers={"Authorization": "Bearer test-token"},
            timeout=10,
        )

    def test_ruc_lookup_fills_company_and_address(self):
        self._lookup("20601030013", _response(200, RUC_DATA))
        p = self.partner
        self.assertEqual(p.name, "REXTIE S.A.C.")
        self.assertTrue(p.is_company)
        self.assertEqual(p.street, "AV. JOSE GALVEZ BARRENECHEA NRO 566 INT. 101 URB. CORPAC")
        self.assertEqual(p.city, "SAN ISIDRO")
        self.assertEqual(p.zip, "150131")
        self.assertEqual(p.country_id, self.env.ref("base.pe"))
        self.assertEqual(p.state_id, self.env.ref("base.state_pe_15"))  # Lima, from ubigeo 15xxxx

    def test_ruc_typed_with_spaces_is_normalized(self):
        get = self._lookup(" 2060 1030 013 ", _response(200, RUC_DATA))
        self.assertEqual(get.call_args.kwargs["params"], {"numero": "20601030013"})

    def test_dash_placeholders_from_sunat_become_empty(self):
        data = dict(RUC_DATA, direccion="-", distrito="-", ubigeo="-")
        self._lookup("20601030013", _response(200, data))
        self.assertFalse(self.partner.street)
        self.assertFalse(self.partner.city)
        self.assertFalse(self.partner.zip)
        self.assertFalse(self.partner.state_id)

    def test_active_and_habido_taxpayer_has_no_warning(self):
        self._lookup("20601030013", _response(200, RUC_DATA))
        self.assertEqual(self.partner.pe_sunat_state, "ACTIVO")
        self.assertEqual(self.partner.pe_sunat_condition, "HABIDO")
        self.assertFalse(self.partner.pe_sunat_warning)

    def test_no_habido_taxpayer_is_flagged(self):
        self._lookup("20601030013", _response(200, dict(RUC_DATA, condicion="NO HABIDO")))
        self.assertTrue(self.partner.pe_sunat_warning)

    def test_suspended_taxpayer_is_flagged(self):
        self._lookup("20601030013", _response(200, dict(RUC_DATA, estado="SUSPENSION TEMPORAL")))
        self.assertTrue(self.partner.pe_sunat_warning)

    # --- DNI

    def test_dni_lookup_fills_person_name_in_reading_order(self):
        get = self._lookup("46027897", _response(200, DNI_DATA))
        self.assertEqual(get.call_args.args[0], "https://api.decolecta.com/v1/reniec/dni")
        self.assertEqual(self.partner.name, "ROXANA KARINA DELGADO HUAMANI")
        self.assertFalse(self.partner.is_company)
        self.assertFalse(self.partner.pe_sunat_warning)

    def test_dni_lookup_after_a_ruc_clears_the_sunat_status(self):
        self._lookup("20601030013", _response(200, dict(RUC_DATA, condicion="NO HABIDO")))
        self._lookup("46027897", _response(200, DNI_DATA))
        self.assertFalse(self.partner.pe_sunat_state)
        self.assertFalse(self.partner.pe_sunat_warning)

    # --- API errors become readable messages and change nothing

    def test_rejected_token(self):
        self.partner.vat = "20601030013"
        with patch(GET, return_value=_response(401)), self.assertRaisesRegex(UserError, "token"):
            self.partner.action_pe_lookup()
        self.assertEqual(self.partner.name, "New contact")

    def test_unknown_ruc(self):
        self.partner.vat = "20601030013"
        with patch(GET, return_value=_response(422, {"message": "ruc no valido"})), \
                self.assertRaisesRegex(UserError, "No SUNAT/RENIEC record"):
            self.partner.action_pe_lookup()

    def test_server_error_is_not_reported_as_not_found(self):
        self.partner.vat = "20601030013"
        with patch(GET, return_value=_response(503)), self.assertRaisesRegex(UserError, "not responding"):
            self.partner.action_pe_lookup()

    def test_timeout(self):
        self.partner.vat = "20601030013"
        with patch(GET, side_effect=requests.Timeout), self.assertRaisesRegex(UserError, "not responding"):
            self.partner.action_pe_lookup()
        self.assertEqual(self.partner.name, "New contact")

    # --- form behaviour

    def test_editing_the_number_clears_the_previous_status(self):
        self._lookup("20601030013", _response(200, dict(RUC_DATA, condicion="NO HABIDO")))
        with Form(self.partner) as form:
            form.vat = "20100047218"
            self.assertFalse(form.pe_sunat_state)
            self.assertFalse(form.pe_sunat_warning)
