from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pe_lookup_token = fields.Char(
        string="Decolecta API Token",
        config_parameter="l10n_pe_partner_lookup.token",
    )
