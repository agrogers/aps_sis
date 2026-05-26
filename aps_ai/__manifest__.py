{
    'name': 'APS AI',
    'version': '18.0.1.0.0',
    'category': 'Technical',
    'summary': 'Standalone AI provider/model engine for Odoo. Provides OpenAI-compatible chat completion integration, prompt management, and a feedback pipeline that any Odoo module can use.',
    'description': (
        'APS AI — reusable AI engine for Odoo 18 Community Edition.\n\n'
        'Provides:\n'
        '  * AI Provider and Model configuration (OpenAI-compatible endpoints)\n'
        '  * Prompt template management with tagging and per-model scoping\n'
        '  * Generic and targeted feedback pipelines\n'
        '  * Multi-model parallel execution and result merging\n'
        '  * Call log with cost estimation and dashboard\n\n'
        'Install this module and then depend on it from your own addons to add\n'
        'AI-powered feedback to any Odoo model.'
    ),
    'author': 'APS',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/aps_ai_views.xml',
        'views/ai_prompts_views.xml',
    ],
    'installable': True,
    'application': False,
}
