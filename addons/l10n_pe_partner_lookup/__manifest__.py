{
    "name": "Peru RUC/DNI Partner Lookup",
    "version": "19.0.1.0.0",
    "summary": "Fill a contact from SUNAT (RUC) or RENIEC (DNI) with one click, and flag taxpayers that are not ACTIVO/HABIDO.",
    "description": """
Validates the RUC check digit locally, then looks the number up through the
Decolecta API and fills the contact's name, address and department. Contacts
whose SUNAT status is not ACTIVO or whose condition is not HABIDO show a
warning before anyone invoices them.
""",
    "author": "Sebastian Postigo",
    "license": "LGPL-3",
    "category": "Localization",
    "depends": ["base_setup"],
    "data": [
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "demo": ["data/demo.xml"],
    "installable": True,
    "application": False,
}
